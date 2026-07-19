"""Browser tool (§6, §30) — read JS-rendered pages; hand off on human-only blockers.

Uses Playwright (lazy import) to render pages that plain fetch can't (JavaScript sites).
`read(url)` navigates and returns the visible text. Interactive automation (logins, forms)
is where captchas/2FA appear — those raise NeedsHuman so the handoff manager (§30) can park
the task and get you. Install once:  pip install playwright && playwright install chromium
"""
from __future__ import annotations

from typing import Optional

_INSTALL = ("Browser tool needs Playwright:\n"
            "    pip install playwright && playwright install chromium")


class NeedsHuman(Exception):
    """Raised when a page needs a human (captcha, login, 2FA) → routes to handoff (§30)."""


# Heuristic markers that a page is asking for a human.
_BLOCKER_SIGNS = ("captcha", "verify you are human", "are you a robot",
                  "unusual traffic", "sign in to continue", "log in to continue")


class Browser:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw = None
        self._browser = None

    def _ensure(self):
        if self._browser is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as e:
                raise ImportError(_INSTALL) from e
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self.headless)
        return self._browser

    def read(self, url: str, *, detect_blockers: bool = True) -> str:
        """Navigate and return the page's visible text. Raises NeedsHuman on a blocker."""
        browser = self._ensure()
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            text = page.inner_text("body")
        finally:
            page.close()
        if detect_blockers:
            low = text.lower()
            if any(s in low for s in _BLOCKER_SIGNS):
                raise NeedsHuman(f"{url} needs a human (login/captcha).")
        return text

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._browser = None
        self._pw = None
