from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photobooth.storage import Store


class StoreTests(unittest.TestCase):
    def test_session_payment_and_print_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "photobooth.sqlite3")
            session_id = store.create_session(500, "USD")
            store.add_payment(session_id, "credit", 200, "coin")
            store.add_payment(session_id, "credit", 300, "bill")
            store.attach_photos(session_id, [Path(tmp) / "a.jpg"])
            job_id = store.create_print_job(session_id, Path(tmp) / "print.jpg")
            store.complete_print_job(job_id)
            store.set_session_status(session_id, "complete")

            sessions = store.recent_sessions(1)
            self.assertEqual(sessions[0]["id"], session_id)
            self.assertEqual(sessions[0]["total_paid_cents"], 500)
            self.assertEqual(sessions[0]["status"], "complete")
            store.close()


if __name__ == "__main__":
    unittest.main()

