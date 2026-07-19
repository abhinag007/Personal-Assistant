"""BrainLoop (§13) — the central orchestrator that ties everything together.

For one turn it runs the canonical pipeline:
    (input text) → kill-switch check → memory recall (§8) → prompt assembly (persona §33)
    → model stream (§1) with TTFW timing (§18) → output → memory write → audit + trace.

It is transport-agnostic: the same `handle_turn()` serves the text REPL and the voice
pipeline. Voice just supplies the text (from STT) and a `speak` sink (to TTS).

Safety: the kill switch is checked first every turn; irreversible actions (from Phase 2)
route through `confirm_action()` which uses the Phase 0 approval engine (§11, §35).
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from ..audit import AuditLog
from ..core.approval import ActionRequest, ApprovalEngine
from ..core.kill_switch import KillSwitch
from ..llm.adapter import Message, ModelAdapter
from ..memory import MemoryStore, MemoryType
from ..tracing import Tracer
from .curiosity import asked_flag, next_curiosity
from .dialog import DialogWindow
from .facts import extract_facts
from .identity import extract_name, extract_preferred_address
from .persona import build_system_prompt


class BrainLoop:
    def __init__(
        self,
        adapter: ModelAdapter,
        memory: MemoryStore,
        *,
        audit: Optional[AuditLog] = None,
        tracer: Optional[Tracer] = None,
        kill_switch: Optional[KillSwitch] = None,
        approval: Optional[ApprovalEngine] = None,
        user_name: Optional[str] = None,
        recall_k: int = 5,
        dialog: Optional[DialogWindow] = None,
        curious: bool = True,
        extract_facts_enabled: bool = True,
    ):
        self.adapter = adapter
        self.memory = memory
        self.audit = audit
        self.tracer = tracer or Tracer.noop()
        self.kill_switch = kill_switch
        self.approval = approval
        # Fallback name only; the real name is LEARNED and stored in memory's profile (§8).
        self._fallback_name = user_name
        self.recall_k = recall_k
        self.dialog = dialog or DialogWindow()
        self.curious = curious                       # append a "get to know you" question (§8)
        self.extract_facts_enabled = extract_facts_enabled
        self.last_ttfw: Optional[float] = None  # time-to-first-word of the last turn (§18)

    @property
    def user_name(self) -> Optional[str]:
        """The name Jarvis currently knows — learned from conversation, else the fallback."""
        return self.memory.get_profile("name") or self._fallback_name

    @property
    def preferred_address(self) -> Optional[str]:
        """How the user wants to be addressed, separate from their real name."""
        return self.memory.get_profile("preferred_address")

    # ---- one conversational turn ----------------------------------------

    def handle_turn(self, text: str, *, speak: Optional[Callable[[str], None]] = None) -> str:
        """Process one user utterance; stream the reply to `speak` (defaults to print)."""
        emit = speak or (lambda chunk: print(chunk, end="", flush=True))

        # 1. Kill switch is always checked first.
        if self.kill_switch and self.kill_switch.check(text):
            return ""  # (trigger() exits before we get here in production)

        with self.tracer.span("handle_turn", input=text) as span:
            self._learn_from(text, span)
            direct = self._direct_profile_answer(text)
            if direct is not None:
                emit(direct)
                self.dialog.add_user(text)
                self.dialog.add_assistant(direct)
                self.memory.add(f"{self.user_name or 'The user'} said: {text}", MemoryType.EPISODIC)
                return direct

            # 2. Recall relevant memories (§8).
            with self.tracer.span("memory.recall", cue=text):
                recalled = self.memory.recall(text, k=self.recall_k)
            memory_context = "\n".join(f"- {m.text}" for m in recalled)
            span.set("recalled", len(recalled))

            # 3. Assemble the prompt: persona + learned profile facts + memory + dialog.
            known_name = self.user_name
            system = build_system_prompt(known_name, memory_context, self.memory.all_profile())
            self.dialog.add_user(text)
            messages: list[Message] = [Message("system", system), *self.dialog.history()]

            # 4. Stream the reply, timing the first token (TTFW, §18).
            start = time.perf_counter()
            first_token_at: Optional[float] = None
            parts: list[str] = []
            with self.tracer.span("model.stream", model=self.adapter.name):
                for chunk in self.adapter.stream(messages):
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    parts.append(chunk)
                    emit(chunk)
            model_reply = "".join(parts).strip()
            self.last_ttfw = (first_token_at - start) if first_token_at else None
            span.set("ttfw_s", round(self.last_ttfw, 3) if self.last_ttfw else None)

            # 5. Curiosity: append ONE question about the next thing it doesn't know yet.
            reply = model_reply
            if self.curious:
                nxt = next_curiosity(self.memory.all_profile())
                if nxt:
                    field, question = nxt
                    sep = " " if model_reply else ""
                    emit(sep + question)
                    reply = (model_reply + sep + question).strip()
                    self.memory.set_profile(asked_flag(field), "1")
                    span.set("asked_about", field)

            # 6. Update dialog + long-term episodic memory.
            self.dialog.add_assistant(reply)
            speaker_label = self.user_name or "The user"
            self.memory.add(f"{speaker_label} said: {text}", MemoryType.EPISODIC)

            # 7. Audit.
            if self.audit:
                self.audit.record(
                    "conversation", f"Handled a turn from {self.user_name}",
                    risk="reversible",
                    extra={"ttfw_s": self.last_ttfw, "recalled": len(recalled)},
                )
        return reply

    # ---- learning: name + durable facts (§8) -----------------------------

    def _learn_from(self, text: str, span) -> None:
        """Extract and store durable facts about the user from their message."""
        # Name — reliable regex baseline.
        learned = extract_name(text)
        if learned and learned != self.memory.get_profile("name"):
            self.memory.set_profile("name", learned)
            self.memory.add(f"The user's name is {learned}.",
                            MemoryType.SEMANTIC, salience=0.9)
            span.set("learned_name", learned)

        preferred = extract_preferred_address(text)
        if preferred and preferred != self.memory.get_profile("preferred_address"):
            self.memory.set_profile("preferred_address", preferred)
            self.memory.add(f"The user prefers to be addressed as {preferred}.",
                            MemoryType.SEMANTIC, salience=0.9)
            span.set("preferred_address", preferred)

        # Other durable facts — model-based extraction (no-op offline / on failure).
        if self.extract_facts_enabled:
            with self.tracer.span("facts.extract"):
                facts = extract_facts(self.adapter, text)
            for key, value in facts.items():
                if value and value != self.memory.get_profile(key):
                    self.memory.set_profile(key, value)
                    self.memory.add(f"About the user — {key}: {value}",
                                    MemoryType.SEMANTIC, salience=0.8)
            if facts:
                span.set("learned_facts", list(facts.keys()))

    def _direct_profile_answer(self, text: str) -> Optional[str]:
        low = text.strip().lower()
        if not low:
            return None
        if "what is my name" not in low and "what's my name" not in low:
            return None
        name = self.user_name
        preferred = self.preferred_address
        if name and preferred and preferred.lower() != name.lower():
            return f"Your name is {name}. You asked me to address you as {preferred}."
        if name:
            return f"Your name is {name}."
        if preferred:
            return f"I do not know your name yet. You asked me to address you as {preferred}."
        return "I do not know your name yet."

    # ---- voice-safe confirmation for irreversible actions (§11, §35) -----

    def confirm_action(self, request: ActionRequest) -> bool:
        """Gate an irreversible action through the approval engine. Used from Phase 2."""
        if self.approval is None:
            return False
        decision = self.approval.evaluate(request)
        if self.audit:
            self.audit.record(
                request.action.value, request.summary,
                outcome="approved" if decision.approved else "denied",
                risk=decision.risk.value, reason=request.reason,
            )
        return decision.approved
