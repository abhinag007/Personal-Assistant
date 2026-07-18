"""Calendar & reminders (§38) — local store + due detection.

A local SQLite store of reminders/events with due times. The scheduler/briefing reads it;
a reminder tool writes to it. Optional Google/Outlook sync is a later connector behind the
same interface. Natural-language time parsing is intentionally simple here (absolute epoch
or a few relative forms); the model can convert phrasing to a timestamp upstream.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Reminder:
    id: str
    text: str
    due: float             # epoch seconds
    created: float
    done: bool = False


_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    due REAL NOT NULL,
    created REAL NOT NULL,
    done INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_rem_due ON reminders(due);
"""


class CalendarStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def add(self, text: str, due: float) -> str:
        rid = uuid.uuid4().hex[:10]
        self._conn.execute(
            "INSERT INTO reminders (id, text, due, created, done) VALUES (?,?,?,?,0)",
            (rid, text, float(due), time.time()),
        )
        self._conn.commit()
        return rid

    def _row(self, r) -> Reminder:
        return Reminder(r["id"], r["text"], r["due"], r["created"], bool(r["done"]))

    def upcoming(self, within_seconds: Optional[float] = None, *, now: Optional[float] = None) -> list[Reminder]:
        now = now if now is not None else time.time()
        if within_seconds is None:
            rows = self._conn.execute(
                "SELECT * FROM reminders WHERE done=0 AND due>=? ORDER BY due", (now,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM reminders WHERE done=0 AND due BETWEEN ? AND ? ORDER BY due",
                (now, now + within_seconds)).fetchall()
        return [self._row(r) for r in rows]

    def due_now(self, *, now: Optional[float] = None) -> list[Reminder]:
        now = now if now is not None else time.time()
        rows = self._conn.execute(
            "SELECT * FROM reminders WHERE done=0 AND due<=? ORDER BY due", (now,)).fetchall()
        return [self._row(r) for r in rows]

    def mark_done(self, rid: str) -> None:
        self._conn.execute("UPDATE reminders SET done=1 WHERE id=?", (rid,))
        self._conn.commit()

    def all(self) -> list[Reminder]:
        rows = self._conn.execute("SELECT * FROM reminders ORDER BY due").fetchall()
        return [self._row(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
