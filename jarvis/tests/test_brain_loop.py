"""BrainLoop tests (§13, §18, §35) — end-to-end turn with mock brain + memory."""
from jarvis.audit import AuditLog
from jarvis.brain import BrainLoop
from jarvis.core.approval import ActionRequest, ApprovalEngine
from jarvis.core.kill_switch import KillSwitch
from jarvis.core.policy import ActionType
from jarvis.llm import MockAdapter
from jarvis.memory import MemoryStore
from jarvis.memory.embedder import HashEmbedder
from jarvis.tracing.tracer import LocalTracer


def _brain(tmp_path, **kw):
    mem = MemoryStore(tmp_path / "mem.db", embedder=HashEmbedder())
    audit = AuditLog(tmp_path / "audit.jsonl")
    tracer = LocalTracer(tmp_path / "traces.jsonl")
    # No fallback name — Jarvis learns it from conversation (§8).
    return BrainLoop(MockAdapter(), mem, audit=audit, tracer=tracer, **kw), mem, tracer


def test_turn_produces_reply_and_measures_ttfw(tmp_path):
    brain, mem, _ = _brain(tmp_path)
    spoken = []
    reply = brain.handle_turn("hello jarvis", speak=spoken.append)
    assert reply
    assert spoken  # something was streamed out
    assert brain.last_ttfw is not None and brain.last_ttfw >= 0


def test_curious_appends_question_for_new_user(tmp_path):
    brain, mem, _ = _brain(tmp_path)  # curious=True by default
    reply = brain.handle_turn("hi", speak=lambda c: None)
    # A brand-new Jarvis knows nothing → it should ask what to call you.
    assert "call you" in reply.lower()
    # And it marks that it asked, so it won't nag next turn.
    assert mem.get_profile("_asked:name") == "1"


def test_curiosity_can_be_disabled(tmp_path):
    brain, mem, _ = _brain(tmp_path, curious=False)
    reply = brain.handle_turn("hi", speak=lambda c: None)
    assert "call you" not in reply.lower()


def test_turn_writes_episodic_memory(tmp_path):
    brain, mem, _ = _brain(tmp_path)
    brain.handle_turn("remember I like tea", speak=lambda c: None)
    assert mem.count() == 1
    assert "tea" in mem.all_records()[0].text


def test_turn_emits_traces(tmp_path):
    brain, mem, tracer = _brain(tmp_path)
    brain.handle_turn("trace this", speak=lambda c: None)
    names = {span["name"] for span in tracer.read_all()}
    assert {"handle_turn", "memory.recall", "model.stream"} <= names


def test_recall_feeds_context_across_turns(tmp_path):
    brain, mem, _ = _brain(tmp_path)
    brain.handle_turn("my dog is named Pixel", speak=lambda c: None)
    # Second turn should recall the first (mock echoes, but memory must have grown).
    brain.handle_turn("what is my dog called", speak=lambda c: None)
    assert mem.count() == 2


def test_confirm_action_denied_blocks(tmp_path):
    brain, mem, _ = _brain(tmp_path, approval=ApprovalEngine(approver=lambda r, k: False))
    ok = brain.confirm_action(ActionRequest(ActionType.SPEND_MONEY, "buy a thing"))
    assert ok is False


def test_confirm_action_approved(tmp_path):
    brain, mem, _ = _brain(tmp_path, approval=ApprovalEngine(approver=lambda r, k: True))
    ok = brain.confirm_action(ActionRequest(ActionType.SEND_MESSAGE, "send a note"))
    assert ok is True


def test_kill_phrase_short_circuits_turn(tmp_path):
    brain, mem, _ = _brain(tmp_path, kill_switch=KillSwitch(terminate_process_group=False))
    import pytest
    with pytest.raises(SystemExit):
        brain.handle_turn("Jarvis, end yourself", speak=lambda c: None)


def test_learns_name_from_conversation(tmp_path):
    """Jarvis should learn the user's name from what they say — not have it hardcoded."""
    brain, mem, _ = _brain(tmp_path)
    # Fresh brain knows no name.
    assert brain.user_name is None
    brain.handle_turn("hey, my name is Abhi", speak=lambda c: None)
    # Now it knows — stored in the profile (persists across sessions).
    assert brain.user_name == "Abhi"
    assert mem.get_profile("name") == "Abhi"
    # And it wrote a semantic memory of the fact.
    assert any("name is Abhi" in r.text for r in mem.all_records())


def test_distinguishes_name_from_preferred_address(tmp_path):
    brain, mem, _ = _brain(tmp_path)
    brain.handle_turn("my name is not sir it's Abhijeet Nag", speak=lambda c: None)
    brain.handle_turn("refer to me as sir", speak=lambda c: None)

    assert brain.user_name == "Abhijeet Nag"
    assert brain.preferred_address == "Sir"
    assert mem.get_profile("name") == "Abhijeet Nag"
    assert mem.get_profile("preferred_address") == "Sir"


def test_what_is_my_name_uses_profile_not_model(tmp_path):
    brain, mem, _ = _brain(tmp_path)
    brain.handle_turn("my name is Abhijeet Nag", speak=lambda c: None)
    brain.handle_turn("refer to me as sir", speak=lambda c: None)

    spoken = []
    reply = brain.handle_turn("what is my name", speak=spoken.append)

    assert reply == "Your name is Abhijeet Nag. You asked me to address you as Sir."
    assert "".join(spoken) == reply


def test_learned_name_persists_across_restart(tmp_path):
    """The learned name is durable — a new BrainLoop on the same DB still knows it."""
    brain, mem, _ = _brain(tmp_path)
    brain.handle_turn("call me Neo", speak=lambda c: None)
    mem.close()
    # Simulate a restart: new store + brain on the same DB file.
    mem2 = MemoryStore(tmp_path / "mem.db", embedder=HashEmbedder())
    brain2 = BrainLoop(MockAdapter(), mem2)
    assert brain2.user_name == "Neo"
