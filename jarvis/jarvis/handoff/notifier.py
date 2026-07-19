"""Notifiers (§10) — reach you on your phone. Free Telegram backend + a test stub.

Interface is tiny: send(text). Telegram uses the free Bot API (token from the vault, chat
id allowlisted). The stub records messages for tests / offline.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import json
from pathlib import Path
from typing import Callable, Optional


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


class TelegramInbox:
    """Poll allowlisted Telegram messages for basic inbound control (§10 Phase 2).

    Only messages from `chat_id` are returned. `offset_path` stores Telegram's update offset
    so a command is handled once.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        offset_path: str | Path | None = None,
        fetcher: Optional[Callable[[str], dict]] = None,
    ):
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.offset_path = Path(offset_path) if offset_path else None
        self.fetcher = fetcher or self._fetch

    def _offset(self) -> int | None:
        if not self.offset_path or not self.offset_path.exists():
            return None
        try:
            data = json.loads(self.offset_path.read_text() or "{}")
            return int(data.get("offset")) if data.get("offset") is not None else None
        except Exception:
            return None

    def _save_offset(self, offset: int) -> None:
        if not self.offset_path:
            return
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        self.offset_path.write_text(json.dumps({"offset": offset}, indent=2), encoding="utf-8")

    def _fetch(self, url: str) -> dict:
        import urllib.request

        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))

    def poll(self, *, limit: int = 10) -> list[str]:
        import urllib.parse

        params = {"timeout": "0", "limit": str(limit)}
        offset = self._offset()
        if offset is not None:
            params["offset"] = str(offset)
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?{urllib.parse.urlencode(params)}"
        data = self.fetcher(url)
        if not data.get("ok"):
            return []

        messages: list[str] = []
        max_update_id = None
        for upd in data.get("result", []):
            uid = upd.get("update_id")
            if isinstance(uid, int):
                max_update_id = uid if max_update_id is None else max(max_update_id, uid)
            msg = upd.get("message") or upd.get("edited_message") or {}
            chat = msg.get("chat") or {}
            if str(chat.get("id")) != self.chat_id:
                continue
            text = (msg.get("text") or "").strip()
            if text:
                messages.append(text)

        if max_update_id is not None:
            self._save_offset(max_update_id + 1)
        return messages
