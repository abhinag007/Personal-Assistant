"""Runtime.handle routing tests (§2A) — M1 via brain, M2/M3 via agents, memory writes."""
import tempfile
from pathlib import Path
import shutil

import pytest

from jarvis.brain import BrainLoop
from jarvis.llm import MockAdapter
from jarvis.llm.adapter import ChatResponse, ModelAdapter
from jarvis.memory import MemoryStore
from jarvis.memory.embedder import HashEmbedder
from jarvis.runtime import Runtime
from jarvis.tools import ToolResult


def _brain(tmp_path):
    mem = MemoryStore(tmp_path / "m.db", embedder=HashEmbedder())
    return BrainLoop(MockAdapter(), mem, curious=False), mem


class ReminderAdapter(ModelAdapter):
    """Scripted: for M2, calls add_reminder then finishes."""
    name = "reminder-adapter"

    def __init__(self):
        self._q = ['{"tool": "add_reminder", "args": {"text": "call mom", "in_minutes": 15}}',
                   '{"final": "Done — reminder set."}']

    def chat(self, messages, tools=None):
        txt = self._q.pop(0) if self._q else '{"final": "ok"}'
        return ChatResponse(text=txt, model=self.name)

    def stream(self, messages):
        yield "hi"

    def embed(self, texts):
        return [[0.0] for _ in texts]


def test_m1_routes_through_brain_and_grows_memory(tmp_path):
    brain, mem = _brain(tmp_path)
    rt = Runtime(MockAdapter(), tmp_path, brain=brain)
    spoken = []
    rt.handle("hello how are you", speak=spoken.append)   # M1 (chat)
    assert mem.count() >= 1     # brain wrote an episodic memory
    assert spoken               # something was emitted


def test_m2_task_runs_agent_and_creates_reminder(tmp_path):
    brain, mem = _brain(tmp_path)
    rt = Runtime(ReminderAdapter(), tmp_path, brain=brain)
    out = rt.handle("remind me to call mom in 15 minutes", speak=lambda c: None)  # M2
    assert "Done" in out
    # the agent actually created the reminder via the tool
    assert any("call mom" in r.text for r in rt.calendar.upcoming())
    # and the task was remembered
    assert any("asked" in r.text for r in mem.all_records())


def test_handle_without_brain_still_answers(tmp_path):
    rt = Runtime(MockAdapter(), tmp_path)          # no brain
    out = rt.handle("hello", speak=lambda c: None)  # M1 falls back to bare chat
    assert out


def test_gmail_inbox_request_uses_direct_tool_not_chat(tmp_path):
    rt = Runtime(MockAdapter(), tmp_path)

    # Override the real Playwright-backed tool with a deterministic fake.
    rt.registry._tools["gmail_inbox"].func = lambda limit=10: ToolResult.success("fake inbox")
    spoken = []
    out = rt.handle("read my latest Gmail inbox items", speak=spoken.append)
    assert out == "fake inbox"
    assert spoken == ["fake inbox"]


def test_gmail_draft_request_uses_direct_tool_with_parsed_args(tmp_path):
    rt = Runtime(MockAdapter(), tmp_path)
    captured = {}

    def fake_draft(**kwargs):
        captured.update(kwargs)
        return ToolResult.success("draft ok")

    rt.registry._tools["gmail_draft"].func = fake_draft
    out = rt.handle(
        "create a draft email for requesting 2 days leave and send to abhinagml@gmail.com",
        speak=lambda c: None,
    )
    assert out == "draft ok"
    assert captured["to"] == "abhinagml@gmail.com"
    assert captured["subject"] == "Request for 2 Days Leave"
    assert "2 days" in captured["body"]


def test_model_identity_uses_the_configured_adapter_name(tmp_path):
    adapter = ReminderAdapter()
    rt = Runtime(adapter, tmp_path)
    out = rt.handle("say which model you are using", speak=lambda c: None)
    assert out == "I am currently using reminder-adapter."


def test_explicit_shell_command_uses_approval_gated_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ALLOW_SHELL", "1")
    rt = Runtime(MockAdapter(), tmp_path, approver=lambda _request, _risk: True)
    captured = {}

    def fake_command(command=""):
        captured["command"] = command
        return ToolResult.success("jarvis-smoke")

    rt.registry._tools["run_command"].func = fake_command
    out = rt.handle("run command echo jarvis-smoke", speak=lambda c: None)
    assert out == "jarvis-smoke"
    assert captured == {"command": "echo jarvis-smoke"}


def test_telegram_request_never_executes_an_irreversible_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ALLOW_SHELL", "1")
    rt = Runtime(MockAdapter(), tmp_path, approver=lambda _request, _risk: True)
    called = []
    rt.registry._tools["run_command"].func = lambda command="": called.append(command) or ToolResult.success("bad")

    out = rt.handle_from_telegram("run command echo should-not-run", speak=lambda c: None)

    assert "need your approval" in out
    assert "echo should-not-run" in out
    assert called == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_write_file_tool_requires_approval(tmp_path):
    sandbox = tmp_path / "sandbox"
    rt = Runtime(MockAdapter(), tmp_path, sandbox_path=str(sandbox), approver=lambda r, k: False)
    res = rt.registry.execute("write_file", path="app.py", content="print('hi')\n")
    assert res.ok is False
    assert not (sandbox / "app.py").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_write_file_tool_writes_inside_sandbox_and_commits(tmp_path):
    sandbox = tmp_path / "sandbox"
    rt = Runtime(MockAdapter(), tmp_path, sandbox_path=str(sandbox), approver=lambda r, k: True)
    res = rt.registry.execute("write_file", path="src/app.py", content="print('hi')\n")
    assert res.ok
    assert (sandbox / "src" / "app.py").read_text() == "print('hi')\n"
    assert any("write_file src/app.py" in c for c in rt.git.last_commits())


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_write_file_tool_blocks_sandbox_escape_after_approval(tmp_path):
    sandbox = tmp_path / "sandbox"
    outside = tmp_path / "outside.py"
    rt = Runtime(MockAdapter(), tmp_path, sandbox_path=str(sandbox), approver=lambda r, k: True)
    res = rt.registry.execute("write_file", path=str(outside), content="bad")
    assert res.ok is False
    assert "outside the sandbox" in res.error
    assert not outside.exists()
