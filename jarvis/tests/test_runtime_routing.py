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
