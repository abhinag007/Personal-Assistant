"""Utterance segmenter tests (§3) — start on speech, end on trailing silence."""
from jarvis.voice.activity import UtteranceSegmenter, frame_rms, frame_is_speech


def _feed(seg, speech_flags):
    """Feed a sequence of speech/silence flags; return list of emitted utterances (as frame counts)."""
    emitted = []
    for i, flag in enumerate(speech_flags):
        out = seg.feed(flag, f"f{i}")
        if out is not None:
            emitted.append(out)
    return emitted


def test_captures_one_utterance():
    seg = UtteranceSegmenter(min_speech_frames=2, end_silence_frames=3)
    # speech (4) then silence (3) → one utterance
    flags = [True] * 4 + [False] * 3
    out = _feed(seg, flags)
    assert len(out) == 1
    assert len(out[0]) >= 4


def test_ignores_short_blip():
    seg = UtteranceSegmenter(min_speech_frames=4, end_silence_frames=3)
    flags = [True] * 2 + [False] * 3   # too short → discarded
    assert _feed(seg, flags) == []


def test_two_utterances_separated_by_silence():
    seg = UtteranceSegmenter(min_speech_frames=2, end_silence_frames=2)
    flags = [True, True, False, False] + [True, True, True, False, False]
    out = _feed(seg, flags)
    assert len(out) == 2


def test_silence_only_emits_nothing():
    seg = UtteranceSegmenter()
    assert _feed(seg, [False] * 20) == []


def test_max_frames_caps_utterance():
    # A never-ending speech stream is chopped into max_frames-sized pieces (no unbounded growth).
    seg = UtteranceSegmenter(min_speech_frames=1, end_silence_frames=100, max_frames=5)
    out = _feed(seg, [True] * 10)
    assert len(out) == 2
    assert all(len(u) == 5 for u in out)


def test_rms_and_is_speech():
    import array
    loud = array.array("h", [10000] * 100).tobytes()
    quiet = array.array("h", [5] * 100).tobytes()
    assert frame_rms(loud) > frame_rms(quiet)
    assert frame_is_speech(loud, threshold=1000) is True
    assert frame_is_speech(quiet, threshold=1000) is False
    assert frame_rms(b"") == 0.0
