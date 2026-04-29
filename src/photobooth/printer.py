from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List

from .config import PrinterSettings


class PrinterError(RuntimeError):
    pass


@dataclass
class PrintResult:
    job_id: str
    output: str = ""


class Printer:
    def print_file(self, file_path: Path, copies: int = 1) -> PrintResult:
        raise NotImplementedError


class MockPrinter(Printer):
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def print_file(self, file_path: Path, copies: int = 1) -> PrintResult:
        job_id = uuid.uuid4().hex
        for copy_index in range(copies):
            suffix = f"{job_id}-{copy_index + 1}{Path(file_path).suffix}"
            shutil.copy2(file_path, self.output_dir / suffix)
        return PrintResult(job_id=job_id, output=str(self.output_dir))


class CupsPrinter(Printer):
    def __init__(self, settings: PrinterSettings):
        if not shutil.which("lp"):
            raise PrinterError("CUPS command 'lp' is not installed")
        self.settings = settings

    def print_file(self, file_path: Path, copies: int = 1) -> PrintResult:
        cmd: List[str] = ["lp"]
        if self.settings.printer_name:
            cmd.extend(["-d", self.settings.printer_name])
        cmd.extend(["-n", str(copies)])
        cmd.extend(self.settings.lp_options)
        cmd.append(str(file_path))
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
        if completed.returncode != 0:
            raise PrinterError(completed.stderr.strip() or completed.stdout.strip())
        return PrintResult(job_id=_extract_lp_job_id(completed.stdout), output=completed.stdout.strip())


class CommandPrinter(Printer):
    def __init__(self, settings: PrinterSettings):
        if not settings.command:
            raise PrinterError("printer.command is required when printer.driver = 'command'")
        self.settings = settings

    def print_file(self, file_path: Path, copies: int = 1) -> PrintResult:
        command = self.settings.command.format(file=str(file_path), copies=copies)
        completed = subprocess.run(command, shell=True, capture_output=True, text=True, check=False, timeout=60)
        if completed.returncode != 0:
            raise PrinterError(completed.stderr.strip() or completed.stdout.strip())
        return PrintResult(job_id=uuid.uuid4().hex, output=completed.stdout.strip())


def build_printer(settings: PrinterSettings, data_dir: Path) -> Printer:
    driver = settings.driver.lower().strip()
    if driver == "mock":
        return MockPrinter(data_dir / "mock-prints")
    if driver == "cups":
        return CupsPrinter(settings)
    if driver == "command":
        return CommandPrinter(settings)
    raise PrinterError(f"Unknown printer driver: {settings.driver}")


def _extract_lp_job_id(output: str) -> str:
    parts = output.strip().split()
    if len(parts) >= 4:
        return parts[3]
    return uuid.uuid4().hex

