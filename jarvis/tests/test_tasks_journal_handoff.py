"""Tests for task queue (§9), journal/staging (§26), handoff (§21,§30)."""
from jarvis.connectors import CalendarStore, GmailPlaywrightConnector, StubEmailConnector, build_briefing
from jarvis.connectors.email import Draft, Message
from jarvis.handoff import HandoffManager, Presence, StubNotifier, TelegramInbox
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


def test_staging_update_and_discard_kind(tmp_path):
    s = StagingStore(tmp_path / "staging")
    a = s.add("note", "old", {"body": "old body"})
    s.add("roadmap", "keep", {})

    assert s.update(a, title="new", payload={"body": "new body"}) is True
    assert s.get(a).title == "new"
    assert s.get(a).payload["body"] == "new body"
    assert s.discard_kind("note") == 1
    assert [item.kind for item in s.list()] == ["roadmap"]


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


def test_telegram_inbox_only_accepts_allowlisted_chat_and_saves_offset(tmp_path):
    seen_urls = []

    def fetcher(url):
        seen_urls.append(url)
        return {
            "ok": True,
            "result": [
                {"update_id": 10, "message": {"chat": {"id": "bad"}, "text": "/tasks"}},
                {"update_id": 11, "message": {"chat": {"id": "123"}, "text": " brief "}},
                {"update_id": 12, "message": {"chat": {"id": "123"}, "text": ""}},
            ],
        }

    inbox = TelegramInbox("token", "123", offset_path=tmp_path / "offset.json", fetcher=fetcher)
    assert inbox.poll() == ["brief"]
    assert '"offset": 13' in (tmp_path / "offset.json").read_text()

    inbox.poll()
    assert "offset=13" in seen_urls[-1]


def test_voice_telegram_poller_sends_startup_help(tmp_path, monkeypatch):
    import jarvis.main as main
    import jarvis.handoff as handoff

    sent = []

    class FakeInbox:
        def __init__(self, *_args, **_kwargs):
            pass

        def poll(self):
            return []

    class FakeNotifier:
        def __init__(self, *_args, **_kwargs):
            pass

        def send(self, text):
            sent.append(text)

    monkeypatch.setattr(main, "_telegram_credentials", lambda _config_dir: ("token", "123"))
    monkeypatch.setattr(handoff, "TelegramInbox", FakeInbox)
    monkeypatch.setattr(handoff, "TelegramNotifier", FakeNotifier)

    main._start_telegram_poller(tmp_path, runtime=object(), interval=999)

    assert sent == [main._telegram_help_text()]


def test_telegram_note_management_commands(tmp_path):
    import jarvis.main as main

    class Runtime:
        calendar = CalendarStore(tmp_path / "cal.db")
        handoff = HandoffManager(tmp_path / "h.json", notifier=StubNotifier(), log=lambda *_: None)
        staging = StagingStore(tmp_path / "st")
        task_queue = TaskQueue(tmp_path / "tasks.db")

    rt = Runtime()
    note_id = rt.staging.add("note", "Focus", {"body": "old"})
    assert note_id in main._telegram_response(rt, "/notes", remote=True)
    assert main._telegram_response(rt, f"/update-note {note_id} new focus body", remote=True) == f"Updated staged item {note_id}."
    assert rt.staging.get(note_id).payload["body"] == "new focus body"
    assert main._telegram_response(rt, "Delete all notes", remote=True) == "Deleted 1 staged note(s)."
    assert rt.staging.list() == []


def test_telegram_task_management_commands(tmp_path):
    import jarvis.main as main

    class Runtime:
        calendar = CalendarStore(tmp_path / "cal.db")
        handoff = HandoffManager(tmp_path / "h.json", notifier=StubNotifier(), log=lambda *_: None)
        staging = StagingStore(tmp_path / "st")
        task_queue = TaskQueue(tmp_path / "tasks.db")

    rt = Runtime()
    job_id = rt.task_queue.enqueue("research", {"topic": "focus"})
    assert job_id in main._telegram_response(rt, "/jobs", remote=True)
    assert main._telegram_response(rt, f"/cancel-task {job_id}", remote=True) == f"Cancelled task {job_id}."
    assert rt.task_queue.get(job_id).result == "cancelled by user"
    assert main._telegram_response(rt, f"/delete-task {job_id}", remote=True) == f"Deleted task {job_id}."
    assert rt.task_queue.get(job_id) is None


def test_telegram_brief_accepts_common_typo(tmp_path):
    import jarvis.main as main

    class Runtime:
        calendar = CalendarStore(tmp_path / "cal.db")
        handoff = HandoffManager(tmp_path / "h.json", notifier=StubNotifier(), log=lambda *_: None)
        staging = StagingStore(tmp_path / "st")
        task_queue = TaskQueue(tmp_path / "tasks.db")

    assert main._telegram_response(Runtime(), "/breif", remote=True)


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


def test_gmail_connector_prefers_installed_chrome(tmp_path):
    conn = GmailPlaywrightConnector(tmp_path / "gmail-profile")
    assert conn.channel == "chrome"


def test_gmail_connector_uses_service_login_url():
    url = GmailPlaywrightConnector._mail_url()
    assert "accounts.google.com/ServiceLogin" in url
    assert "service=mail" in url


def test_gmail_connector_reports_google_automation_block():
    class Page:
        def inner_text(self, selector, timeout=5000):
            return "Couldn’t sign you in This browser or app may not be secure."

    try:
        GmailPlaywrightConnector._ensure_logged_in(Page())
    except RuntimeError as e:
        assert "Google blocked" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_gmail_draft_verification_is_advisory_if_subject_missing(tmp_path):
    class Page:
        def goto(self, *args, **kwargs):
            pass
        def wait_for_timeout(self, *args, **kwargs):
            pass
        def inner_text(self, selector, timeout=10000):
            return "Drafts inbox text without expected subject"

    conn = GmailPlaywrightConnector(tmp_path / "gmail-profile")
    assert conn._verify_draft_exists(Page(), Draft("a@example.com", "Expected Subject", "Body")) is False
