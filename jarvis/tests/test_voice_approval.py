from jarvis.brain import BrainLoop
from jarvis.core.approval import ActionRequest
from jarvis.core.policy import ActionRisk, ActionType
from jarvis.llm import MockAdapter
from jarvis.memory import MemoryStore
from jarvis.memory.embedder import HashEmbedder
from jarvis.voice.live import LiveVoiceLoop
from jarvis.voice.stubs import StubSTT, StubSpeakerVerifier, StubTTS, StubWakeWord


class _Runtime:
    def __init__(self):
        from jarvis.core.approval import ApprovalEngine

        self.approval = ApprovalEngine()


def _loop(tmp_path, answer):
    mem = MemoryStore(tmp_path / "m.db", embedder=HashEmbedder())
    brain = BrainLoop(MockAdapter(), mem, curious=False)
    runtime = _Runtime()
    loop = LiveVoiceLoop(
        brain, StubWakeWord(), StubSTT(), StubTTS(), StubSpeakerVerifier(),
        runtime=runtime,
    )
    loop._listen_for_approval_answer = lambda timeout=12.0: answer
    return loop, runtime


def test_voice_approver_accepts_clear_yes(tmp_path):
    loop, _ = _loop(tmp_path, "yes approve it")
    req = ActionRequest(ActionType.RUN_COMMAND, "Run echo hi")
    assert loop._approve_by_voice(req, ActionRisk.IRREVERSIBLE) is True


def test_voice_approver_denies_unclear_or_no(tmp_path):
    loop, _ = _loop(tmp_path, "no cancel")
    req = ActionRequest(ActionType.RUN_COMMAND, "Run rm something")
    assert loop._approve_by_voice(req, ActionRisk.IRREVERSIBLE) is False
