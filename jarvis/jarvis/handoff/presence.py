"""Presence detection (§30) — are you at the PC, or away?

Decides whether to ask you on-screen or notify your phone. On macOS it can read the system
idle time (seconds since last keyboard/mouse input); if that's unavailable, it falls back to
a manual/assumed-present flag. Pure and injectable so it's testable.
"""
from __future__ import annotations

from typing import Callable, Optional


def _macos_idle_seconds() -> Optional[float]:
    """Seconds since last user input on macOS, via ioreg. None if unavailable."""
    import subprocess

    try:
        out = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=3
        ).stdout
        for line in out.splitlines():
            if "HIDIdleTime" in line:
                ns = int(line.split("=")[-1].strip())
                return ns / 1_000_000_000  # nanoseconds → seconds
    except Exception:
        return None
    return None


class Presence:
    def __init__(self, away_after_seconds: float = 120.0,
                 idle_fn: Optional[Callable[[], Optional[float]]] = None):
        self.away_after = away_after_seconds
        self._idle_fn = idle_fn or _macos_idle_seconds

    def idle_seconds(self) -> Optional[float]:
        return self._idle_fn()

    def is_present(self) -> bool:
        """True if you seem to be at the machine. Unknown idle → assume present."""
        idle = self.idle_seconds()
        if idle is None:
            return True
        return idle < self.away_after
