"""Graceful failure + presence-aware human handoff (§21, §30) + notifications (§10)."""
from .notifier import Notifier, StubNotifier, TelegramNotifier  # noqa: F401
from .presence import Presence  # noqa: F401
from .handoff import BlockedTask, HandoffManager  # noqa: F401
