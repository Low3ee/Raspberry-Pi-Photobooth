from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - used on Python 3.9/3.10
    import tomli as tomllib  # type: ignore


@dataclass
class AppSettings:
    title: str = "Photo Booth"
    fullscreen: bool = True
    price_cents: int = 500
    currency: str = "USD"
    data_dir: Path = Path("./data")
    photo_count: int = 4
    countdown_seconds: int = 3
    auto_print: bool = False
    allow_retake: bool = True
    refund_on_cancel: bool = True


@dataclass
class CameraSettings:
    driver: str = "mock"
    width: int = 1280
    height: int = 720
    timeout_seconds: int = 20
    warmup_ms: int = 1200
    device: str = "/dev/video0"
    command: str = ""


@dataclass
class LayoutSettings:
    width_px: int = 1200
    height_px: int = 1800
    dpi: int = 300
    margin_px: int = 72
    gap_px: int = 36
    background: str = "#ffffff"
    accent: str = "#111827"
    caption: str = "Thanks for visiting"


@dataclass
class PrinterSettings:
    driver: str = "mock"
    printer_name: str = ""
    copies: int = 1
    lp_options: List[str] = field(default_factory=lambda: ["-o", "fit-to-page"])
    command: str = ""


@dataclass
class MoneySettings:
    driver: str = "mock"
    serial_port: str = "/dev/ttyUSB0"
    baud_rate: int = 9600
    poll_interval_ms: int = 100
    enable_command: str = "ENABLE\n"
    disable_command: str = "DISABLE\n"
    dispense_command: str = "PAYOUT {cents}\n"
    reject_command: str = "REJECT\n"
    credit_gpio: int = 17
    payout_gpio: int = 27
    cents_per_pulse: int = 100
    payout_cents_per_pulse: int = 100
    payout_pulse_ms: int = 120


@dataclass
class PhotoboothConfig:
    app: AppSettings = field(default_factory=AppSettings)
    camera: CameraSettings = field(default_factory=CameraSettings)
    layout: LayoutSettings = field(default_factory=LayoutSettings)
    printer: PrinterSettings = field(default_factory=PrinterSettings)
    money: MoneySettings = field(default_factory=MoneySettings)


def load_config(path: Optional[Path] = None) -> PhotoboothConfig:
    config_path = path or _default_config_path()
    raw: Dict[str, Any] = {}

    if config_path and config_path.exists():
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)

    config = PhotoboothConfig(
        app=_settings(AppSettings, raw.get("app", {})),
        camera=_settings(CameraSettings, raw.get("camera", {})),
        layout=_settings(LayoutSettings, raw.get("layout", {})),
        printer=_settings(PrinterSettings, raw.get("printer", {})),
        money=_settings(MoneySettings, raw.get("money", {})),
    )
    config.app.data_dir = Path(config.app.data_dir).expanduser().resolve()
    _validate(config)
    return config


def _default_config_path() -> Optional[Path]:
    env_path = os.environ.get("PHOTOBOOTH_CONFIG")
    if env_path:
        return Path(env_path)
    local = Path("config.toml")
    if local.exists():
        return local
    example = Path("config.example.toml")
    if example.exists():
        return example
    return None


def _settings(cls: Any, values: Dict[str, Any]) -> Any:
    allowed = set(cls.__dataclass_fields__.keys())
    clean = {key: value for key, value in values.items() if key in allowed}
    return cls(**clean)


def _validate(config: PhotoboothConfig) -> None:
    if config.app.price_cents < 0:
        raise ValueError("app.price_cents must be 0 or greater")
    if not 1 <= config.app.photo_count <= 8:
        raise ValueError("app.photo_count must be between 1 and 8")
    if config.app.countdown_seconds < 0:
        raise ValueError("app.countdown_seconds must be 0 or greater")
    if config.printer.copies < 1:
        raise ValueError("printer.copies must be at least 1")
    if config.layout.width_px < 100 or config.layout.height_px < 100:
        raise ValueError("layout dimensions are too small")
    if config.money.cents_per_pulse <= 0:
        raise ValueError("money.cents_per_pulse must be positive")
    if config.money.payout_cents_per_pulse <= 0:
        raise ValueError("money.payout_cents_per_pulse must be positive")

