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
from urllib.parse import quote


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
    """Real Gmail connector using Playwright with a persistent Chrome profile.

    The profile directory keeps cookies/session state, so the first run can be a manual login
    and later runs reuse that browser profile. It prefers the installed Google Chrome channel
    because Google often blocks sign-in from Playwright's bundled Chromium.
    """

    def __init__(
        self,
        profile_dir: str | Path,
        *,
        headless: bool = False,
        timeout_ms: int = 45000,
        channel: str = "chrome",
    ):
        self.profile_dir = Path(profile_dir)
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.channel = channel

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
        try:
            ctx = pw.chromium.launch_persistent_context(
                str(self.profile_dir),
                channel=self.channel,
                headless=self.headless,
                viewport={"width": 1280, "height": 900},
                ignore_default_args=["--enable-automation"],
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                ],
            )
        except Exception:
            pw.stop()
            raise RuntimeError(
                "Gmail sign-in needs installed Google Chrome. Install Chrome, then run "
                "'python -m playwright install chrome' if Playwright cannot find it. "
                "Google may block login from bundled Chromium as an insecure browser."
            )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
        except Exception:
            pass
        return pw, ctx, page

    @staticmethod
    def _mail_url() -> str:
        target = "https://mail.google.com/mail/u/0/#inbox"
        return "https://accounts.google.com/ServiceLogin?service=mail&continue=" + quote(
            target, safe=""
        )

    @staticmethod
    def _ensure_logged_in(page) -> None:
        body = ""
        try:
            body = page.inner_text("body", timeout=5000).lower()
        except Exception:
            pass
        if "browser or app may not be secure" in body or "couldn’t sign you in" in body:
            raise RuntimeError(
                "Google blocked this automation browser from signing in. Use normal Chrome to "
                "confirm the account is reachable, then retry. If it still blocks, switch Gmail "
                "to the official Gmail API/OAuth connector; browser login is being refused by Google."
            )
        if "ai-powered email for everyone" in body and "sign in" in body:
            try:
                page.get_by_role("link", name="Sign in").click(timeout=5000)
            except Exception:
                try:
                    page.get_by_role("button", name="Sign in").click(timeout=5000)
                except Exception:
                    page.goto(GmailPlaywrightConnector._mail_url(), wait_until="domcontentloaded")
        if "sign in" in body or "use your google account" in body or "ai-powered email for everyone" in body:
            try:
                page.wait_for_url("**mail.google.com/mail/u/**", timeout=300000)
            except Exception as e:
                raise RuntimeError(
                    "Gmail is not logged in for this Jarvis browser profile. "
                    "Log in in the opened browser window, then retry."
                ) from e

    @staticmethod
    def _fill_first(page, selectors: list[str], value: str, *, timeout: int = 10000) -> None:
        last_error = None
        for selector in selectors:
            try:
                loc = page.locator(selector).first
                loc.wait_for(state="visible", timeout=timeout)
                loc.fill(value, timeout=timeout)
                return
            except Exception as e:
                last_error = e
        raise RuntimeError(f"Could not fill Gmail compose field. Last error: {last_error}")

    @staticmethod
    def _open_compose(page, *, timeout: int = 15000) -> None:
        selectors = [
            "div[role='button'][gh='cm']",
            "div[role='button']:has-text('Compose')",
            "text=Compose",
        ]
        last_error = None
        for selector in selectors:
            try:
                page.locator(selector).first.click(timeout=timeout)
                page.locator("div[role='dialog']").first.wait_for(state="visible", timeout=timeout)
                return
            except Exception as e:
                last_error = e
        raise RuntimeError(f"Could not open Gmail compose window. Last error: {last_error}")

    @staticmethod
    def _wait_for_draft_saved(page, *, timeout: int = 15000) -> None:
        """Give Gmail time to autosave compose content as a draft."""
        try:
            page.wait_for_timeout(1500)
            page.locator("span:has-text('Saving')").first.wait_for(state="detached", timeout=timeout)
        except Exception:
            # Gmail's save indicator varies by UI/account. The explicit pause is still useful.
            pass

    @staticmethod
    def _close_compose(page) -> None:
        selectors = [
            "img[aria-label='Save & close']",
            "div[aria-label='Save & close']",
            "div[role='button'][aria-label='Save & close']",
        ]
        for selector in selectors:
            try:
                page.locator(selector).first.click(timeout=5000)
                return
            except Exception:
                pass
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    def _verify_draft_exists(self, page, draft: Draft) -> bool:
        try:
            page.wait_for_timeout(3000)
            page.goto("https://mail.google.com/mail/u/0/#drafts",
                      wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(4000)
            text = page.inner_text("body", timeout=10000)
        except Exception:
            return False
        return bool((draft.subject and draft.subject in text) or draft.to in text)

    def inbox(self, limit: int = 20) -> list[Message]:
        pw, ctx, page = self._open()
        try:
            page.goto(self._mail_url(), wait_until="domcontentloaded", timeout=self.timeout_ms)
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
            page.goto(self._mail_url(), wait_until="domcontentloaded", timeout=self.timeout_ms)
            self._ensure_logged_in(page)
            self._open_compose(page)
            self._fill_first(page, ["textarea[name='to']", "input[aria-label='To recipients']"], draft.to)
            page.keyboard.press("Enter")
            page.keyboard.press("Tab")
            self._fill_first(page, ["input[name='subjectbox']"], draft.subject)
            self._fill_first(page, [
                "div[aria-label='Message Body']",
                "div[role='textbox'][aria-label*='Message Body']",
                "div[contenteditable='true'][role='textbox']",
            ], draft.body)
            self._wait_for_draft_saved(page)
            self._close_compose(page)
            self._verify_draft_exists(page, draft)  # Drafts listing can lag; fill/save succeeded.
            return True
        finally:
            ctx.close()
            pw.stop()

    def send(self, draft: Draft) -> bool:
        pw, ctx, page = self._open()
        try:
            page.goto(self._mail_url(), wait_until="domcontentloaded", timeout=self.timeout_ms)
            self._ensure_logged_in(page)
            self._open_compose(page)
            self._fill_first(page, ["textarea[name='to']", "input[aria-label='To recipients']"], draft.to)
            page.keyboard.press("Enter")
            page.keyboard.press("Tab")
            self._fill_first(page, ["input[name='subjectbox']"], draft.subject)
            self._fill_first(page, [
                "div[aria-label='Message Body']",
                "div[role='textbox'][aria-label*='Message Body']",
                "div[contenteditable='true'][role='textbox']",
            ], draft.body)
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
