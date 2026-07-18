"""Approval engine — the reversibility gate (§11).

Before any action executes, it is classified. Reversible actions proceed; irreversible
ones are blocked until a human approves; forbidden ones are refused outright.

In Phase 0 the "ask the human" step is a pluggable callback (console prompt by default).
Later phases wire it to voice confirmation (§35) and Telegram approvals (§10) without
changing this logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .policy import ActionRisk, ActionType, risk_of


@dataclass
class ActionRequest:
    """A proposed action awaiting a go/no-go decision."""

    action: ActionType
    summary: str                      # human-readable "what I'm about to do" (§37)
    reason: str = ""                  # why (for the decision journal, §26)
    details: dict = field(default_factory=dict)


@dataclass
class ApprovalDecision:
    approved: bool
    risk: ActionRisk
    rationale: str


# An approver takes an ActionRequest and returns True (approved) / False (denied).
Approver = Callable[[ActionRequest, ActionRisk], bool]


def console_approver(request: ActionRequest, risk: ActionRisk) -> bool:
    """Default human approver: read back the action and ask for yes/no on the console."""
    print("\n[APPROVAL REQUIRED] Jarvis wants to do something irreversible:")
    print(f"  What:  {request.summary}")
    if request.reason:
        print(f"  Why:   {request.reason}")
    print(f"  Risk:  {risk.value}")
    answer = input("  Approve? (yes/no): ").strip().lower()
    return answer in {"y", "yes"}


class ApprovalEngine:
    def __init__(self, approver: Optional[Approver] = None):
        # Default to the console approver; swappable for voice/Telegram later.
        self._approver: Approver = approver or console_approver

    def set_approver(self, approver: Approver) -> None:
        self._approver = approver

    def evaluate(self, request: ActionRequest) -> ApprovalDecision:
        """Classify and, if needed, ask the human."""
        risk = risk_of(request.action)

        if risk is ActionRisk.FORBIDDEN:
            return ApprovalDecision(
                approved=False,
                risk=risk,
                rationale="Forbidden action (touches the immutable core §23); refused outright.",
            )

        if risk is ActionRisk.REVERSIBLE:
            return ApprovalDecision(
                approved=True,
                risk=risk,
                rationale="Reversible (read-only or sandbox change revertible via git §17); auto-approved.",
            )

        # IRREVERSIBLE → require explicit human approval.
        granted = bool(self._approver(request, risk))
        return ApprovalDecision(
            approved=granted,
            risk=risk,
            rationale="Human approved." if granted else "Human denied.",
        )
