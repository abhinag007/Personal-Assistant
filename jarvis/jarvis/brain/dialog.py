"""Multi-turn conversation context (§19).

Holds the last N turns of the current exchange (the "conscious" working set). It is
separate from long-term memory (§8) and is cleared when the conversation ends or times
out. Follow-ups can reference earlier turns without repeating the wake word.
"""
from __future__ import annotations

import time

from ..llm.adapter import Message


class DialogWindow:
    def __init__(self, max_turns: int = 8, timeout_seconds: float = 120.0):
        self.max_turns = max_turns
        self.timeout_seconds = timeout_seconds
        self._turns: list[Message] = []
        self._last_activity = time.time()

    def _expire_if_stale(self, now: float) -> None:
        if self._turns and (now - self._last_activity) > self.timeout_seconds:
            self._turns.clear()

    def add_user(self, text: str, *, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self._expire_if_stale(now)
        self._turns.append(Message("user", text))
        self._last_activity = now
        self._trim()

    def add_assistant(self, text: str) -> None:
        self._turns.append(Message("assistant", text))
        self._last_activity = time.time()
        self._trim()

    def _trim(self) -> None:
        # Keep at most max_turns*2 messages (user+assistant pairs).
        limit = self.max_turns * 2
        if len(self._turns) > limit:
            self._turns = self._turns[-limit:]

    def history(self) -> list[Message]:
        return list(self._turns)

    def clear(self) -> None:
        self._turns.clear()

    def is_active(self, *, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        return bool(self._turns) and (now - self._last_activity) <= self.timeout_seconds
