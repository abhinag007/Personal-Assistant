"""Voice activity detection + utterance segmentation (§3, §19).

Splits a continuous mic stream into discrete utterances so the live loop can transcribe
one spoken phrase at a time. Uses a simple, dependency-light energy VAD:

  * `frame_rms` / `frame_is_speech` — is this 80 ms frame speech or silence (by loudness)?
  * `UtteranceSegmenter` — a small state machine that starts collecting on speech and emits
    the collected frames once it hears enough trailing silence (you've stopped talking).

The state-machine logic is pure and unit-tested with boolean sequences; the loudness math is
separated so tests don't need audio or numpy. Thresholds are calibrated to ambient noise at
startup by the live loop.
"""
from __future__ import annotations

import array
import difflib
from typing import Optional


# ---- fuzzy wake-word matching (§3) --------------------------------------
# STT mishears "Jarvis" as "Jervis", "Jaarvis", "Jarvish", "Javis"... Match by similarity
# instead of exact text, so those all count as the wake word.

def _clean(word: str) -> str:
    return "".join(c for c in word.lower() if c.isalnum())


def word_is_wake(word: str, wake_words, threshold: float = 0.72) -> bool:
    w = _clean(word)
    if not w:
        return False
    return any(difflib.SequenceMatcher(None, w, wake).ratio() >= threshold for wake in wake_words)


def split_on_wake(text: str, wake_words, threshold: float = 0.72) -> tuple[bool, str]:
    """If `text` contains the wake word (fuzzily), return (True, everything after it).

    e.g. "Hey Jervis what's the time" -> (True, "what's the time").
    """
    tokens = text.split()
    for i, tok in enumerate(tokens):
        if word_is_wake(tok, wake_words, threshold):
            return True, " ".join(tokens[i + 1:]).strip(" ,.!?-")
    return False, ""


def frame_rms(frame_bytes: bytes) -> float:
    """Root-mean-square loudness of a 16-bit PCM mono frame. No numpy needed."""
    if not frame_bytes:
        return 0.0
    samples = array.array("h")
    samples.frombytes(frame_bytes)
    if not samples:
        return 0.0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


def frame_is_speech(frame_bytes: bytes, threshold: float) -> bool:
    return frame_rms(frame_bytes) >= threshold


class UtteranceSegmenter:
    """Collects frames from first speech until a trailing pause, then emits the utterance.

    - `min_speech_frames`: ignore blips shorter than this (avoids clicks/coughs).
    - `end_silence_frames`: how many silent frames end an utterance (the pause after you speak).
      At 80 ms/frame, ~10 frames ≈ 0.8 s of silence.
    - `max_frames`: hard cap so a stuck stream can't grow unbounded.
    """

    def __init__(self, *, min_speech_frames: int = 3, end_silence_frames: int = 10,
                 max_frames: int = 750):
        self.min_speech_frames = min_speech_frames
        self.end_silence_frames = end_silence_frames
        self.max_frames = max_frames
        self.reset()

    def reset(self) -> None:
        self._frames: list = []
        self._speech_count = 0
        self._silence_run = 0
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def feed(self, is_speech: bool, frame) -> Optional[list]:
        """Feed one frame. Returns the collected frames when an utterance completes, else None."""
        if not self._active:
            if is_speech:
                # Start of an utterance.
                self._active = True
                self._frames = [frame]
                self._speech_count = 1
                self._silence_run = 0
            return None

        # Active: keep collecting.
        self._frames.append(frame)
        if is_speech:
            self._speech_count += 1
            self._silence_run = 0
        else:
            self._silence_run += 1

        ended = self._silence_run >= self.end_silence_frames
        too_long = len(self._frames) >= self.max_frames
        if ended or too_long:
            frames = self._frames
            enough_speech = self._speech_count >= self.min_speech_frames
            self.reset()
            return frames if enough_speech else None
        return None
