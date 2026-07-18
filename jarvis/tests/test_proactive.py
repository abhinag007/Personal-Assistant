"""Proactive engine tests (§25, §30, §40) — speak if present, phone if away, quiet hours."""
import time

from jarvis.connectors import CalendarStore
from jarvis.handoff import HandoffManager, Presence, StubNotifier
from jarvis.proactive import ProactiveEngine


def _present(now=None):
    return Presence(idle_fn=lambda: 0)      # active


def _away():
    return Presence(idle_fn=lambda: 99999)  # idle → away


def test_due_reminder_spoken_when_present(tmp_path):
    cal = CalendarStore(tmp_path / "c.db")
    cal.add("call mom", due=100.0)
    eng = ProactiveEngine(calendar=cal, presence=_present())
    out = eng.poll(now=200.0)
    assert any("call mom" in a for a in out)
    # marked done → not repeated
    assert eng.poll(now=300.0) == []


def test_routed_to_phone_when_away(tmp_path):
    cal = CalendarStore(tmp_path / "c.db")
    cal.add("standup", due=100.0)
    notifier = StubNotifier()
    eng = ProactiveEngine(calendar=cal, presence=_away(), notifier=notifier)
    spoken = eng.poll(now=200.0)
    assert spoken == []                       # nothing spoken
    assert any("standup" in m for m in notifier.sent)   # sent to phone


def test_quiet_hours_stay_silent(tmp_path):
    cal = CalendarStore(tmp_path / "c.db")
    cal.add("late thing", due=100.0)
    notifier = StubNotifier()
    # Quiet all day so 'now' is always inside it.
    eng = ProactiveEngine(calendar=cal, presence=_present(), notifier=notifier,
                          quiet_hours="00:00-23:59")
    assert eng.poll(now=time.time()) == []
    assert notifier.sent == []


def test_blocked_handoff_announced_once(tmp_path):
    h = HandoffManager(tmp_path / "h.json", presence=_present(), log=lambda *_: None)
    h.block("solve captcha")
    eng = ProactiveEngine(handoff=h, presence=_present())
    out = eng.poll()
    assert any("captcha" in a for a in out)
    assert eng.poll() == []                    # not repeated


def test_nothing_to_say_returns_empty(tmp_path):
    eng = ProactiveEngine(calendar=CalendarStore(tmp_path / "c.db"), presence=_present())
    assert eng.poll(now=0) == []


def test_conversational_phrasing_uses_model(tmp_path):
    """With an adapter, updates are rephrased conversationally (one natural message)."""
    from jarvis.llm.adapter import ChatResponse, ModelAdapter

    class Phraser(ModelAdapter):
        name = "phraser"
        def chat(self, messages, tools=None):
            return ChatResponse(text="Hey Abhi, quick heads-up — time to call your mom!",
                                model=self.name)
        def stream(self, messages):
            yield ""
        def embed(self, texts):
            return [[0.0] for _ in texts]

    cal = CalendarStore(tmp_path / "c.db")
    cal.add("call mom", due=100.0)
    eng = ProactiveEngine(calendar=cal, presence=_present(), adapter=Phraser(), user_name="Abhi")
    out = eng.poll(now=200.0)
    assert out == ["Hey Abhi, quick heads-up — time to call your mom!"]  # one warm message


def test_no_adapter_keeps_raw(tmp_path):
    cal = CalendarStore(tmp_path / "c.db")
    cal.add("call mom", due=100.0)
    eng = ProactiveEngine(calendar=cal, presence=_present())  # no adapter
    assert eng.poll(now=200.0) == ["Reminder: call mom."]


def test_quiet_hours_parsing_spans_midnight():
    eng = ProactiveEngine(quiet_hours="22:00-07:00")
    # 23:30
    t = time.mktime(time.struct_time((2026, 7, 18, 23, 30, 0, 0, 0, -1)))
    assert eng.in_quiet_hours(t) is True
    # 12:00
    t2 = time.mktime(time.struct_time((2026, 7, 18, 12, 0, 0, 0, 0, -1)))
    assert eng.in_quiet_hours(t2) is False
