"""Dialog window tests (§19) — multi-turn context, trimming, timeout."""
from jarvis.brain.dialog import DialogWindow


def test_keeps_turns():
    d = DialogWindow(max_turns=4)
    d.add_user("hi")
    d.add_assistant("hello")
    d.add_user("how are you")
    hist = d.history()
    assert [m.role for m in hist] == ["user", "assistant", "user"]


def test_trims_to_max_turns():
    d = DialogWindow(max_turns=2)
    for i in range(5):
        d.add_user(f"u{i}")
        d.add_assistant(f"a{i}")
    # max_turns*2 messages retained
    assert len(d.history()) == 4


def test_timeout_clears_context():
    d = DialogWindow(timeout_seconds=10)
    d.add_user("first", now=1000.0)
    # A new turn far in the future should have expired the stale context first.
    d.add_user("much later", now=2000.0)
    hist = d.history()
    assert len(hist) == 1
    assert hist[0].content == "much later"


def test_clear():
    d = DialogWindow()
    d.add_user("x")
    d.clear()
    assert d.history() == []
