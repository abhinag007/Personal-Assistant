"""Shared agent state + interrupts (§2A.4, §11, §30).

AgentState is the typed contract that flows through the workflow and is checkpointed at each
step, so a run can pause (for human approval or a blocker) and resume from exactly where it
stopped. Interrupt is how any depth signals "a human is needed here".
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class Mode(str, Enum):
    M1_DIRECT = "M1_direct"        # single model call, no agents
    M2_AGENT = "M2_single_agent"  # one ReAct agent with tools
    M3_MULTI = "M3_multi_agent"   # supervisor + sub-agents


class InterruptType(str, Enum):
    APPROVAL = "approval"     # irreversible action needs a yes/no (§11)
    BLOCKED = "blocked"       # human-only blocker: captcha, login, decision (§30)
    CLARIFY = "clarify"       # need info from the user


@dataclass
class Interrupt:
    type: InterruptType
    prompt: str               # what to ask the human
    context: dict = field(default_factory=dict)


@dataclass
class AgentState:
    goal: str
    mode: str = Mode.M2_AGENT.value
    plan: list[str] = field(default_factory=list)
    sub_results: list[dict] = field(default_factory=list)
    result: Optional[str] = None
    citations: list[str] = field(default_factory=list)
    confidence: Optional[float] = None
    status: str = "running"   # running | done | blocked | failed
    interrupt: Optional[dict] = None    # set when paused for a human
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    updated: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated = time.time()

    # ---- checkpointing (§2A.4) ------------------------------------------

    def save(self, directory: str | Path) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.run_id}.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "AgentState":
        d = json.loads(Path(path).read_text())
        return cls(**d)
