"""Agent — a scoped ReAct loop (§2A.3, M2).

The agent is given a role, a subset of tools, and a step budget. Each step it asks the model
for the next action as JSON — either a tool call `{"tool": name, "args": {...}}` or a final
answer `{"final": "..."}` — executes tools through the registry (which enforces approval),
observes the result, and repeats until done or the budget is hit (a defined exit, never a
silent spin).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from ..llm.adapter import Message, ModelAdapter
from ..tools import ToolRegistry
from .state import Interrupt


@dataclass
class AgentResult:
    ok: bool
    output: str
    steps: int = 0
    error: str = ""
    trace: list[str] = field(default_factory=list)
    interrupt: Optional[Interrupt] = None


def _parse_action(text: str):
    """Return ('tool', name, args) or ('final', answer, {})."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(0))
        except (ValueError, TypeError):
            d = None
        if isinstance(d, dict):
            if "tool" in d and d["tool"]:
                return "tool", str(d["tool"]), (d.get("args") or {})
            if "final" in d:
                return "final", str(d["final"]), {}
    return "final", (text or "").strip(), {}


class Agent:
    def __init__(
        self,
        adapter: ModelAdapter,
        tools: ToolRegistry,
        tool_names: Optional[list[str]] = None,
        *,
        role: str = "a focused task agent",
        max_steps: int = 6,
    ):
        self.adapter = adapter
        self.tools = tools
        self.tool_names = tool_names if tool_names is not None else tools.names()
        self.role = role
        self.max_steps = max_steps

    def _system(self) -> str:
        catalog = [t for t in self.tools.catalog() if t["name"] in self.tool_names]
        lines = "\n".join(f'  - {t["name"]}: {t["description"]} (risk: {t["risk"]})' for t in catalog)
        return (
            f"You are {self.role}. Accomplish the task using the tools below.\n"
            "Respond with ONE JSON object per step, nothing else:\n"
            '  to use a tool: {"tool": "<name>", "args": { ... }}\n'
            '  when finished: {"final": "<answer for the user>"}\n'
            f"Available tools:\n{lines or '  (none)'}\n"
            "Use one tool at a time, observe the result, then continue. Be concise."
        )

    def run(self, task: str) -> AgentResult:
        messages = [Message("system", self._system()), Message("user", task)]
        trace: list[str] = []

        for step in range(1, self.max_steps + 1):
            resp = self.adapter.chat(messages)
            kind, a, b = _parse_action(resp.text)

            if kind == "final":
                return AgentResult(ok=True, output=a, steps=step, trace=trace)

            # tool call
            name, args = a, b
            trace.append(f"step {step}: tool {name}({args})")
            if name not in self.tool_names:
                obs = f"error: tool '{name}' not available to you"
            else:
                result = self.tools.execute(name, **args)
                if result.ok:
                    obs = f"ok: {result.output}"
                else:
                    obs = f"error: {result.error}"
                trace[-1] += f" -> {obs}"
            messages.append(Message("assistant", resp.text))
            messages.append(Message("user", f"Observation: {obs}"))

        # Budget exhausted — defined exit, not a silent spin (§2A.3).
        return AgentResult(ok=False, output="", steps=self.max_steps,
                           error="step budget exhausted", trace=trace)
