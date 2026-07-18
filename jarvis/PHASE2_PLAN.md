# JARVIS — Phase 2 Build Plan (Agents & Actions)
*From "talks" to "does". Spec: §6, §7, §9, §11, §16, §21, §26, §30, §38, §39, §40; workflow §2A.*

## Goal
Jarvis can take on a real task, plan it, execute it through tools/agents, ask before
anything irreversible, hand off to you when it hits a human-only blocker, and manage your
day (reminders, calendar, email drafts, briefings) — all recorded with reasoning.

## Modules (build order)

1. **Tools + Actions (`jarvis/tools/`)** — a `Tool` = a named callable with a typed
   `ActionType` (§11). A `ToolRegistry` holds them. Executing a tool routes through the
   Phase 0 approval engine: reversible → run; irreversible → ask. This is the safe hands.

2. **Agent framework (`jarvis/agents/`)** — the §2A workflow:
   - `Agent` — a scoped ReAct loop (think → tool → observe) with a tool subset + budget (M2).
   - `Orchestrator` — supervisor (M3): decompose a goal, **create sub-agents at runtime**,
     run them, **critic-review** each output, merge. Sub-agents never talk directly.
   - `route_mode()` — pick M1 (direct chat) / M2 (single agent) / M3 (multi-agent).
   - `AgentState` — the shared, checkpointed contract; `Interrupt` for human-in-the-loop.

3. **Task queue (`jarvis/tasks/`)** — durable SQLite-backed job queue + worker so work runs
   in the background and survives restarts (§9), publishing status.

4. **Decision journal + staging (`jarvis/journal/`)** — every decision/action logged with
   *what, why, alternatives, confidence, outcome* (§26); staging store for speculative work
   (promote or discard).

5. **Graceful failure + handoff (`jarvis/handoff/`)** — on a human-only blocker (captcha,
   login, a decision), park the task in a "waiting on you" queue, detect presence, notify
   locally or by phone, resume from checkpoint (§21, §30). Includes a notifier interface with
   a **Telegram** backend (§10) and a test stub.

6. **Daily-life tools (`jarvis/connectors/`)** —
   - **Calendar/reminders (§38):** local store + due-time scheduler + reminder tool.
   - **Email/messaging (§39):** connector interface; read/summarize/draft; **send is
     approval-gated**; local "outbox" stub now, real Gmail/IMAP drops in later.
   - **Daily briefing (§40):** assembles calendar + waiting-queue + overnight notes.

7. **Wire-up** — CLI (`agent`, `remind`, `brief`, `tasks`), voice-loop integration so spoken
   requests can create reminders / trigger agents; README; run the full suite.

## Test strategy
Everything runs and is tested with the **MockAdapter** and **stub tools/notifiers** — no
network, no accounts. Real connectors (Gmail, Telegram, browser) are seams that plug into
the same interfaces later.

## Honest scope notes
- **LangGraph:** the architecture named it, but we implement its *pattern* natively
  (supervisor + interrupts + checkpointed state) over our model-agnostic `ModelAdapter`.
  This keeps Phase 2 dependency-light, testable offline, and model-swappable. LangGraph can
  be adopted later without changing the agent contract.
- **Real Gmail / Telegram / browser actions** need your accounts/tokens; those are wired as
  connectors behind stable interfaces. The framework, safety gates, and local tools are
  fully built and tested now.
