#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/pi/photobooth}"

sudo apt update
sudo apt install -y \
  python3 \
  python3-venv \
  python3-tk \
  python3-pil \
  python3-pil.imagetk \
  cups \
  libcups2-bin \
  fswebcam

sudo apt install -y rpicam-apps || sudo apt install -y libcamera-apps || true

cd "$APP_DIR"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e ".[hardware]"

if [ ! -f config.toml ]; then
  cp config.example.toml config.toml
fi

echo "Installed. Edit $APP_DIR/config.toml, then run:"
echo "$APP_DIR/.venv/bin/python -m photobooth --config $APP_DIR/config.toml"
