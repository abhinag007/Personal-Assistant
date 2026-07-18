"""Approval engine tests (§11) — reversible auto-proceeds, irreversible asks, core forbidden."""
from jarvis.core.approval import ActionRequest, ApprovalEngine
from jarvis.core.policy import ActionRisk, ActionType


def _engine(answer: bool):
    # Inject an approver that always returns the given answer (no console).
    return ApprovalEngine(approver=lambda req, risk: answer)


def test_reversible_auto_approved_without_asking():
    asked = {"called": False}

    def approver(req, risk):
        asked["called"] = True
        return False

    engine = ApprovalEngine(approver=approver)
    decision = engine.evaluate(ActionRequest(ActionType.WRITE_SANDBOX, "write a file"))
    assert decision.approved is True
    assert decision.risk is ActionRisk.REVERSIBLE
    assert asked["called"] is False  # reversible must NOT prompt the human


def test_irreversible_requires_human_yes():
    engine = _engine(answer=True)
    decision = engine.evaluate(ActionRequest(ActionType.SPEND_MONEY, "buy something"))
    assert decision.approved is True
    assert decision.risk is ActionRisk.IRREVERSIBLE


def test_irreversible_denied_when_human_says_no():
    engine = _engine(answer=False)
    decision = engine.evaluate(ActionRequest(ActionType.SEND_MESSAGE, "send email"))
    assert decision.approved is False


def test_core_modification_is_forbidden_even_with_yes():
    engine = _engine(answer=True)  # human says yes, but it must still be refused
    decision = engine.evaluate(ActionRequest(ActionType.MODIFY_CORE, "rewrite kill switch"))
    assert decision.approved is False
    assert decision.risk is ActionRisk.FORBIDDEN


def test_unknown_action_defaults_to_irreversible():
    # RUN_COMMAND is conservatively irreversible.
    engine = _engine(answer=False)
    decision = engine.evaluate(ActionRequest(ActionType.RUN_COMMAND, "run something"))
    assert decision.risk is ActionRisk.IRREVERSIBLE
    assert decision.approved is False
