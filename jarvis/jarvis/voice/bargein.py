"""Barge-in (§18) — interrupt Jarvis mid-sentence by speaking.

While Jarvis is talking (TTS playing), a monitor watches the mic. If it hears sustained
speech from you, it stops the playback immediately so you can take over — like a real
conversation where you can cut in.

  * BargeInDetector — pure state machine (N sustained speech frames → interrupt). Testable.
  * BargeInMonitor  — runs in a thread during playback, reads the mic, sets an Event on
    barge-in. It uses a HIGHER threshold than normal speech to avoid tripping on Jarvis's
    own audio echoing back into the mic.
"""
from __future__ import annotations

import threading
from typing import Optional


class BargeInDetector:
    def __init__(self, min_speech_frames: int = 4):
        # ~4 frames ≈ 0.3s of sustained speech before we count it as a real interruption.
        self.min_speech_frames = min_speech_frames
        self._run = 0

    def reset(self) -> None:
        self._run = 0

    def feed(self, is_speech: bool) -> bool:
        """Return True once enough consecutive speech frames indicate a real barge-in."""
        self._run = self._run + 1 if is_speech else 0
        return self._run >= self.min_speech_frames


class BargeInMonitor:
    def __init__(self, mic, threshold: float, event: threading.Event,
                 *, min_speech_frames: int = 5, verify=None, log=None):
        self.mic = mic
        self.threshold = threshold
        self.event = event
        self.detector = BargeInDetector(min_speech_frames)
        # verify(pcm_bytes) -> bool: True only if this is the OWNER's voice. When set, this is
        # what makes barge-in work on SPEAKERS — Jarvis's own TTS echo won't match you, so it
        # can't interrupt itself; only your real voice does.
        self.verify = verify
        self.log = log
        self._stop = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop = False
        self.detector.reset()
        self._thread = threading.Thread(target=self._loop, name="barge-in", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        from .activity import frame_is_speech
        buf: list = []
        while not self._stop:
            try:
                frame = self.mic.read()
            except Exception:
                break
            if frame_is_speech(frame, self.threshold):
                buf.append(frame)
                if self.detector.feed(True):
                    # Candidate barge-in. If we can verify the speaker, only interrupt for YOU.
                    if self.verify is None:
                        self._fire()
                        break
                    pcm = b"".join(buf[-8:])   # ~0.6s of the loudest recent speech
                    try:
                        if self.verify(pcm):
                            self._fire()
                            break
                    except Exception:
                        pass  # verify failed → don't interrupt on possible echo (stay safe)
                    # Not you (Jarvis's echo, or someone else) → keep listening, don't barge.
                    self.detector.reset()
                    buf = buf[-4:]
            else:
                self.detector.feed(False)
                if len(buf) > 30:
                    buf = buf[-8:]

    def _fire(self) -> None:
        self.event.set()
        if self.log:
            self.log("[voice] (you started talking — stopping)")

    def stop(self) -> None:
        self._stop = True
        if self._thread is not None:
            self._thread.join(timeout=0.3)
