"""Kill switch — "Jarvis, end yourself" (§23).

An independent listener that, on hearing the kill phrase, shuts the entire process
group down immediately. It is deliberately simple and self-contained so that a wedged
or misbehaving main loop cannot prevent shutdown.

Design notes for the real system:
  * On the real machine this runs as its own process/thread, independent of the brain
    loop, and issues an OS-level termination to the whole process group.
  * In Phase 0 it exposes: (a) a text checker (used by the voice layer later and by
    tests now), and (b) a `trigger()` that performs the actual teardown.
  * The phrase and this handler live in the immutable core; the AI can never modify them.
"""
from __future__ import annotations

import os
import signal
import sys
import threading
from typing import Callable, Optional

from .policy import KILL_PHRASE


# The kill command is safety-critical, so matching is tolerant of speech-to-text errors.
# "end" is very commonly misheard as "and", so both are accepted, plus a few clear variants.
_KILL_VARIANTS = (
    "end yourself",
    "and yourself",      # common STT mishearing of "end yourself"
    "end your self",
    "kill yourself",
    "shut yourself down",
    "shut down yourself",
    "terminate yourself",
)


def _normalize(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in text)
    return " ".join(cleaned.split())


def is_kill_phrase(text: str) -> bool:
    """True if the transcript is the kill command. Tolerant of STT errors (end↔and, etc.).

    Requires the wake name ('jarvis') AND a shutdown variant in the same utterance, so it
    won't fire on ordinary conversation.
    """
    if not text:
        return False
    normalized = _normalize(text)
    if "jarvis" not in normalized:
        return False
    return any(variant in normalized for variant in _KILL_VARIANTS)


class KillSwitch:
    def __init__(
        self,
        on_shutdown: Optional[Callable[[], None]] = None,
        terminate_process_group: bool = True,
    ):
        # Optional cleanup hook run best-effort before termination (flush logs, etc.).
        self._on_shutdown = on_shutdown
        # In production this is True so the whole process group (child agents/workers)
        # is terminated. Tests set it False so the test runner isn't killed too.
        self._terminate_process_group = terminate_process_group
        self._armed = True

    def check(self, text: str) -> bool:
        """Feed transcribed text; triggers shutdown and returns True if it was the kill phrase."""
        if self._armed and is_kill_phrase(text):
            self.trigger()
            return True
        return False

    def trigger(self, exit_code: int = 0) -> None:
        """Perform the actual shutdown of the whole process group."""
        try:
            if self._on_shutdown:
                self._on_shutdown()
        except Exception:
            pass  # never let cleanup block the kill

        # Terminate the whole process group so child workers/agents die too.
        if self._terminate_process_group:
            try:
                os.killpg(os.getpgrp(), signal.SIGTERM)
            except (AttributeError, ProcessLookupError, PermissionError, OSError):
                # os.killpg may be unavailable (e.g. Windows) or restricted; fall back.
                pass
        sys.exit(exit_code)

    def run_stdin_listener(self) -> threading.Thread:
        """Phase 0 convenience: listen on stdin for the kill phrase in a background thread.

        Lets you type 'Jarvis, end yourself' to test the shutdown path before voice exists.
        """
        def _loop() -> None:
            try:
                for line in sys.stdin:
                    if self.check(line.strip()):
                        break
            except Exception:
                pass

        t = threading.Thread(target=_loop, name="kill-switch-stdin", daemon=True)
        t.start()
        return t
