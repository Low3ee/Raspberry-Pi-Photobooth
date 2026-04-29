from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

from .config import MoneySettings


class MoneyError(RuntimeError):
    pass


@dataclass
class PaymentEvent:
    kind: str
    cents: int = 0
    message: str = ""


class MoneyDevice:
    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def start_transaction(self, price_cents: int) -> None:
        pass

    def cancel_transaction(self) -> None:
        pass

    def finish_transaction(self) -> None:
        pass

    def poll_events(self) -> List[PaymentEvent]:
        return []

    def dispense(self, cents: int) -> PaymentEvent:
        return PaymentEvent("dispensed", cents, "No payout hardware configured")


class MockMoneyDevice(MoneyDevice):
    def __init__(self) -> None:
        self.price_cents = 0
        self.balance_cents = 0
        self._events: List[PaymentEvent] = []
        self._lock = threading.Lock()

    def start_transaction(self, price_cents: int) -> None:
        with self._lock:
            self.price_cents = price_cents
            self.balance_cents = 0
            self._events.clear()

    def cancel_transaction(self) -> None:
        with self._lock:
            self._events.clear()

    def finish_transaction(self) -> None:
        with self._lock:
            self._events.clear()

    def credit(self, cents: int) -> None:
        with self._lock:
            self.balance_cents += cents
            self._events.append(PaymentEvent("credit", cents, "Mock credit"))
            if self.balance_cents >= self.price_cents:
                self._events.append(PaymentEvent("paid", self.balance_cents, "Mock paid"))

    def poll_events(self) -> List[PaymentEvent]:
        with self._lock:
            events = list(self._events)
            self._events.clear()
            return events

    def dispense(self, cents: int) -> PaymentEvent:
        return PaymentEvent("dispensed", cents, "Mock payout")


class SerialTextMoneyDevice(MoneyDevice):
    def __init__(self, settings: MoneySettings):
        self.settings = settings
        self.price_cents = 0
        self.balance_cents = 0
        self._serial = None
        self._buffer = ""

    def open(self) -> None:
        try:
            import serial
        except ImportError as exc:  # pragma: no cover
            raise MoneyError("Install pyserial to use serial money hardware") from exc

        self._serial = serial.Serial(
            self.settings.serial_port,
            self.settings.baud_rate,
            timeout=0,
            write_timeout=2,
        )

    def close(self) -> None:
        if self._serial:
            self._send(self.settings.disable_command)
            self._serial.close()
            self._serial = None

    def start_transaction(self, price_cents: int) -> None:
        self.price_cents = price_cents
        self.balance_cents = 0
        self._buffer = ""
        self._send(self.settings.enable_command)

    def cancel_transaction(self) -> None:
        self._send(self.settings.reject_command)
        self._send(self.settings.disable_command)

    def finish_transaction(self) -> None:
        self._send(self.settings.disable_command)

    def poll_events(self) -> List[PaymentEvent]:
        if not self._serial:
            return []
        waiting = getattr(self._serial, "in_waiting", 0)
        if waiting <= 0:
            return []
        chunk = self._serial.read(waiting).decode("utf-8", errors="replace")
        self._buffer += chunk
        lines = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if line:
                lines.append(line)

        events: List[PaymentEvent] = []
        for line in lines:
            event = self._parse_line(line)
            if event:
                events.append(event)
                if event.kind == "credit":
                    self.balance_cents += event.cents
                    if self.balance_cents >= self.price_cents:
                        events.append(PaymentEvent("paid", self.balance_cents, "Balance reached price"))
        return events

    def dispense(self, cents: int) -> PaymentEvent:
        if cents <= 0:
            return PaymentEvent("dispensed", 0, "No payout needed")
        command = self.settings.dispense_command.format(cents=cents, amount=f"{cents / 100:.2f}")
        self._send(command)
        return PaymentEvent("dispensed", cents, "Payout command sent")

    def _send(self, command: str) -> None:
        if not self._serial or not command:
            return
        self._serial.write(command.encode("utf-8"))
        self._serial.flush()

    def _parse_line(self, line: str) -> Optional[PaymentEvent]:
        upper = line.upper()
        credit = re.match(r"^CREDIT[:\s]+(\d+)", upper)
        if credit:
            return PaymentEvent("credit", int(credit.group(1)), line)
        dispensed = re.match(r"^DISPENSED[:\s]+(\d+)", upper)
        if dispensed:
            return PaymentEvent("dispensed", int(dispensed.group(1)), line)
        if upper == "PAID":
            return PaymentEvent("paid", self.balance_cents, line)
        if upper.startswith("ERROR"):
            return PaymentEvent("error", 0, line)
        return PaymentEvent("message", 0, line)


class GpioPulseMoneyDevice(MoneyDevice):
    def __init__(self, settings: MoneySettings):
        self.settings = settings
        self.price_cents = 0
        self.balance_cents = 0
        self._pulse_count = 0
        self._events: List[PaymentEvent] = []
        self._gpio = None
        self._lock = threading.Lock()

    def open(self) -> None:
        try:
            import RPi.GPIO as GPIO
        except ImportError as exc:  # pragma: no cover
            raise MoneyError("Install RPi.GPIO to use GPIO pulse money hardware") from exc

        self._gpio = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.settings.credit_gpio, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(self.settings.payout_gpio, GPIO.OUT, initial=GPIO.LOW)
        GPIO.add_event_detect(self.settings.credit_gpio, GPIO.RISING, callback=self._on_credit_pulse, bouncetime=80)

    def close(self) -> None:
        if self._gpio:
            self._gpio.cleanup((self.settings.credit_gpio, self.settings.payout_gpio))
            self._gpio = None

    def start_transaction(self, price_cents: int) -> None:
        with self._lock:
            self.price_cents = price_cents
            self.balance_cents = 0
            self._pulse_count = 0
            self._events.clear()

    def cancel_transaction(self) -> None:
        with self._lock:
            self._events.clear()

    def finish_transaction(self) -> None:
        with self._lock:
            self._events.clear()

    def poll_events(self) -> List[PaymentEvent]:
        with self._lock:
            if self._pulse_count:
                cents = self._pulse_count * self.settings.cents_per_pulse
                self._pulse_count = 0
                self.balance_cents += cents
                self._events.append(PaymentEvent("credit", cents, "GPIO pulse credit"))
                if self.balance_cents >= self.price_cents:
                    self._events.append(PaymentEvent("paid", self.balance_cents, "Balance reached price"))
            events = list(self._events)
            self._events.clear()
            return events

    def dispense(self, cents: int) -> PaymentEvent:
        if not self._gpio:
            raise MoneyError("GPIO money device is not open")
        pulses = cents // self.settings.payout_cents_per_pulse
        for _ in range(pulses):
            self._gpio.output(self.settings.payout_gpio, self._gpio.HIGH)
            time.sleep(self.settings.payout_pulse_ms / 1000)
            self._gpio.output(self.settings.payout_gpio, self._gpio.LOW)
            time.sleep(0.08)
        return PaymentEvent("dispensed", pulses * self.settings.payout_cents_per_pulse, "GPIO payout pulses sent")

    def _on_credit_pulse(self, _channel) -> None:
        with self._lock:
            self._pulse_count += 1


def build_money_device(settings: MoneySettings) -> MoneyDevice:
    driver = settings.driver.lower().strip()
    if driver in {"mock", "disabled", "none"}:
        return MockMoneyDevice()
    if driver in {"serial", "serial_text", "mdb", "cctalk"}:
        return SerialTextMoneyDevice(settings)
    if driver in {"gpio", "gpio_pulse"}:
        return GpioPulseMoneyDevice(settings)
    raise MoneyError(f"Unknown money driver: {settings.driver}")
