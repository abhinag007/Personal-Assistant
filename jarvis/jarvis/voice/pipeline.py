"""VoicePipeline (§3→§5, §18) — one voice turn, end to end.

Flow:  wake word → capture → speaker check → STT → BrainLoop.handle_turn → streaming TTS.

It works identically with stub backends (testable now) and real Mac backends. The reply
is streamed token-by-token from the brain into a sentence buffer, so TTS starts speaking
the first sentence while the rest is still being generated (low latency, §18).
"""
from __future__ import annotations

from typing import Callable, Optional

from ..brain.loop import BrainLoop
from .base import STT, TTS, SpeakerVerifier, WakeWordDetector


class _SentenceSpeaker:
    """Buffers streamed tokens and speaks each complete sentence as it arrives."""

    def __init__(self, tts: TTS):
        self._tts = tts
        self._buf = ""

    def feed(self, chunk: str) -> None:
        self._buf += chunk
        while True:
            idx = next((i for i, c in enumerate(self._buf) if c in ".!?\n"), None)
            if idx is None:
                break
            sentence, self._buf = self._buf[: idx + 1], self._buf[idx + 1 :]
            if sentence.strip():
                self._tts.speak(sentence.strip())

    def flush(self) -> None:
        if self._buf.strip():
            self._tts.speak(self._buf.strip())
        self._buf = ""


class VoicePipeline:
    def __init__(
        self,
        wake: WakeWordDetector,
        speaker: SpeakerVerifier,
        stt: STT,
        tts: TTS,
        brain: BrainLoop,
        *,
        capture: Optional[Callable[[], object]] = None,
    ):
        self.wake = wake
        self.speaker = speaker
        self.stt = stt
        self.tts = tts
        self.brain = brain
        # capture() returns audio (real) or text (stub). Defaults to reading a typed line.
        self.capture = capture or (lambda: input("you (speak)> "))

    def run_once(self) -> Optional[str]:
        """Handle one wake→reply cycle. Returns the reply text, or None if ignored."""
        if not self.wake.wait_for_wake():
            return None

        audio = self.capture()

        # §3 — only respond to the owner's voice.
        if not self.speaker.is_owner(audio):
            return None

        # §4 — transcribe.
        text = self.stt.transcribe(audio)
        if not text or not text.strip():
            return None

        # §5/§18 — stream the reply into sentence-buffered TTS.
        speaker_sink = _SentenceSpeaker(self.tts)
        reply = self.brain.handle_turn(text, speak=speaker_sink.feed)
        speaker_sink.flush()
        return reply

    def run_forever(self) -> None:  # pragma: no cover - interactive loop
        while True:
            try:
                self.run_once()
            except (EOFError, KeyboardInterrupt):
                break
