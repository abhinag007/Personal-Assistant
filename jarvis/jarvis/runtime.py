"""Phase 2 runtime (§2A) — assembles the agent/action stack around the brain.

One place that wires: approval engine → journal → tool registry (with built-in tools) →
calendar/staging/handoff → mode router + orchestrator. The CLI and voice layer use this so
a request can be routed to a direct reply (M1), a single agent (M2), or the supervisor (M3).
"""
from __future__ import annotations

import time
from pathlib import Path

from .agents import Orchestrator, route_mode
from .agents.agent import Agent
from .agents.state import Mode
from .connectors import CalendarStore
from .core.approval import ApprovalEngine
from .core.policy import ActionType
from .handoff import HandoffManager, StubNotifier, TelegramNotifier
from .journal import DecisionJournal, StagingStore
from .tools import ToolRegistry, ToolResult


class Runtime:
    def __init__(self, adapter, config_dir: str | Path, *, approver=None, vault=None):
        self.adapter = adapter
        self.dir = Path(config_dir)
        self.journal = DecisionJournal(self.dir / "logs" / "journal.jsonl")
        self.staging = StagingStore(self.dir / "memory" / "staging")
        self.calendar = CalendarStore(self.dir / "memory" / "calendar.db")
        self.approval = ApprovalEngine(approver=approver) if approver else ApprovalEngine()
        self.registry = ToolRegistry(approval=self.approval, journal=self.journal)

        # Notifier: real Telegram if a bot token + chat id are in the vault, else stub.
        notifier = StubNotifier()
        if vault is not None:
            try:
                token = vault.get_secret("telegram_bot_token")
                chat = vault.get_secret("telegram_chat_id")
                if token and chat:
                    notifier = TelegramNotifier(token, chat)
            except Exception:
                pass
        self.handoff = HandoffManager(self.dir / "memory" / "handoff.json", notifier=notifier)

        self._register_builtin_tools()

    # ---- built-in tools --------------------------------------------------

    def _register_builtin_tools(self) -> None:
        reg = self.registry

        @reg.tool("get_time", "Return the current local date and time.", ActionType.NETWORK_FETCH)
        def _get_time():
            return ToolResult.success(time.strftime("%A %Y-%m-%d %H:%M"))

        @reg.tool("add_reminder", "Add a reminder. args: text (str), in_minutes (number).",
                  ActionType.WRITE_SANDBOX)
        def _add_reminder(text="", in_minutes=0):
            due = time.time() + float(in_minutes) * 60
            rid = self.calendar.add(text, due)
            return ToolResult.success(f"reminder '{text}' set (id {rid})")

        @reg.tool("list_reminders", "List upcoming reminders.", ActionType.READ_FILE)
        def _list_reminders():
            ups = self.calendar.upcoming()
            return ToolResult.success("; ".join(f"{r.text}" for r in ups) or "none")

        @reg.tool("stage_note", "Save a speculative note for the user to review later.",
                  ActionType.WRITE_SANDBOX)
        def _stage_note(title="", body=""):
            sid = self.staging.add("note", title, {"body": body})
            return ToolResult.success(f"staged (id {sid})")

    # ---- request handling (M1/M2/M3) -------------------------------------

    def handle(self, request: str) -> str:
        """Route a request to the right mode and return the final answer text."""
        mode = route_mode(request)
        self.journal.record(action="route", summary=request, reasoning=f"mode={mode.value}")

        if mode is Mode.M1_DIRECT:
            from .llm.adapter import Message
            resp = self.adapter.chat([Message("user", request)])
            return resp.text

        if mode is Mode.M2_AGENT:
            agent = Agent(self.adapter, self.registry, role="Jarvis's task agent")
            res = agent.run(request)
            return res.output if res.ok else f"I couldn't finish that: {res.error}"

        # M3
        orch = Orchestrator(self.adapter, self.registry,
                            checkpoint_dir=self.dir / "memory" / "runs",
                            journal=self.journal)
        state = orch.run(request)
        return state.result or "(no result)"
