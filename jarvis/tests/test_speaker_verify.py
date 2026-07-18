"""Speaker verification gating tests (§3) — the non-audio logic paths.

The embedding model needs torch/audio (not tested here), but the gating decisions are
pure and important: not-enrolled must not block; the require_owner wiring must hold.
"""
from jarvis.voice.backends import SpeechBrainVerifier


def test_not_enrolled_allows_everyone():
    # Before enrollment, is_owner returns True (so it never silently blocks the user).
    v = SpeechBrainVerifier()
    assert v.get_enrolled_vector() is None
    assert v.is_owner(b"\x00\x00" * 100) is True


def test_set_enrolled_vector_roundtrip():
    v = SpeechBrainVerifier()
    v.set_enrolled_vector([0.1, 0.2, 0.3])
    assert v.get_enrolled_vector() == [0.1, 0.2, 0.3]


def test_require_owner_disabled_when_no_speaker():
    from jarvis.brain import BrainLoop
    from jarvis.llm import MockAdapter
    from jarvis.memory import MemoryStore
    from jarvis.memory.embedder import HashEmbedder
    from jarvis.voice.live import LiveVoiceLoop

    import tempfile
    from pathlib import Path
    mem = MemoryStore(Path(tempfile.mkdtemp()) / "m.db", embedder=HashEmbedder())
    brain = BrainLoop(MockAdapter(), mem)
    loop = LiveVoiceLoop(brain, wake=None, stt=None, tts=None, speaker=None, require_owner=True)
    # With no speaker backend, owner-check must auto-disable (never blocks).
    assert loop.require_owner is False
