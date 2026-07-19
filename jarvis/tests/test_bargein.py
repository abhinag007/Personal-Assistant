"""Barge-in tests (§18) — detector logic + interruptible sentence speaker."""
from jarvis.voice.bargein import BargeInDetector
from jarvis.voice.pipeline import _SentenceSpeaker
from jarvis.voice.stubs import StubTTS


def test_detector_fires_after_sustained_speech():
    d = BargeInDetector(min_speech_frames=4)
    assert d.feed(True) is False   # 1
    assert d.feed(True) is False   # 2
    assert d.feed(True) is False   # 3
    assert d.feed(True) is True    # 4 → barge-in


def test_detector_resets_on_silence():
    d = BargeInDetector(min_speech_frames=3)
    d.feed(True); d.feed(True)
    assert d.feed(False) is False  # silence resets the run
    assert d.feed(True) is False   # counting starts over
    assert d.feed(True) is False
    assert d.feed(True) is True


def test_sentence_speaker_stops_on_barge():
    tts = StubTTS()
    stopped = {"v": False}
    sink = _SentenceSpeaker(tts, stop_check=lambda: stopped["v"])
    sink.feed("First sentence. ")
    assert tts.spoken == ["First sentence."]   # spoke the first one
    stopped["v"] = True                          # user barges in
    sink.feed("Second sentence. Third. ")
    sink.flush()
    assert tts.spoken == ["First sentence."]     # nothing more spoken after barge


def test_sentence_speaker_speaks_all_without_barge():
    tts = StubTTS()
    sink = _SentenceSpeaker(tts)   # no stop_check
    sink.feed("One. Two. ")
    sink.flush()
    assert tts.spoken == ["One.", "Two."]


# ---- speaker-verified barge-in (the speaker/echo fix) --------------------

import array
import threading

from jarvis.voice.bargein import BargeInMonitor


class _FakeMic:
    """Feeds a fixed sequence of frames, then blocks-ish (returns silence)."""
    def __init__(self, frames):
        self._frames = list(frames)

    def read(self):
        if self._frames:
            return self._frames.pop(0)
        return _silence()


def _loud():
    return array.array("h", [12000] * 1280).tobytes()


def _silence():
    return array.array("h", [2] * 1280).tobytes()


def test_barge_ignores_jarvis_echo_but_fires_for_owner():
    # Verify says NOT owner (simulating Jarvis's own voice / echo) → must NOT barge.
    ev = threading.Event()
    mon = BargeInMonitor(_FakeMic([_loud()] * 30), threshold=1000, event=ev,
                         min_speech_frames=4, verify=lambda pcm: False)
    mon.start(); mon._thread.join(timeout=1.0); mon.stop()
    assert not ev.is_set()          # echo did not interrupt

    # Verify says owner → barge fires.
    ev2 = threading.Event()
    mon2 = BargeInMonitor(_FakeMic([_loud()] * 30), threshold=1000, event=ev2,
                          min_speech_frames=4, verify=lambda pcm: True)
    mon2.start(); mon2._thread.join(timeout=1.0); mon2.stop()
    assert ev2.is_set()             # your real voice interrupted


def test_barge_without_verify_fires_on_threshold():
    ev = threading.Event()
    mon = BargeInMonitor(_FakeMic([_loud()] * 20), threshold=1000, event=ev,
                         min_speech_frames=4, verify=None)
    mon.start(); mon._thread.join(timeout=1.0); mon.stop()
    assert ev.is_set()
