"""Text-mode stubs for the voice interfaces.

These let the full pipeline run and be tested with NO audio hardware or heavy models:
  * wake word  → always "triggered"
  * speaker    → always the owner
  * STT        → returns queued text (typed input stands in for speech)
  * TTS        → prints instead of playing audio

The real backends (backends.py) are drop-in replacements used on the Mac.
"""
from __future__ import annotations

from typing import Callable, Iterator, Optional

from .base import STT, TTS, SpeakerVerifier, WakeWordDetector


class StubWakeWord(WakeWordDetector):
    def __init__(self, trigger: Callable[[], bool] | None = None):
        self._trigger = trigger or (lambda: True)

    def wait_for_wake(self) -> bool:
        return self._trigger()


class StubSpeakerVerifier(SpeakerVerifier):
    def __init__(self, owner: bool = True):
        self._owner = owner
        self.enrolled = False

    def enroll(self, samples: list) -> None:
        self.enrolled = True

    def is_owner(self, audio) -> bool:
        return self._owner


class StubSTT(STT):
    """Returns text handed to it (typed input standing in for speech)."""

    def __init__(self, provider: Optional[Callable[[], str]] = None):
        self._provider = provider

    def transcribe(self, audio) -> str:
        if isinstance(audio, str):
            return audio
        if self._provider:
            return self._provider()
        return ""


class StubTTS(TTS):
    """Prints the spoken text (captured in tests)."""

    def __init__(self, sink: Optional[Callable[[str], None]] = None):
        self.spoken: list[str] = []
        self._sink = sink

    def speak(self, text: str) -> None:
        self.spoken.append(text)
        if self._sink:
            self._sink(text)
        else:
            print(f"[Jarvis speaks] {text}")
