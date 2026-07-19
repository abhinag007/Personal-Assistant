"""Human-in-the-loop via LangGraph interrupts (§11, §30).

Demonstrates real pause/resume: a graph node calls `interrupt()` before an irreversible
action, which *pauses the whole graph and persists its state*. The human answers later, and
the graph resumes from exactly that point via `Command(resume=...)` — not a re-run.

This is the durable-interrupt mechanism the architecture calls for; the synchronous approval
engine remains the default fast path, and this is available for long-running / async flows.
"""
from __future__ import annotations

from typing import Optional, TypedDict


class _State(TypedDict):
    action: str
    approved: Optional[bool]
    result: Optional[str]


def build_approval_graph():
    """A tiny graph: ask-human (interrupt) → act-if-approved. Returns a compiled app."""
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import START, END, StateGraph
    from langgraph.types import interrupt

    def ask_human(state: _State) -> dict:
        # Pauses here; whatever the human sends on resume becomes `decision`.
        decision = interrupt({"question": f"Approve this irreversible action? {state['action']}"})
        return {"approved": bool(decision)}

    def act(state: _State) -> dict:
        if state.get("approved"):
            return {"result": f"executed: {state['action']}"}
        return {"result": "cancelled by human"}

    g = StateGraph(_State)
    g.add_node("ask_human", ask_human)
    g.add_node("act", act)
    g.add_edge(START, "ask_human")
    g.add_edge("ask_human", "act")
    g.add_edge("act", END)
    return g.compile(checkpointer=MemorySaver())
