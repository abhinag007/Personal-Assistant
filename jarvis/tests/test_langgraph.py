"""LangGraph orchestrator + HITL interrupt tests (§2A, §11).

Skipped automatically if langgraph isn't installed (it's an optional dependency).
"""
import pytest

pytest.importorskip("langgraph")

from jarvis.agents.graph import LangGraphOrchestrator  # noqa: E402
from jarvis.agents.hitl import build_approval_graph  # noqa: E402
from jarvis.llm.adapter import ChatResponse, ModelAdapter  # noqa: E402
from jarvis.tools import ToolRegistry  # noqa: E402


class ScriptedAdapter(ModelAdapter):
    name = "scripted"

    def __init__(self, script):
        self._script = list(script)

    def chat(self, messages, tools=None):
        text = self._script.pop(0) if self._script else '{"final": "done"}'
        return ChatResponse(text=text, model=self.name)

    def stream(self, messages):
        yield "x"

    def embed(self, texts):
        return [[0.0] for _ in texts]


def test_langgraph_orchestrator_runs_plan_execute_merge():
    script = [
        '["research topic", "write summary"]',   # plan
        '{"final": "found info"}', "YES ok",     # sub-agent 1 + critic
        '{"final": "summary done"}', "YES ok",   # sub-agent 2 + critic
        "Merged final answer.",                   # merge
    ]
    orch = LangGraphOrchestrator(ScriptedAdapter(script), ToolRegistry())
    state = orch.run("research and summarise")
    assert state.status == "done"
    assert len(state.plan) == 2
    assert len(state.sub_results) == 2
    assert state.result


def test_hitl_interrupt_pauses_then_resumes_on_approval():
    from langgraph.types import Command

    app = build_approval_graph()
    cfg = {"configurable": {"thread_id": "t1"}}
    # First invoke pauses at the human interrupt (does not finish).
    res = app.invoke({"action": "send money", "approved": None, "result": None}, cfg)
    assert "__interrupt__" in res or res.get("result") is None  # paused, not executed

    # Human approves → graph RESUMES from the interrupt (not a re-run) and acts.
    final = app.invoke(Command(resume=True), cfg)
    assert final["result"] == "executed: send money"


def test_hitl_interrupt_resume_with_denial():
    from langgraph.types import Command

    app = build_approval_graph()
    cfg = {"configurable": {"thread_id": "t2"}}
    app.invoke({"action": "delete files", "approved": None, "result": None}, cfg)
    final = app.invoke(Command(resume=False), cfg)   # human denies
    assert final["result"] == "cancelled by human"
