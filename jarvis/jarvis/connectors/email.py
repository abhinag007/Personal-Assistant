"""Email / messaging (§39) — read, summarize, draft; SEND is approval-gated.

The connector interface separates reading (safe) from sending (irreversible → §11). Phase 2
ships a local stub: a fake inbox for reading and an "outbox" that captures drafts instead of
sending. Real Gmail/IMAP/Graph drops in behind the same interface with OAuth in the vault.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
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

    def create_draft(self, draft: Draft) -> bool:
        """Create a draft without sending. Connectors may override with a real draft action."""
        return self.send(draft)


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

    def create_draft(self, draft: Draft) -> bool:
        self.outbox.append(draft)
        return True


class GmailPlaywrightConnector(EmailConnector):
    """Real Gmail connector using Playwright with a persistent Chromium profile.

    The profile directory keeps cookies/session state, so the first run can be a manual login
    and later runs reuse that browser profile. Playwright is imported lazily so tests and
    offline installs do not require it.
    """

    def __init__(self, profile_dir: str | Path, *, headless: bool = False, timeout_ms: int = 45000):
        self.profile_dir = Path(profile_dir)
        self.headless = headless
        self.timeout_ms = timeout_ms

    def _open(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise ImportError(
                "Gmail connector needs Playwright: pip install playwright && "
                "playwright install chromium"
            ) from e

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        pw = sync_playwright().start()
        ctx = pw.chromium.launch_persistent_context(
            str(self.profile_dir),
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        return pw, ctx, page

    @staticmethod
    def _ensure_logged_in(page) -> None:
        body = ""
        try:
            body = page.inner_text("body", timeout=5000).lower()
        except Exception:
            pass
        if "sign in" in body or "use your google account" in body:
            try:
                page.wait_for_url("**mail.google.com/mail/u/**", timeout=300000)
            except Exception as e:
                raise RuntimeError(
                    "Gmail is not logged in for this Jarvis browser profile. "
                    "Log in in the opened browser window, then retry."
                ) from e

    def inbox(self, limit: int = 20) -> list[Message]:
        pw, ctx, page = self._open()
        try:
            page.goto("https://mail.google.com/mail/u/0/#inbox",
                      wait_until="domcontentloaded", timeout=self.timeout_ms)
            self._ensure_logged_in(page)
            try:
                page.wait_for_selector("tr[role='row']", timeout=self.timeout_ms)
            except Exception:
                pass
            rows = page.locator("tr[role='row']").all()[:max(1, limit)]
            messages: list[Message] = []
            for i, row in enumerate(rows):
                try:
                    text = " ".join(row.inner_text(timeout=3000).split())
                except Exception:
                    continue
                if not text:
                    continue
                parts = text.split()
                sender = parts[0] if parts else "unknown"
                messages.append(Message(id=f"gmail-row-{i}", sender=sender,
                                        subject=text[:180], body="", unread=True))
            return messages
        finally:
            ctx.close()
            pw.stop()

    def create_draft(self, draft: Draft) -> bool:
        pw, ctx, page = self._open()
        try:
            page.goto("https://mail.google.com/mail/u/0/#inbox",
                      wait_until="domcontentloaded", timeout=self.timeout_ms)
            self._ensure_logged_in(page)
            page.get_by_role("button", name="Compose").click(timeout=self.timeout_ms)
            page.locator("textarea[name='to']").fill(draft.to, timeout=self.timeout_ms)
            page.locator("input[name='subjectbox']").fill(draft.subject, timeout=self.timeout_ms)
            page.locator("div[aria-label='Message Body']").fill(draft.body, timeout=self.timeout_ms)
            return True
        finally:
            ctx.close()
            pw.stop()

    def send(self, draft: Draft) -> bool:
        pw, ctx, page = self._open()
        try:
            page.goto("https://mail.google.com/mail/u/0/#inbox",
                      wait_until="domcontentloaded", timeout=self.timeout_ms)
            self._ensure_logged_in(page)
            page.get_by_role("button", name="Compose").click(timeout=self.timeout_ms)
            page.locator("textarea[name='to']").fill(draft.to, timeout=self.timeout_ms)
            page.locator("input[name='subjectbox']").fill(draft.subject, timeout=self.timeout_ms)
            page.locator("div[aria-label='Message Body']").fill(draft.body, timeout=self.timeout_ms)
            page.get_by_role("button", name="Send").click(timeout=self.timeout_ms)
            return True
        finally:
            ctx.close()
            pw.stop()


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
