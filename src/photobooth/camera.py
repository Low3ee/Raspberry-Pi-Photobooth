from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List

from .config import CameraSettings


class CameraError(RuntimeError):
    pass


class Camera:
    def capture_photo(self, output_path: Path) -> Path:
        raise NotImplementedError


class MockCamera(Camera):
    def __init__(self, settings: CameraSettings):
        self.settings = settings

    def capture_photo(self, output_path: Path) -> Path:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as exc:  # pragma: no cover
            raise CameraError("Pillow is required for the mock camera") from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (self.settings.width, self.settings.height), "#e5e7eb")
        draw = ImageDraw.Draw(image)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = ["MOCK PHOTO", timestamp, output_path.stem]
        try:
            title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 72)
            body_font = ImageFont.truetype("DejaVuSans.ttf", 36)
        except OSError:
            title_font = ImageFont.load_default()
            body_font = ImageFont.load_default()

        draw.rectangle((0, 0, self.settings.width, self.settings.height), fill="#f9fafb")
        draw.rectangle((48, 48, self.settings.width - 48, self.settings.height - 48), outline="#111827", width=6)
        y = self.settings.height // 2 - 100
        for index, line in enumerate(lines):
            font = title_font if index == 0 else body_font
            bbox = draw.textbbox((0, 0), line, font=font)
            x = (self.settings.width - (bbox[2] - bbox[0])) // 2
            draw.text((x, y), line, fill="#111827", font=font)
            y += (bbox[3] - bbox[1]) + 28

        image.save(output_path, "JPEG", quality=92)
        return output_path


class PiStillCamera(Camera):
    def __init__(self, settings: CameraSettings):
        self.settings = settings
        self.command = _first_available(["rpicam-still", "libcamera-still"])
        if not self.command:
            raise CameraError("Install rpicam-apps or libcamera-apps for Pi camera capture")

    def capture_photo(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.command,
            "-n",
            "--width",
            str(self.settings.width),
            "--height",
            str(self.settings.height),
            "--timeout",
            str(self.settings.warmup_ms),
            "-o",
            str(output_path),
        ]
        _run(cmd, self.settings.timeout_seconds)
        return output_path


class FsWebcamCamera(Camera):
    def __init__(self, settings: CameraSettings):
        self.settings = settings
        if not shutil.which("fswebcam"):
            raise CameraError("Install fswebcam for USB webcam capture")

    def capture_photo(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "fswebcam",
            "-d",
            self.settings.device,
            "-r",
            f"{self.settings.width}x{self.settings.height}",
            "--no-banner",
            str(output_path),
        ]
        _run(cmd, self.settings.timeout_seconds)
        return output_path


class CommandCamera(Camera):
    def __init__(self, settings: CameraSettings):
        if not settings.command:
            raise CameraError("camera.command is required when camera.driver = 'command'")
        self.settings = settings

    def capture_photo(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = self.settings.command.format(
            output=str(output_path),
            width=self.settings.width,
            height=self.settings.height,
            device=self.settings.device,
        )
        _run(command, self.settings.timeout_seconds, shell=True)
        return output_path


def build_camera(settings: CameraSettings) -> Camera:
    driver = settings.driver.lower().strip()
    if driver == "mock":
        return MockCamera(settings)
    if driver in {"pi", "libcamera", "rpicam"}:
        return PiStillCamera(settings)
    if driver in {"fswebcam", "usb"}:
        return FsWebcamCamera(settings)
    if driver == "command":
        return CommandCamera(settings)
    raise CameraError(f"Unknown camera driver: {settings.driver}")


def _first_available(commands: List[str]) -> str:
    for command in commands:
        if shutil.which(command):
            return command
    return ""


def _run(command, timeout_seconds: int, shell: bool = False) -> None:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=shell,
        )
    except subprocess.TimeoutExpired as exc:
        raise CameraError(f"Camera command timed out after {timeout_seconds}s") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise CameraError(f"Camera command failed: {stderr}")

