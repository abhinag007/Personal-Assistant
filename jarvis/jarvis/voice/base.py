"""Voice interfaces (§3, §4, §5).

Four small abstractions the pipeline depends on. Concrete backends (real audio or stubs)
implement them. Keeping these tiny is what lets the text-mode stubs and the Mac audio
backends be swapped freely.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, Optional


class WakeWordDetector(ABC):
    """§3 — detects the 'Hey Jarvis' trigger phrase in an audio stream."""

    @abstractmethod
    def wait_for_wake(self) -> bool:
        """Block until the wake word is heard. Returns True when triggered."""


class SpeakerVerifier(ABC):
    """§3 — confirms an utterance is the enrolled owner's voice."""

    @abstractmethod
    def enroll(self, samples: list) -> None:
        """Learn the owner's voiceprint from sample audio."""

    @abstractmethod
    def is_owner(self, audio) -> bool:
        """Return True if the audio matches the enrolled owner."""


class STT(ABC):
    """§4 — speech to text."""

    @abstractmethod
    def transcribe(self, audio) -> str:
        """Transcribe a complete utterance."""

    def stream_transcribe(self, audio) -> Iterator[str]:
        """Optional streaming partials; default falls back to one final result."""
        yield self.transcribe(audio)


class TTS(ABC):
    """§5 — text to speech."""

    @abstractmethod
    def speak(self, text: str) -> None:
        """Synthesize and play the text."""

    def speak_stream(self, chunks: Iterator[str]) -> None:
        """Speak streamed text chunks, sentence by sentence (low latency, §18).

        Default: buffer into sentences and speak each as it completes.
        """
        buffer = ""
        for chunk in chunks:
            buffer += chunk
            while True:
                idx = _first_sentence_end(buffer)
                if idx is None:
                    break
                sentence, buffer = buffer[: idx + 1], buffer[idx + 1 :]
                if sentence.strip():
                    self.speak(sentence.strip())
        if buffer.strip():
            self.speak(buffer.strip())


def _first_sentence_end(text: str) -> Optional[int]:
    for i, ch in enumerate(text):
        if ch in ".!?\n":
            return i
    return None
