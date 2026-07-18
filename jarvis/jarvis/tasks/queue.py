"""Durable task queue (§9) — SQLite-backed so jobs survive restarts.

Requests become jobs on this queue; a worker executes them in the background and publishes
status. Because it's persisted, in-flight work isn't lost on a crash/restart (§27).
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"    # waiting on a human (§30)
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    kind: str
    payload: dict
    status: str
    result: Optional[str]
    created: float
    updated: float


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


class TaskQueue:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def enqueue(self, kind: str, payload: dict) -> str:
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        self._conn.execute(
            "INSERT INTO jobs (id, kind, payload, status, result, created, updated) "
            "VALUES (?,?,?,?,?,?,?)",
            (job_id, kind, json.dumps(payload), JobStatus.QUEUED.value, None, now, now),
        )
        self._conn.commit()
        return job_id

    def _row_to_job(self, r) -> Job:
        return Job(r["id"], r["kind"], json.loads(r["payload"]), r["status"],
                   r["result"], r["created"], r["updated"])

    def claim_next(self) -> Optional[Job]:
        """Atomically take the oldest queued job and mark it running."""
        cur = self._conn.execute(
            "SELECT * FROM jobs WHERE status=? ORDER BY created LIMIT 1", (JobStatus.QUEUED.value,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        self.update(row["id"], JobStatus.RUNNING)
        return self._row_to_job(row)

    def update(self, job_id: str, status: JobStatus, result: Optional[str] = None) -> None:
        self._conn.execute(
            "UPDATE jobs SET status=?, result=COALESCE(?, result), updated=? WHERE id=?",
            (status.value, result, time.time(), job_id),
        )
        self._conn.commit()

    def get(self, job_id: str) -> Optional[Job]:
        r = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row_to_job(r) if r else None

    def list(self, status: Optional[JobStatus] = None) -> list[Job]:
        if status:
            rows = self._conn.execute("SELECT * FROM jobs WHERE status=? ORDER BY created",
                                      (status.value,)).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM jobs ORDER BY created").fetchall()
        return [self._row_to_job(r) for r in rows]

    def requeue_running(self) -> int:
        """On startup, reset any 'running' jobs (interrupted by a crash) back to queued."""
        cur = self._conn.execute(
            "UPDATE jobs SET status=? WHERE status=?",
            (JobStatus.QUEUED.value, JobStatus.RUNNING.value),
        )
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()
