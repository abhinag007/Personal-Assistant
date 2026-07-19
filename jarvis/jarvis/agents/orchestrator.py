"""Orchestrator — the supervisor (§2A.2, M3).

Decomposes a goal into sub-tasks, **creates a sub-agent at runtime** for each (writing its
role, giving it tools + a budget), runs them, **critic-reviews** each output before
accepting, and merges the accepted results into one answer. Sub-agents never talk to each
other — everything flows through the supervisor via the shared AgentState, which is
checkpointed at each step so the run can pause and resume.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from ..llm.adapter import Message, ModelAdapter
from ..tools import ToolRegistry
from .agent import Agent
from .state import AgentState, Mode


def _extract_list(text: str) -> Optional[list]:
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return [str(x) for x in data] if isinstance(data, list) else None
    except (ValueError, TypeError):
        return None


class Orchestrator:
    def __init__(
        self,
        adapter: ModelAdapter,
        tools: ToolRegistry,
        *,
        checkpoint_dir=None,
        journal=None,
        max_subtasks: int = 4,
        use_critic: bool = True,
        max_critic_rounds: int = 2,
    ):
        self.adapter = adapter
        self.tools = tools
        self.checkpoint_dir = checkpoint_dir
        self.journal = journal
        self.max_subtasks = max_subtasks
        self.use_critic = use_critic
        self.max_critic_rounds = max_critic_rounds

    # ---- planning --------------------------------------------------------

    def _decompose(self, goal: str) -> list[str]:
        prompt = (
            "Break this goal into 2-4 concrete, ordered sub-tasks. "
            'Respond ONLY as a JSON array of short strings.\nGoal: ' + goal
        )
        try:
            resp = self.adapter.chat([Message("system", "You are a planning supervisor."),
                                      Message("user", prompt)])
            steps = _extract_list(resp.text)
        except Exception:
            steps = None
        if not steps:
            steps = [goal]  # fallback: one sub-task = the whole goal
        return steps[: self.max_subtasks]

    # ---- critic ----------------------------------------------------------

    def _critique(self, subtask: str, output: str) -> tuple[bool, str]:
        if not self.use_critic:
            return True, "critic disabled"
        prompt = (f"Sub-task: {subtask}\nProposed result: {output}\n\n"
                  "Is this result adequate, complete, and safe? Answer YES or NO, then a reason.")
        try:
            resp = self.adapter.chat([Message("system", "You are a strict reviewer."),
                                      Message("user", prompt)])
            ans = (resp.text or "").strip().lower()
            if ans.startswith("no"):
                return False, resp.text
            return True, resp.text
        except Exception:
            return True, "critic unavailable"

    # ---- merge -----------------------------------------------------------

    def _merge(self, goal: str, sub_results: list[dict]) -> str:
        joined = "\n".join(f"- {r['subtask']}: {r['output']}" for r in sub_results)
        prompt = f"Goal: {goal}\nSub-results:\n{joined}\n\nWrite one concise final answer."
        try:
            resp = self.adapter.chat([Message("system", "You merge sub-results for the user."),
                                      Message("user", prompt)])
            if resp.text.strip():
                return resp.text.strip()
        except Exception:
            pass
        return joined  # fallback: just present the sub-results

    # ---- run -------------------------------------------------------------

    def run(self, goal: str) -> AgentState:
        state = AgentState(goal=goal, mode=Mode.M3_MULTI.value)
        state.plan = self._decompose(goal)
        self._checkpoint(state)
        if self.journal:
            self.journal.record(action="plan", summary=f"Planned {len(state.plan)} sub-tasks for: {goal}",
                                reasoning=" | ".join(state.plan))

        for subtask in state.plan:
            # Dynamic sub-agent: role written from the sub-task at runtime. It should use
            # web tools to research and RETURN its findings as the answer (not stash notes).
            agent = Agent(self.adapter, self.tools,
                          role=(f"a specialist handling: {subtask}. Use web_search/web_fetch to "
                                f"find real information if needed, then return your findings as "
                                f"the final answer — do not save notes"))
            output, ok, critique = self._run_with_review(agent, subtask)
            state.sub_results.append({"subtask": subtask, "output": output,
                                      "accepted": ok, "critique": critique})
            self._checkpoint(state)

        state.result = self._merge(goal, state.sub_results)
        state.status = "done"
        state.touch()
        self._checkpoint(state)
        return state

    def _run_with_review(self, agent: Agent, subtask: str):
        critique = ""
        output = ""
        for _round in range(self.max_critic_rounds):
            res = agent.run(subtask if not critique else f"{subtask}\n(Reviewer feedback: {critique})")
            output = res.output if res.ok else f"(failed: {res.error})"
            ok, critique = self._critique(subtask, output)
            if ok:
                return output, True, critique
        return output, False, critique  # escalate: failed review after max rounds

    def _checkpoint(self, state: AgentState) -> None:
        if self.checkpoint_dir:
            try:
                state.save(self.checkpoint_dir)
            except Exception:
                pass
