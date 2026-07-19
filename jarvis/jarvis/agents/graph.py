"""LangGraph orchestrator (§2A, §7) — the supervisor as a real StateGraph.

This is the LangGraph implementation of the M3 supervisor: a checkpointed graph
plan → execute → merge. LangGraph gives us durable, resumable execution and native
human-in-the-loop `interrupt()` (see hitl.py). It's optional: the Runtime falls back to
the native Orchestrator if langgraph isn't installed.

It reuses the native Orchestrator's LLM helpers (decompose / critic / merge / sub-agent
review) so behavior matches; only the control flow is now a graph.
"""
from __future__ import annotations

import uuid
from typing import Optional, TypedDict

from ..tools import ToolRegistry
from .agent import Agent
from .orchestrator import Orchestrator
from .state import AgentState, Mode


class _GState(TypedDict):
    goal: str
    plan: list
    sub_results: list
    result: Optional[str]


class LangGraphOrchestrator:
    def __init__(self, adapter, tools: ToolRegistry, *, checkpoint_dir=None,
                 journal=None, **kw):
        from langgraph.graph import StateGraph, START, END

        # Borrow the tested LLM helpers (decompose/critic/merge/sub-agent review).
        self._h = Orchestrator(adapter, tools, journal=journal, **kw)
        self.adapter = adapter
        self.tools = tools
        self.journal = journal

        g = StateGraph(_GState)
        g.add_node("plan", self._plan)
        g.add_node("execute", self._execute)
        g.add_node("merge", self._merge)
        g.add_edge(START, "plan")
        g.add_edge("plan", "execute")
        g.add_edge("execute", "merge")
        g.add_edge("merge", END)

        # Checkpointer = durable/resumable state. MemorySaver by default; swap for
        # SqliteSaver for cross-restart durability.
        from langgraph.checkpoint.memory import MemorySaver
        self._app = g.compile(checkpointer=MemorySaver())

    # ---- nodes -----------------------------------------------------------

    def _plan(self, state: _GState) -> dict:
        plan = self._h._decompose(state["goal"])
        if self.journal:
            self.journal.record(action="plan", summary=f"{len(plan)} sub-tasks",
                                reasoning=" | ".join(plan))
        return {"plan": plan}

    def _execute(self, state: _GState) -> dict:
        subs = []
        for subtask in state["plan"]:
            agent = Agent(self.adapter, self.tools,
                          role=(f"a specialist handling: {subtask}. Use web_search/web_fetch "
                                f"to find real information, then return findings as the answer"))
            out, ok, critique = self._h._run_with_review(agent, subtask)
            subs.append({"subtask": subtask, "output": out, "accepted": ok, "critique": critique})
        return {"sub_results": subs}

    def _merge(self, state: _GState) -> dict:
        return {"result": self._h._merge(state["goal"], state["sub_results"])}

    # ---- run -------------------------------------------------------------

    def run(self, goal: str) -> AgentState:
        cfg = {"configurable": {"thread_id": uuid.uuid4().hex[:8]}}
        final = self._app.invoke(
            {"goal": goal, "plan": [], "sub_results": [], "result": None}, cfg)
        st = AgentState(goal=goal, mode=Mode.M3_MULTI.value)
        st.plan = final.get("plan", [])
        st.sub_results = final.get("sub_results", [])
        st.result = final.get("result")
        st.status = "done"
        return st
