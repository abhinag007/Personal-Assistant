"""Voice pipeline tests (§3-5) — full flow with stubs, speaker gating, sentence TTS."""
from jarvis.brain import BrainLoop
from jarvis.llm import MockAdapter
from jarvis.memory import MemoryStore
from jarvis.memory.embedder import HashEmbedder
from jarvis.voice import VoicePipeline
from jarvis.voice.stubs import StubSTT, StubSpeakerVerifier, StubTTS, StubWakeWord


def _brain(tmp_path):
    mem = MemoryStore(tmp_path / "mem.db", embedder=HashEmbedder())
    return BrainLoop(MockAdapter(), mem, user_name="Abhi")


def test_full_voice_turn_speaks(tmp_path):
    tts = StubTTS()
    pipe = VoicePipeline(
        wake=StubWakeWord(), speaker=StubSpeakerVerifier(owner=True),
        stt=StubSTT(), tts=tts, brain=_brain(tmp_path),
        capture=lambda: "hello there jarvis",
    )
    reply = pipe.run_once()
    assert reply
    assert tts.spoken  # something was spoken


def test_non_owner_is_ignored(tmp_path):
    tts = StubTTS()
    pipe = VoicePipeline(
        wake=StubWakeWord(), speaker=StubSpeakerVerifier(owner=False),
        stt=StubSTT(), tts=tts, brain=_brain(tmp_path),
        capture=lambda: "this should be ignored",
    )
    assert pipe.run_once() is None
    assert tts.spoken == []  # nothing spoken for a stranger


def test_no_wake_no_turn(tmp_path):
    tts = StubTTS()
    pipe = VoicePipeline(
        wake=StubWakeWord(trigger=lambda: False), speaker=StubSpeakerVerifier(),
        stt=StubSTT(), tts=tts, brain=_brain(tmp_path),
        capture=lambda: "unheard",
    )
    assert pipe.run_once() is None


def test_sentence_streaming_splits_into_sentences(tmp_path):
    """TTS should receive complete sentences from the streamed reply (§18)."""
    from jarvis.voice.pipeline import _SentenceSpeaker
    tts = StubTTS()
    s = _SentenceSpeaker(tts)
    for chunk in ["Hello", " there", ". How", " are you", "? Bye", "."]:
        s.feed(chunk)
    s.flush()
    assert tts.spoken == ["Hello there.", "How are you?", "Bye."]
