"""Email / messaging (§39) — read, summarize, draft; SEND is approval-gated.

The connector interface separates reading (safe) from sending (irreversible → §11). Phase 2
ships a local stub: a fake inbox for reading and an "outbox" that captures drafts instead of
sending. Real Gmail/IMAP/Graph drops in behind the same interface with OAuth in the vault.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Message:
    id: str
    sender: str
    subject: str
    body: str
    unread: bool = True


@dataclass
class Draft:
    to: str
    subject: str
    body: str


class EmailConnector(ABC):
    @abstractmethod
    def inbox(self, limit: int = 20) -> list[Message]: ...

    @abstractmethod
    def send(self, draft: Draft) -> bool:
        """Actually send. MUST be called only after §11 approval by the caller."""


class StubEmailConnector(EmailConnector):
    """A fake inbox + captured outbox for offline/testing."""

    def __init__(self, seed: Optional[list[Message]] = None):
        self._inbox = list(seed or [])
        self.outbox: list[Draft] = []   # what "send" captured (never actually emailed)

    def inbox(self, limit: int = 20) -> list[Message]:
        return self._inbox[:limit]

    def send(self, draft: Draft) -> bool:
        self.outbox.append(draft)
        return True


def summarize_inbox(connector: EmailConnector, adapter, limit: int = 10) -> str:
    """Read + summarize what needs attention (does NOT send anything)."""
    msgs = connector.inbox(limit=limit)
    if not msgs:
        return "Your inbox is empty."
    listing = "\n".join(f"- from {m.sender}: {m.subject}" for m in msgs)
    try:
        from ..llm.adapter import Message as LMsg
        resp = adapter.chat([
            LMsg("system", "Summarize which emails need the user's attention, briefly."),
            LMsg("user", listing),
        ])
        if resp.text.strip():
            return resp.text.strip()
    except Exception:
        pass
    return listing
