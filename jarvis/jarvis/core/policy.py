"""Policy — the immutable rules of the system (§11, §17).

This defines two things the rest of the system is not allowed to override:
  1. Which filesystem locations are writable (the sandbox), and which are read-only.
  2. Which action types are irreversible and therefore require human approval.

Kept as plain data + tiny pure functions so it is trivially auditable.
"""
from __future__ import annotations

from enum import Enum


class ActionRisk(str, Enum):
    """Classification used by the approval engine (§11)."""

    REVERSIBLE = "reversible"        # proceed automatically (git can undo, or it's read-only)
    IRREVERSIBLE = "irreversible"   # must ask the human first
    FORBIDDEN = "forbidden"         # never allowed, even with approval (touches the core)


# Action categories the assistant may attempt. Extended in later phases.
class ActionType(str, Enum):
    READ_FILE = "read_file"
    WRITE_SANDBOX = "write_sandbox"        # write inside the sandbox → reversible via git
    WRITE_OUTSIDE = "write_outside"        # write outside sandbox → irreversible (needs approval)
    DELETE_SANDBOX = "delete_sandbox"      # reversible via git
    DELETE_OUTSIDE = "delete_outside"      # irreversible
    MODIFY_CORE = "modify_core"            # FORBIDDEN — the AI may never touch the core
    SEND_MESSAGE = "send_message"          # email / chat → irreversible
    SPEND_MONEY = "spend_money"            # purchases / transfers → irreversible
    POST_ONLINE = "post_online"            # irreversible
    RUN_COMMAND = "run_command"            # depends; classified case-by-case in later phases
    NETWORK_FETCH = "network_fetch"        # read-only web fetch → reversible


# The static risk map. This is the heart of §11 and must stay conservative:
# when in doubt, an action is IRREVERSIBLE (ask), never silently reversible.
RISK_MAP: dict[ActionType, ActionRisk] = {
    ActionType.READ_FILE: ActionRisk.REVERSIBLE,
    ActionType.NETWORK_FETCH: ActionRisk.REVERSIBLE,
    ActionType.WRITE_SANDBOX: ActionRisk.REVERSIBLE,
    ActionType.DELETE_SANDBOX: ActionRisk.REVERSIBLE,
    ActionType.WRITE_OUTSIDE: ActionRisk.IRREVERSIBLE,
    ActionType.DELETE_OUTSIDE: ActionRisk.IRREVERSIBLE,
    ActionType.SEND_MESSAGE: ActionRisk.IRREVERSIBLE,
    ActionType.SPEND_MONEY: ActionRisk.IRREVERSIBLE,
    ActionType.POST_ONLINE: ActionRisk.IRREVERSIBLE,
    ActionType.RUN_COMMAND: ActionRisk.IRREVERSIBLE,   # conservative default
    ActionType.MODIFY_CORE: ActionRisk.FORBIDDEN,
}


def risk_of(action: ActionType) -> ActionRisk:
    """Return the risk class for an action. Unknown actions default to IRREVERSIBLE."""
    return RISK_MAP.get(action, ActionRisk.IRREVERSIBLE)


# The exact phrase that triggers total shutdown (§23). Matched case-insensitively.
KILL_PHRASE = "jarvis end yourself"
