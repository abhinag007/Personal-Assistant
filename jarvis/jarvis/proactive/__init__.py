"""Proactive engine (§25, §30, §40) — Jarvis speaks first, or notifies your phone.

Watches for things worth telling you about (due reminders, finished tasks, blockers, a
scheduled briefing) and routes each by presence: speak aloud if you're at the machine, send
to your phone (Telegram) if you're away. Respects quiet hours and de-duplicates so it never
repeats or spams.
"""
from .engine import ProactiveEngine  # noqa: F401
