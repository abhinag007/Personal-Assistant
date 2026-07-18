"""Blocked-task handoff (§21, §30) — park a task, get the human, keep working.

When a task hits something only a human can clear (captcha, login, 2FA, a decision), it's
added to the "waiting on you" queue. Presence decides whether to ask on-screen or notify by
phone. When you provide what's needed, the task resumes from its checkpoint.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .notifier import Notifier
from .presence import Presence


@dataclass
class BlockedTask:
    id: str
    reason: str                 # what a human needs to clear
    context: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    resolved: bool = False
    resolution: Optional[str] = None


class HandoffManager:
    def __init__(self, store_path: str | Path, notifier: Optional[Notifier] = None,
                 presence: Optional[Presence] = None, log=print):
        self.path = Path(store_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.notifier = notifier
        self.presence = presence or Presence()
        self.log = log
        self._queue: dict[str, BlockedTask] = {}
        self._load()

    # ---- persistence -----------------------------------------------------

    def _load(self) -> None:
        if self.path.exists():
            for d in json.loads(self.path.read_text() or "[]"):
                self._queue[d["id"]] = BlockedTask(**d)

    def _save(self) -> None:
        self.path.write_text(json.dumps(
            [t.__dict__ for t in self._queue.values()], ensure_ascii=False, indent=2))

    # ---- API -------------------------------------------------------------

    def block(self, reason: str, context: Optional[dict] = None) -> BlockedTask:
        """Park a task needing you; ask on-screen if present, else notify your phone."""
        task = BlockedTask(id=uuid.uuid4().hex[:8], reason=reason, context=context or {})
        self._queue[task.id] = task
        self._save()

        message = f"Jarvis needs you: {reason} (id {task.id})"
        if self.presence.is_present():
            self.log(f"[handoff] {message}")
        elif self.notifier is not None:
            self.notifier.send(message)
            self.log(f"[handoff] you're away — notified your phone: {reason}")
        else:
            self.log(f"[handoff] {message} (no phone notifier configured)")
        return task

    def waiting(self) -> list[BlockedTask]:
        return [t for t in self._queue.values() if not t.resolved]

    def resolve(self, task_id: str, resolution: str = "done") -> bool:
        """You cleared the blocker — mark it resolved so the task can resume."""
        task = self._queue.get(task_id)
        if task is None or task.resolved:
            return False
        task.resolved = True
        task.resolution = resolution
        self._save()
        self.log(f"[handoff] resolved {task_id}: {resolution}")
        return True
