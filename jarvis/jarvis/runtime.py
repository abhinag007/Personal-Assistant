"""Phase 2 runtime (§2A) — assembles the agent/action stack around the brain.

One place that wires: approval engine → journal → tool registry (with built-in tools) →
calendar/staging/handoff → mode router + orchestrator. The CLI and voice layer use this so
a request can be routed to a direct reply (M1), a single agent (M2), or the supervisor (M3).
"""
from __future__ import annotations

import re
import time
import threading
from pathlib import Path

from .agents import Orchestrator, route_mode
from .agents.agent import Agent
from .agents.state import Mode
from .connectors import CalendarStore
from .core.approval import ApprovalEngine
from .core.git_tracker import GitTracker
from .core.policy import ActionType
from .core.sandbox_guard import SandboxGuard, SandboxViolation
from .handoff import HandoffManager, StubNotifier, TelegramNotifier
from .journal import DecisionJournal, StagingStore
from .tasks import JobStatus, TaskQueue, Worker
from .tools import ToolRegistry, ToolResult, WebSearch, web_fetch


class Runtime:
    def __init__(self, adapter, config_dir: str | Path, *, approver=None, vault=None,
                 brain=None, background=False, sandbox_path: str = ""):
        self.adapter = adapter
        self.brain = brain          # BrainLoop for M1 conversation + memory (optional)
        self.background = background  # dispatch long tasks to a worker thread (voice/chat)
        self.dir = Path(config_dir)
        self.journal = DecisionJournal(self.dir / "logs" / "journal.jsonl")
        self.staging = StagingStore(self.dir / "memory" / "staging")
        self.calendar = CalendarStore(self.dir / "memory" / "calendar.db")
        self.approval = ApprovalEngine(approver=approver) if approver else ApprovalEngine()
        self.registry = ToolRegistry(approval=self.approval, journal=self.journal)
        self.sandbox_path = sandbox_path
        self.guard = SandboxGuard(sandbox_path) if sandbox_path else None
        self.git = GitTracker(sandbox_path) if sandbox_path else None

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

        # Optional Tavily key → better search; falls back to DuckDuckGo automatically.
        self.tavily_key = None
        if vault is not None:
            try:
                self.tavily_key = vault.get_secret("tavily_api_key")
            except Exception:
                pass

        # Background task queue + worker (for multitasking while you keep talking, §9).
        self.task_queue = TaskQueue(self.dir / "memory" / "tasks.db")
        self.task_queue.requeue_running()  # reset anything interrupted by a crash (§27)
        self.worker = Worker(self.task_queue)
        self.worker.register("agent_task", self._run_agent_job)
        self._bg_started = False
        # Voice and the Telegram poller can both submit requests. Keep adapter, tools, and
        # approval state serialized instead of letting them race each other.
        self._request_lock = threading.RLock()

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
        def _stage_note(title="", body="", **kw):
            # Tolerant of common arg-name variants an agent might guess.
            body = body or kw.get("text") or kw.get("note") or kw.get("content") or ""
            title = title or (body[:40] if body else "note")
            sid = self.staging.add("note", title, {"body": body})
            return ToolResult.success(f"staged (id {sid})")

        @reg.tool("write_file", "Write text/code to a file inside the Jarvis sandbox. "
                  "args: path (relative to sandbox), content (str). Requires approval, "
                  "then writes through the sandbox guard and auto-commits.",
                  ActionType.WRITE_FILE)
        def _write_file(path="", content="", **kw):
            content = content if content != "" else kw.get("text", "")
            if not self.guard or not self.git:
                return ToolResult.failure("sandbox is not configured; run onboarding first")
            if not path:
                return ToolResult.failure("path required")
            try:
                target = self.guard.write_text(path, content)
                self.git.auto_commit(f"write_file {target.relative_to(self.guard.sandbox_root)}")
            except SandboxViolation as e:
                return ToolResult.failure(str(e))
            except Exception as e:
                return ToolResult.failure(f"{type(e).__name__}: {e}")
            return ToolResult.success(f"wrote and committed {target}")

        # ---- web tools (real research) ----------------------------------
        # Tavily first if a key is stored, else DuckDuckGo (auto-fallback on limit/error).
        websearch = WebSearch(tavily_api_key=self.tavily_key)

        self._websearch = websearch  # exposed so the CLI can report the source

        @reg.tool("web_search", "Search the web. args: query (str), max_results (int).",
                  ActionType.NETWORK_FETCH)
        def _web_search(query="", max_results=5):
            res = websearch.search(query, int(max_results or 5))
            if websearch.last_source:  # record which backend served it (§26)
                self.journal.record(action="web_search_source", summary=f"query: {query}",
                                    reasoning=f"served by {websearch.last_source}")
            return res

        @reg.tool("web_fetch", "Fetch a web page and return its readable text. args: url (str).",
                  ActionType.NETWORK_FETCH)
        def _web_fetch(url=""):
            return web_fetch(url)

        # ---- macOS control (§28) ----------------------------------------
        from .connectors import desktop as _desk

        @reg.tool("open_app", "Open a Mac application. args: name (e.g. 'Google Chrome', "
                  "'Visual Studio Code', 'Notes').", ActionType.OPEN_APP)
        def _open_app(name=""):
            return _desk.open_app(name)

        @reg.tool("open_path", "Open a file or folder in its default app. args: path "
                  "(e.g. '~/Desktop/notes.txt').", ActionType.OPEN_APP)
        def _open_path(path=""):
            return _desk.open_path(path)

        @reg.tool("open_url", "Open a URL in the default browser. args: url.", ActionType.OPEN_APP)
        def _open_url(url=""):
            return _desk.open_url(url)

        @reg.tool("browser_search", "Search the web in a browser window. args: query (str), "
                  "browser (default 'Google Chrome').", ActionType.OPEN_APP)
        def _browser_search(query="", browser="Google Chrome"):
            return _desk.browser_search(query, browser)

        @reg.tool("run_command", "Run a macOS shell/terminal command (DANGEROUS — asks first, "
                  "opt-in via JARVIS_ALLOW_SHELL=1). args: command (str).", ActionType.RUN_COMMAND)
        def _run_command(command=""):
            return _desk.run_command(command)

        @reg.tool("browse", "Open a JS-heavy page in a real browser and read it. args: url (str).",
                  ActionType.NETWORK_FETCH)
        def _browse(url=""):
            try:
                from .connectors.browser import Browser, NeedsHuman
            except Exception as e:
                return ToolResult.failure(str(e))
            br = Browser()
            try:
                return ToolResult.success(br.read(url)[:4000])
            except NeedsHuman as e:
                # Human-only blocker → park it and get the user (§30).
                self.handoff.block(str(e), context={"url": url})
                return ToolResult.failure(f"needs you: {e} (I've flagged it for you)")
            except Exception as e:
                return ToolResult.failure(str(e))
            finally:
                br.close()

        # ---- Gmail via persistent Playwright profile (§39) ---------------
        @reg.tool("gmail_inbox", "Read visible Gmail inbox items using a persistent browser "
                  "profile. Args: limit (int). First run may ask you to log in.",
                  ActionType.NETWORK_FETCH)
        def _gmail_inbox(limit=10):
            try:
                from .connectors.email import GmailPlaywrightConnector
                conn = GmailPlaywrightConnector(self.dir / "browser" / "gmail-profile",
                                                headless=False)
                msgs = conn.inbox(limit=int(limit or 10))
                return ToolResult.success(
                    "\n".join(f"- from {m.sender}: {m.subject}" for m in msgs) or
                    "No visible Gmail messages found."
                )
            except Exception as e:
                return ToolResult.failure(str(e))

        @reg.tool("gmail_draft", "Create a Gmail draft in the persistent browser profile. "
                  "Args: to, subject, body. Does not send.",
                  ActionType.WRITE_SANDBOX)
        def _gmail_draft(to="", subject="", body=""):
            try:
                from .connectors.email import Draft, GmailPlaywrightConnector
                conn = GmailPlaywrightConnector(self.dir / "browser" / "gmail-profile",
                                                headless=False)
                conn.create_draft(Draft(to=to, subject=subject, body=body))
                return ToolResult.success("Gmail draft created/saved; I did not send it.")
            except Exception as e:
                return ToolResult.failure(str(e))

        @reg.tool("gmail_send", "Send an email through Gmail. Args: to, subject, body. "
                  "Irreversible: requires approval before sending.",
                  ActionType.SEND_MESSAGE)
        def _gmail_send(to="", subject="", body=""):
            try:
                from .connectors.email import Draft, GmailPlaywrightConnector
                conn = GmailPlaywrightConnector(self.dir / "browser" / "gmail-profile",
                                                headless=False)
                ok = conn.send(Draft(to=to, subject=subject, body=body))
                return ToolResult.success("email sent") if ok else ToolResult.failure("send failed")
            except Exception as e:
                return ToolResult.failure(str(e))

    # ---- request handling (M1/M2/M3) -------------------------------------

    def handle(self, request: str, speak=None) -> str:
        """Handle a local voice/chat request, serializing access to the shared runtime."""
        with self._request_lock:
            return self._handle(request, speak=speak)

    def handle_from_telegram(self, request: str, speak=None) -> str:
        """Handle an inbound Telegram request without allowing remote irreversible actions.

        Telegram remains useful for questions, status, and read-only work while voice is
        running. Actions that require human approval are reported back as pending rather than
        trying to consume the active microphone from a background thread.
        """
        with self._request_lock:
            original_approver = self.approval._approver
            requested = []

            def deny_remote(action, _risk):
                requested.append(action)
                return False

            self.approval.set_approver(deny_remote)
            try:
                output = self._handle(request, speak=speak)
            finally:
                self.approval.set_approver(original_approver)
            if requested:
                action = requested[0]
                return ("I need your approval at Jarvis before I can do that. "
                        f"I did not perform: {action.summary}")
            return output

    def _handle(self, request: str, speak=None) -> str:
        """Route a request to the right mode and return the final answer text.

        `speak(chunk)` is how output is emitted — print for the CLI, a TTS sink for voice.
        M1 (chat) goes through the brain (memory, persona, curiosity); M2/M3 run agents with
        tools, then the result is spoken and remembered.
        """
        emit = speak or (lambda _c: None)
        mode = route_mode(request)
        self.journal.record(action="route", summary=request, reasoning=f"mode={mode.value}")

        direct = self._direct_tool_request(request)
        if direct is not None:
            emit(direct)
            self._remember(request, direct)
            return direct

        if mode is Mode.M1_DIRECT:
            if self.brain is not None:
                return self.brain.handle_turn(request, speak=emit)
            from .llm.adapter import Message
            resp = self.adapter.chat([Message("user", request)])
            emit(resp.text)
            return resp.text

        if mode is Mode.M2_AGENT:
            agent = Agent(self.adapter, self.registry, role="Jarvis's task agent")
            res = agent.run(request)
            out = res.output if res.ok else f"I couldn't finish that: {res.error}"
            emit(out)
            self._remember(request, out)
            return out

        # M3 — big, multi-step. If background is on, run it in a worker thread and keep
        # talking; Jarvis announces the result when done (§9). Else run inline.
        if self.background:
            label = request if len(request) < 60 else request[:57] + "…"
            self.task_queue.enqueue("agent_task", {"request": request, "label": label})
            # The worker thread is started once by the long-running session (voice/chat).
            ack = f"On it — I'll let you know when I've finished that. (Working on: {label})"
            emit(ack)
            self.journal.record(action="background_task", summary=label,
                                reasoning="dispatched to background worker")
            return ack

        state = self._make_orchestrator().run(request)
        out = state.result or "(no result)"
        emit(out)
        self._remember(request, out)
        return out

    def _direct_tool_request(self, request: str) -> str | None:
        """Deterministic shortcuts for common smoke-test/action phrases.

        The generic agent can still call these tools, but obvious status/action commands should
        not depend on the model choosing the exact tool name or accurately describing itself.
        """
        text = (request or "").lower()
        if re.search(r"\b(?:which|what)\s+model\b", text) or "model you are using" in text:
            return f"I am currently using {self.adapter.name}."
        command_match = re.match(
            r"\s*(?:run|execute)\s+(?:the\s+)?command\s+(.+?)\s*$",
            request or "",
            re.IGNORECASE,
        )
        if command_match:
            command = command_match.group(1)
            res = self.registry.execute("run_command", command=command)
            return str(res.output) if res.ok else f"I couldn't run the command: {res.error}"
        if "gmail" in text and "inbox" in text and any(w in text for w in ("read", "check", "latest", "show")):
            res = self.registry.execute("gmail_inbox", limit=10)
            return str(res.output) if res.ok else f"I couldn't read Gmail: {res.error}"
        if ("draft" in text or "create a draft" in text) and ("email" in text or "gmail" in text):
            parsed = self._parse_email_draft_request(request)
            if not parsed.get("to"):
                return "I need the recipient email address to create a Gmail draft."
            res = self.registry.execute("gmail_draft", **parsed)
            return str(res.output) if res.ok else f"I couldn't create the Gmail draft: {res.error}"
        return None

    @staticmethod
    def _parse_email_draft_request(request: str) -> dict:
        text = request or ""
        to_match = re.search(r"\b(?:send\s+to|to)\s+([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
                             text, re.IGNORECASE)
        subject_match = re.search(r"\bsubject\s+(.+?)(?:\s+and\s+body\b|\s+with\s+body\b|$)",
                                  text, re.IGNORECASE)
        body_match = re.search(r"\bbody\s+(.+)$", text, re.IGNORECASE)

        purpose = text
        if to_match:
            purpose = text[:to_match.start()].strip()
        subject = subject_match.group(1).strip(" .") if subject_match else ""
        body = body_match.group(1).strip() if body_match else ""

        if not subject and "leave" in text.lower():
            subject = "Request for 2 Days Leave" if "2" in text or "two" in text.lower() else "Leave Request"
        if not body and "leave" in text.lower():
            days = "2 days" if "2" in text or "two" in text.lower() else "a few days"
            body = (
                "Hi,\n\n"
                f"I would like to request {days} of leave. Please let me know if you need any "
                "additional details from my side.\n\n"
                "Regards,\n"
                "Abhijeet"
            )
        if not subject:
            subject = "Draft Email"
        if not body:
            body = purpose or "Hi,\n\nPlease see this draft email.\n\nRegards,\nAbhijeet"

        return {"to": to_match.group(1) if to_match else "", "subject": subject, "body": body}

    # ---- background execution (§9) ---------------------------------------

    def start_background(self) -> None:
        """Start the worker thread that runs queued agent tasks while you keep talking."""
        if self._bg_started:
            return
        self._bg_started = True
        import threading
        import time

        def _loop():
            while True:
                try:
                    job = self.worker.run_one()
                except Exception:
                    job = None
                if job is None:
                    time.sleep(1.5)  # idle — nothing queued

        threading.Thread(target=_loop, name="jarvis-worker", daemon=True).start()

    def _run_agent_job(self, job):
        """Worker handler: run a long agent task off the main thread (§9)."""
        request = job.payload.get("request", "")
        try:
            state = self._make_orchestrator().run(request)
            result = state.result or "(no result)"
            return JobStatus.DONE, result
        except Exception as e:  # graceful failure (§21)
            return JobStatus.FAILED, f"{type(e).__name__}: {e}"

    def _make_orchestrator(self):
        """LangGraph orchestrator if installed + enabled, else the native one."""
        import os

        runs = self.dir / "memory" / "runs"
        if os.environ.get("JARVIS_USE_LANGGRAPH", "1") != "0":
            try:
                from .agents.graph import LangGraphOrchestrator
                return LangGraphOrchestrator(self.adapter, self.registry,
                                             checkpoint_dir=runs, journal=self.journal)
            except Exception:
                pass  # langgraph not installed → fall back
        return Orchestrator(self.adapter, self.registry, checkpoint_dir=runs, journal=self.journal)

    def _remember(self, request: str, output: str) -> None:
        """Write agent tasks to long-term memory so voice/chat recall them later (§8)."""
        if self.brain is None:
            return
        try:
            name = self.brain.user_name or "The user"
            self.brain.memory.add(f"{name} asked: {request}")
            self.brain.memory.add(f"Jarvis handled it: {output[:300]}")
        except Exception:
            pass
