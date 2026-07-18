"""Append-only audit trail (§16).

Every action the assistant takes is appended here as one JSON line (JSONL). The log is
append-only by contract: there is no update or delete API. Each entry carries a
correlation id so it can be tied to the decision journal (§26) and traces (§2A.5) later.

Phase 0 keeps it to a local file. Later phases add the richer decision-journal fields
(alternatives considered, confidence) on top of the same records.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, log_path: str | os.PathLike):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(
        self,
        action: str,
        summary: str,
        *,
        outcome: str = "ok",
        risk: str | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
        **extra,
    ) -> str:
        """Append one audit entry. Returns the correlation id."""
        cid = correlation_id or uuid.uuid4().hex
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "correlation_id": cid,
            "action": action,
            "summary": summary,
            "outcome": outcome,
            "risk": risk,
            "reason": reason,
        }
        if extra:
            entry["extra"] = extra
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return cid

    def read_all(self) -> list[dict]:
        """Read back every entry (for review/tests)."""
        if not self.log_path.exists():
            return []
        entries = []
        with self.log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
