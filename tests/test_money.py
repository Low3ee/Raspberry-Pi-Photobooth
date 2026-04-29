from __future__ import annotations

import unittest

from photobooth.config import MoneySettings
from photobooth.money import MockMoneyDevice, SerialTextMoneyDevice


class FakeSerial:
    def __init__(self) -> None:
        self.writes = []

    def write(self, data: bytes) -> None:
        self.writes.append(data.decode("utf-8"))

    def flush(self) -> None:
        pass


class MoneyTests(unittest.TestCase):
    def test_mock_credit_reaches_paid(self) -> None:
        device = MockMoneyDevice()
        device.start_transaction(200)
        device.credit(100)
        device.credit(100)
        kinds = [event.kind for event in device.poll_events()]
        self.assertEqual(kinds, ["credit", "credit", "paid"])

    def test_serial_cancel_finish_and_dispense_commands(self) -> None:
        settings = MoneySettings(
            enable_command="ENABLE\n",
            disable_command="DISABLE\n",
            reject_command="REJECT\n",
            dispense_command="PAYOUT {cents}\n",
        )
        device = SerialTextMoneyDevice(settings)
        fake = FakeSerial()
        device._serial = fake

        device.cancel_transaction()
        self.assertEqual(fake.writes, ["REJECT\n", "DISABLE\n"])

        fake.writes.clear()
        device.finish_transaction()
        self.assertEqual(fake.writes, ["DISABLE\n"])

        fake.writes.clear()
        device.dispense(500)
        self.assertEqual(fake.writes, ["PAYOUT 500\n"])


if __name__ == "__main__":
    unittest.main()

