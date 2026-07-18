"""Agent framework (§2A, §7) — the M1/M2/M3 workflow.

- Agent: a scoped ReAct loop (think → tool → observe) with a tool subset + budget (M2).
- Orchestrator: supervisor (M3) that decomposes a goal, creates sub-agents at runtime,
  critic-reviews their outputs, and merges.
- route_mode: pick M1 (direct) / M2 (single agent) / M3 (multi-agent).
- AgentState / Interrupt: the checkpointed shared contract + human-in-the-loop pause.
"""
from .state import AgentState, Interrupt, Mode  # noqa: F401
from .agent import Agent, AgentResult  # noqa: F401
from .router import route_mode  # noqa: F401
from .orchestrator import Orchestrator  # noqa: F401
