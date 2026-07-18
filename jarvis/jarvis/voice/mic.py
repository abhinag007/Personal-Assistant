"""Microphone capture (§3) — a simple 16 kHz mono int16 frame source.

Wraps sounddevice in a queue-backed stream that yields fixed-size frames (80 ms) to the
live loop. sounddevice/numpy are imported lazily so the rest of the package imports without
audio deps.
"""
from __future__ import annotations

import queue
from typing import Iterator

from .backends import FRAME_SAMPLES, SAMPLE_RATE


class MicStream:
    def __init__(self, sample_rate: int = SAMPLE_RATE, frame_samples: int = FRAME_SAMPLES):
        self.sample_rate = sample_rate
        self.frame_samples = frame_samples
        self._q: "queue.Queue[bytes]" = queue.Queue()
        self._stream = None

    def __enter__(self) -> "MicStream":
        import sounddevice as sd  # lazy

        def _callback(indata, frames, time_info, status):
            # indata is int16 bytes (RawInputStream). Push a copy to the queue.
            self._q.put(bytes(indata))

        self._stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self.frame_samples,
            dtype="int16",
            channels=1,
            callback=_callback,
        )
        self._stream.start()
        return self

    def __exit__(self, *exc) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def frames(self) -> Iterator[bytes]:
        """Yield raw int16 PCM frames (80 ms each) as they arrive from the mic."""
        while True:
            yield self._q.get()

    def read(self) -> bytes:
        """Block for and return the next 80 ms frame."""
        return self._q.get()

    def drain(self) -> int:
        """Discard any buffered frames (e.g. captured while Jarvis was speaking/thinking).

        Prevents processing stale audio or hearing its own TTS. Returns frames dropped.
        """
        import queue as _q

        dropped = 0
        try:
            while True:
                self._q.get_nowait()
                dropped += 1
        except _q.Empty:
            pass
        return dropped
