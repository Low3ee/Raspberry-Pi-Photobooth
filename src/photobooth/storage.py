from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    price_cents INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    total_paid_cents INTEGER NOT NULL DEFAULT 0,
                    photo_paths TEXT NOT NULL DEFAULT '[]',
                    print_path TEXT
                );

                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    cents INTEGER NOT NULL,
                    message TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS print_jobs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    level TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            self._conn.commit()

    def create_session(self, price_cents: int, currency: str) -> str:
        session_id = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (id, created_at, status, price_cents, currency)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, utc_now(), "payment", price_cents, currency),
            )
            self._conn.commit()
        return session_id

    def set_session_status(self, session_id: str, status: str) -> None:
        completed_at = utc_now() if status in {"complete", "cancelled", "failed"} else None
        with self._lock:
            self._conn.execute(
                """
                UPDATE sessions
                SET status = ?, completed_at = COALESCE(?, completed_at)
                WHERE id = ?
                """,
                (status, completed_at, session_id),
            )
            self._conn.commit()

    def add_payment(self, session_id: str, kind: str, cents: int, message: str = "") -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO payments (session_id, created_at, kind, cents, message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, utc_now(), kind, cents, message),
            )
            self._conn.execute(
                "UPDATE sessions SET total_paid_cents = total_paid_cents + ? WHERE id = ?",
                (cents, session_id),
            )
            self._conn.commit()

    def attach_photos(self, session_id: str, paths: Iterable[Path]) -> None:
        encoded = json.dumps([str(path) for path in paths])
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET photo_paths = ? WHERE id = ?",
                (encoded, session_id),
            )
            self._conn.commit()

    def attach_print(self, session_id: str, path: Path) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET print_path = ? WHERE id = ?",
                (str(path), session_id),
            )
            self._conn.commit()

    def create_print_job(self, session_id: str, file_path: Path) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO print_jobs (id, session_id, created_at, status, file_path)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, session_id, utc_now(), "queued", str(file_path)),
            )
            self._conn.commit()
        return job_id

    def complete_print_job(self, job_id: str, error: str = "") -> None:
        status = "failed" if error else "complete"
        with self._lock:
            self._conn.execute(
                """
                UPDATE print_jobs
                SET status = ?, completed_at = ?, error = ?
                WHERE id = ?
                """,
                (status, utc_now(), error, job_id),
            )
            self._conn.commit()

    def log_event(
        self,
        event_type: str,
        message: str,
        level: str = "info",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO events (created_at, level, event_type, message, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (utc_now(), level, event_type, message, json.dumps(payload or {})),
            )
            self._conn.commit()

    def recent_sessions(self, limit: int = 20) -> List[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT *
                FROM sessions
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return list(cur.fetchall())

