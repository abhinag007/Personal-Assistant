"""Decision journal (§26) — the human-readable "why" behind every decision and action.

Sits on top of the audit log (§16): the audit log answers *what happened*, the journal
answers *why* — what it did, why, alternatives considered, confidence, and outcome. This is
what lets you (and Jarvis) understand its behavior and catch mistakes.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class DecisionJournal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(
        self,
        *,
        action: str,
        summary: str,
        reasoning: str = "",
        alternatives: Optional[list[str]] = None,
        confidence: Optional[float] = None,
        outcome: Optional[str] = None,
        decision: Optional[str] = None,
        approved: Optional[bool] = None,
        correlation_id: Optional[str] = None,
    ) -> str:
        cid = correlation_id or uuid.uuid4().hex
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "id": cid,
            "action": action,
            "summary": summary,
            "reasoning": reasoning,
            "alternatives": alternatives or [],
            "confidence": confidence,
            "outcome": outcome,
            "decision": decision,
            "approved": approved,
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return cid

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(ln) for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def recent(self, n: int = 20) -> list[dict]:
        return self.read_all()[-n:]
