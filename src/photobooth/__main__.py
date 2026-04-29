from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .app import run_app
from .config import load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the offline photobooth kiosk.")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config TOML. Defaults to PHOTOBOOTH_CONFIG or config.toml.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)
    run_app(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
