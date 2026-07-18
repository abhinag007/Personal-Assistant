"""Tool interface + registry (§11, §2A.6).

Executing any tool routes through the approval engine: the tool declares an ActionType,
the registry classifies it (reversible / irreversible / forbidden), and irreversible tools
require human approval before the function runs. This is the single safe path for actions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..core.approval import ActionRequest, ApprovalEngine
from ..core.policy import ActionType


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    error: str = ""

    @staticmethod
    def success(output: Any = None) -> "ToolResult":
        return ToolResult(ok=True, output=output)

    @staticmethod
    def failure(error: str) -> "ToolResult":
        return ToolResult(ok=False, error=error)


@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., ToolResult]
    action_type: ActionType = ActionType.RUN_COMMAND
    # A function (kwargs) -> short human summary, for the approval prompt / journal (§37).
    summarize: Optional[Callable[[dict], str]] = None

    def summary_for(self, kwargs: dict) -> str:
        if self.summarize:
            try:
                return self.summarize(kwargs)
            except Exception:
                pass
        return f"{self.name}({', '.join(f'{k}={v!r}' for k, v in kwargs.items())})"


class ToolRegistry:
    def __init__(self, approval: Optional[ApprovalEngine] = None, journal=None):
        self._tools: dict[str, Tool] = {}
        self.approval = approval
        self.journal = journal  # optional DecisionJournal (§26)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def tool(self, name: str, description: str, action_type: ActionType = ActionType.RUN_COMMAND,
             summarize=None):
        """Decorator to register a plain function as a tool."""
        def deco(func):
            self.register(Tool(name, description, func, action_type, summarize))
            return func
        return deco

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def catalog(self) -> list[dict]:
        """Machine-readable list for an agent to choose from."""
        return [{"name": t.name, "description": t.description, "risk": t.action_type.value}
                for t in self._tools.values()]

    def execute(self, name: str, **kwargs) -> ToolResult:
        """Run a tool, gating irreversible ones through the approval engine (§11)."""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.failure(f"no such tool: {name}")

        summary = tool.summary_for(kwargs)
        if self.approval is not None:
            decision = self.approval.evaluate(
                ActionRequest(tool.action_type, summary, reason=f"tool:{name}", details=kwargs)
            )
            if self.journal is not None:
                self.journal.record(
                    action=name, summary=summary, decision=decision.risk.value,
                    approved=decision.approved, reasoning=decision.rationale,
                )
            if not decision.approved:
                return ToolResult.failure(f"not approved: {decision.rationale}")

        try:
            result = tool.func(**kwargs)
            if not isinstance(result, ToolResult):
                result = ToolResult.success(result)
        except Exception as e:  # graceful failure (§21)
            result = ToolResult.failure(f"{type(e).__name__}: {e}")

        if self.journal is not None:
            self.journal.record(action=name, summary=summary,
                                outcome="ok" if result.ok else "error",
                                reasoning=result.error or "completed")
        return result
