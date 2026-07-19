"""Background multitasking tests (§9) — long tasks run off-thread; proactive announces done."""
import tempfile
import time
from pathlib import Path

from jarvis.brain import BrainLoop
from jarvis.llm import MockAdapter
from jarvis.llm.adapter import ChatResponse, ModelAdapter
from jarvis.memory import MemoryStore
from jarvis.memory.embedder import HashEmbedder
from jarvis.proactive import ProactiveEngine
from jarvis.handoff import Presence
from jarvis.runtime import Runtime
from jarvis.tasks import JobStatus


class PlanAdapter(ModelAdapter):
    """Enough script for an M3 run to complete quickly."""
    name = "plan"

    def chat(self, messages, tools=None):
        sys = messages[0].content.lower() if messages else ""
        if "planning supervisor" in sys:
            return ChatResponse(text='["step one"]', model=self.name)
        if "reviewer" in sys:
            return ChatResponse(text="YES fine", model=self.name)
        if "merge" in sys:
            return ChatResponse(text="Final merged result.", model=self.name)
        return ChatResponse(text='{"final": "did the step"}', model=self.name)

    def stream(self, messages):
        yield "x"

    def embed(self, texts):
        return [[0.0] for _ in texts]


def _rt(tmp_path, background):
    mem = MemoryStore(tmp_path / "m.db", embedder=HashEmbedder())
    brain = BrainLoop(MockAdapter(), mem, curious=False)
    return Runtime(PlanAdapter(), tmp_path, brain=brain, background=background)


def test_background_off_runs_inline(tmp_path):
    rt = _rt(tmp_path, background=False)
    out = rt.handle("research phones and compare them", speak=lambda c: None)  # M3
    assert "merged" in out.lower()   # ran inline, returned the real result


def test_background_on_acks_and_runs_in_worker(tmp_path):
    rt = _rt(tmp_path, background=True)
    ack = rt.handle("research phones and compare them", speak=lambda c: None)  # M3
    assert "on it" in ack.lower()                      # immediate ack, not the result
    assert len(rt.task_queue.list(JobStatus.QUEUED)) == 1

    # The background worker processes the queued job.
    job = rt.worker.run_one()
    assert job is not None and job.status == JobStatus.DONE.value
    assert "merged" in (job.result or "").lower()


def test_proactive_announces_finished_background_job(tmp_path):
    rt = _rt(tmp_path, background=True)
    rt.handle("research phones and compare them", speak=lambda c: None)
    rt.worker.run_one()   # complete the job

    eng = ProactiveEngine(queue=rt.task_queue, presence=Presence(idle_fn=lambda: 0))
    announcements = eng.poll()
    assert any("finished" in a.lower() or "merged" in a.lower() for a in announcements)
    # announced once only
    assert eng.poll() == []


def test_quick_task_stays_inline_even_with_background(tmp_path):
    rt = _rt(tmp_path, background=True)
    # A simple reminder is M2 → inline, not queued.
    rt.handle("remind me to call mom in 5 minutes", speak=lambda c: None)
    assert rt.task_queue.list(JobStatus.QUEUED) == []
