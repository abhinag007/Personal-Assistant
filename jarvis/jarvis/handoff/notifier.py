"""Notifiers (§10) — reach you on your phone. Free Telegram backend + a test stub.

Interface is tiny: send(text). Telegram uses the free Bot API (token from the vault, chat
id allowlisted). The stub records messages for tests / offline.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Notifier(ABC):
    @abstractmethod
    def send(self, text: str) -> bool:
        """Send a notification. Returns True on success."""


class StubNotifier(Notifier):
    """Collects messages instead of sending (tests / offline)."""

    def __init__(self):
        self.sent: list[str] = []

    def send(self, text: str) -> bool:
        self.sent.append(text)
        return True


class TelegramNotifier(Notifier):
    """Free Telegram Bot API notifier (§10). Two-way capable; here we use send."""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = str(chat_id)

    def send(self, text: str) -> bool:
        import urllib.parse
        import urllib.request

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": self.chat_id, "text": text}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10) as r:
                return r.status == 200
        except Exception:
            return False
