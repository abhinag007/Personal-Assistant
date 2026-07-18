"""Tests for task queue (§9), journal/staging (§26), handoff (§21,§30)."""
from jarvis.connectors import CalendarStore, StubEmailConnector, build_briefing
from jarvis.connectors.email import Draft, Message
from jarvis.handoff import HandoffManager, Presence, StubNotifier
from jarvis.journal import DecisionJournal, StagingStore
from jarvis.tasks import JobStatus, TaskQueue, Worker


# ---- task queue ----------------------------------------------------------

def test_queue_enqueue_and_process(tmp_path):
    q = TaskQueue(tmp_path / "q.db")
    q.enqueue("greet", {"name": "Abhi"})
    w = Worker(q)
    w.register("greet", lambda job: (JobStatus.DONE, f"hi {job.payload['name']}"))
    assert w.drain() == 1
    jobs = q.list(JobStatus.DONE)
    assert jobs and jobs[0].result == "hi Abhi"


def test_queue_survives_restart(tmp_path):
    q = TaskQueue(tmp_path / "q.db")
    q.enqueue("x", {})
    q.close()
    q2 = TaskQueue(tmp_path / "q.db")  # reopen
    assert len(q2.list(JobStatus.QUEUED)) == 1


def test_requeue_running_resets_interrupted(tmp_path):
    q = TaskQueue(tmp_path / "q.db")
    jid = q.enqueue("x", {})
    q.update(jid, JobStatus.RUNNING)
    assert q.requeue_running() == 1
    assert q.get(jid).status == JobStatus.QUEUED.value


def test_blocked_job_skipped_others_run(tmp_path):
    q = TaskQueue(tmp_path / "q.db")
    q.enqueue("block", {})
    q.enqueue("ok", {})
    w = Worker(q)
    w.register("block", lambda job: (JobStatus.BLOCKED, "needs human"))
    w.register("ok", lambda job: (JobStatus.DONE, "done"))
    w.drain()
    assert len(q.list(JobStatus.DONE)) == 1
    assert len(q.list(JobStatus.BLOCKED)) == 1


# ---- journal + staging ---------------------------------------------------

def test_journal_records_reasoning(tmp_path):
    j = DecisionJournal(tmp_path / "j.jsonl")
    j.record(action="send_email", summary="email Bob", reasoning="he asked",
             alternatives=["wait"], confidence=0.8, outcome="ok")
    e = j.read_all()[0]
    assert e["reasoning"] == "he asked" and e["confidence"] == 0.8


def test_staging_promote_and_discard(tmp_path):
    s = StagingStore(tmp_path / "staging")
    a = s.add("reminder", "call mom", {"when": "5pm"})
    b = s.add("roadmap", "5yr plan", {})
    assert len(s.list()) == 2
    promoted = {}
    s.promote(a, lambda item: promoted.update({"t": item.title}))
    assert promoted["t"] == "call mom"
    assert s.discard(b) is True
    assert s.list() == []


# ---- handoff -------------------------------------------------------------

def test_handoff_notifies_phone_when_away(tmp_path):
    notifier = StubNotifier()
    away = Presence(idle_fn=lambda: 9999)  # very idle → away
    h = HandoffManager(tmp_path / "h.json", notifier=notifier, presence=away, log=lambda *_: None)
    h.block("solve the captcha")
    assert notifier.sent and "captcha" in notifier.sent[0]


def test_handoff_local_when_present(tmp_path):
    notifier = StubNotifier()
    present = Presence(idle_fn=lambda: 0)  # active → present
    h = HandoffManager(tmp_path / "h.json", notifier=notifier, presence=present, log=lambda *_: None)
    task = h.block("confirm this")
    assert notifier.sent == []            # not phoned; you're here
    assert len(h.waiting()) == 1
    assert h.resolve(task.id) is True
    assert h.waiting() == []


# ---- calendar + briefing -------------------------------------------------

def test_calendar_add_and_upcoming(tmp_path):
    cal = CalendarStore(tmp_path / "cal.db")
    cal.add("call mom", due=1000.0)
    cal.add("dentist", due=5000.0)
    assert len(cal.upcoming(now=0)) == 2
    assert cal.due_now(now=2000.0)[0].text == "call mom"


def test_briefing_assembles(tmp_path):
    cal = CalendarStore(tmp_path / "cal.db")
    cal.add("standup", due=100.0)
    staging = StagingStore(tmp_path / "st")
    staging.add("roadmap", "career plan", {})
    text = build_briefing(calendar=cal, staging=staging, now=0)
    assert "standup" in text and "career plan" in text


def test_briefing_empty():
    assert "all clear" in build_briefing().lower()


# ---- email (gated) -------------------------------------------------------

def test_email_stub_read_and_capture_send():
    conn = StubEmailConnector(seed=[Message("1", "bob@x.com", "hi", "hello there")])
    assert conn.inbox()[0].sender == "bob@x.com"
    conn.send(Draft("bob@x.com", "re: hi", "hi Bob"))
    assert conn.outbox[0].to == "bob@x.com"   # captured, not actually emailed
