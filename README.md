# Raspberry Pi Photobooth

Offline photobooth software for a Raspberry Pi 3B kiosk. It is designed for
business use without a server: every booth owns its camera, payment hardware,
printer queue, SQLite records, and local media storage.

## What is included

- Fullscreen Tkinter kiosk app that runs on Raspberry Pi OS.
- Camera adapters for Pi camera commands, USB webcam commands, and mock testing.
- Printer adapters for CUPS, custom print commands, and mock testing.
- Money adapters for mock mode, USB serial text controllers, and GPIO pulse
  controllers.
- Local SQLite records for sessions, payments, print jobs, and event logs.
- 4x6 print layout generation with Pillow.
- Pi install script and systemd service template.

## Hardware connections

Recommended business setup:

| Device | Connection | Notes |
| --- | --- | --- |
| Raspberry Pi 3B | 5V 2.5A PSU | Use a quality supply, heatsink, and read-only or backed-up SD image. |
| Camera | CSI ribbon or USB | Pi camera uses `rpicam-still` or `libcamera-still`; USB cameras can use `fswebcam`. |
| Photo printer | USB to Pi, configured in CUPS | Use the printer's own power supply. Set media and fit options in `config.toml`. |
| Bill or coin acceptor | MDB/ccTalk controller to USB serial | Recommended. The adapter translates hardware events into serial text events. |
| Money dispenser / hopper | MDB/ccTalk controller or relay driver | Recommended through the same USB serial controller. Do not connect 12V/24V payout hardware directly to GPIO. |

GPIO pulse fallback:

| Signal | Pi pin | GPIO | Protection |
| --- | --- | --- | --- |
| Coin/bill credit pulse input | Pin 11 | GPIO17 | Opto-isolator or level shifter. Never feed 12V into GPIO. |
| Hopper payout relay output | Pin 13 | GPIO27 | Transistor/relay board with flyback protection and separate hopper PSU. |
| Ground reference | Pin 6 | GND | Only share ground if your isolation/driver design requires it. |

For cash-ready business use, prefer an MDB or ccTalk USB controller. Those
controllers handle higher-voltage vending hardware safely and let this app stay
portable by reading lines such as `CREDIT:100` and sending commands such as
`PAYOUT 500`.

## Install on Raspberry Pi OS

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-tk python3-pil python3-pil.imagetk cups libcups2-bin fswebcam

git clone https://github.com/Low3ee/Raspberry-Pi-Photobooth.git /home/pi/photobooth
cd /home/pi/photobooth
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[hardware]"
cp config.example.toml config.toml
```

Edit `config.toml` for your camera, printer, and money hardware.

Run locally:

```bash
python -m photobooth --config config.toml
```

Enable kiosk service after testing:

```bash
sudo cp systemd/photobooth.service /etc/systemd/system/photobooth.service
sudo systemctl daemon-reload
sudo systemctl enable photobooth
sudo systemctl start photobooth
```

## Printer setup

1. Plug the printer into the Pi by USB.
2. Add it in CUPS.
3. Confirm its CUPS name:

```bash
lpstat -p -d
```

4. Set `[printer].driver = "cups"` and `[printer].printer_name` in
   `config.toml`.

Example:

```toml
[printer]
driver = "cups"
printer_name = "DNP_DS620"
copies = 1
lp_options = ["-o", "media=Custom.4x6in", "-o", "fit-to-page"]
```

## Money hardware setup

The app has one `MoneyDevice` interface that can accept credits and command
payouts.

### USB serial text controller

Use this for MDB/ccTalk adapters or your own microcontroller firmware.

Incoming lines:

```text
CREDIT:100
CREDIT 500
PAID
ERROR:jammed
DISPENSED:500
```

Outgoing commands are configured in `config.toml`:

```toml
[money]
driver = "serial_text"
serial_port = "/dev/ttyUSB0"
baud_rate = 9600
enable_command = "ENABLE\n"
disable_command = "DISABLE\n"
dispense_command = "PAYOUT {cents}\n"
```

### GPIO pulse controller

Use only for simple pulse acceptors and relay-driven hoppers. Add electrical
protection before connecting anything to the Pi.

```toml
[money]
driver = "gpio_pulse"
credit_gpio = 17
payout_gpio = 27
cents_per_pulse = 100
payout_cents_per_pulse = 100
```

## Scaling without servers

This is intentionally serverless at runtime. To scale to many booths:

- Build one tested SD card image and clone it per booth.
- Keep per-booth settings in `config.toml` only.
- Export each booth's `photobooth.sqlite3` and media folder periodically.
- Use CUPS locally on each Pi so printing is not network-dependent.
- Use the mock adapters on laptops for testing and the same app package on Pi.
- Keep hardware protocols behind adapters so a new printer or payout device does
  not change the kiosk UI or storage layer.

## Development

Mock mode runs without Pi hardware:

```bash
python -m photobooth --config config.example.toml
```

Run tests:

```bash
python -m unittest discover -s tests
```

