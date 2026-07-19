"""Nightly consolidation scheduler (§8, Phase 1 readiness).

The Consolidator already implements the "sleep pass"; this module decides when to run it.
It persists the last run day so long-running voice/proactive sessions can call poll() often
without repeating the job.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .consolidation import Consolidator
from .store import MemoryStore


class NightlyConsolidationScheduler:
    def __init__(
        self,
        store: MemoryStore,
        state_path: str | Path,
        *,
        hour: int = 2,
        log=print,
    ):
        self.store = store
        self.state_path = Path(state_path)
        self.hour = max(0, min(23, int(hour)))
        self.log = log

    def _state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text() or "{}")
        except Exception:
            return {}

    def _save(self, data: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _day_key(now: float) -> str:
        lt = time.localtime(now)
        return f"{lt.tm_year:04d}-{lt.tm_yday:03d}"

    def due(self, *, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        lt = time.localtime(now)
        if lt.tm_hour < self.hour:
            return False
        return self._state().get("last_day") != self._day_key(now)

    def run(self, *, now: Optional[float] = None) -> dict:
        now = now if now is not None else time.time()
        summary = Consolidator(self.store).run(now=now)
        data = self._state()
        data.update({"last_day": self._day_key(now), "last_run": now, "last_summary": summary})
        self._save(data)
        self.log(f"[memory] nightly consolidation: {summary}")
        return summary

    def poll(self, *, now: Optional[float] = None) -> Optional[dict]:
        now = now if now is not None else time.time()
        if not self.due(now=now):
            return None
        return self.run(now=now)
