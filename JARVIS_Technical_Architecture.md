# JARVIS — Technical Architecture & Solution Design
### Companion to *JARVIS_Requirements.md* (v2, 42 requirements)
*Prepared as a solution-architecture reference. Research-grounded to July 2026. No code — design only.*

---

## 0. How to read this document

This is the engineering blueprint for the 42-point requirements spec. It has three parts:

1. **System architecture** — the big picture: layers, the always-on brain loop, process model, data layout, and cross-cutting concerns (security, safety, storage).
2. **Master tech stack** — every chosen technology with the reason it was picked over alternatives, current as of 2026.
3. **The 42 requirements, one by one** — for each: *what it does → how it works technically → the tech → data flow → risks & mitigations.*

Design principles that recur throughout:

- **Model-agnostic core.** Everything is built so the "brain" (OpenAI now → local later) is a swappable adapter. Nothing downstream knows or cares which model answers.
- **Everything is a message on a bus.** Voice, tasks, memory writes, notifications, and agent results are events on an internal event bus. This is what lets it be always-on, background, and interruptible.
- **Safety is structural, not advisory.** Approval gates, the sandbox boundary, git rollback, and the immutable core are enforced by code paths, not by asking the model nicely.
- **Local-first, degrade gracefully.** Every subsystem has a local implementation; cloud is optional and gated.

---

## 1. System Architecture

### 1.1 Layered view

```
┌─────────────────────────────────────────────────────────────────────┐
│  IMMUTABLE CORE (read-only to the AI) — §23                          │
│  kill switch · approval engine · sandbox guard · policy enforcement  │
└─────────────────────────────────────────────────────────────────────┘
            ▲ enforces                              ▲ enforces
┌───────────────────────────┐        ┌──────────────────────────────────┐
│  ORCHESTRATOR / BRAIN LOOP │◄──────►│  EVENT BUS (async pub/sub)        │
│  §13 — the always-on control│        │  voice · tasks · memory · alerts │
└───────────────────────────┘        └──────────────────────────────────┘
     ▲          ▲          ▲          ▲            ▲            ▲
┌────────┐ ┌─────────┐ ┌────────┐ ┌────────┐ ┌──────────┐ ┌────────────┐
│ VOICE  │ │ MODEL   │ │ MEMORY │ │ AGENTS │ │ SKILLS/  │ │ BACKGROUND │
│ I/O    │ │ ADAPTER │ │ SYSTEM │ │ +TASKS │ │ TOOLS    │ │ BRAIN      │
│ §3-5,  │ │ §1,§20  │ │ §8,§42 │ │ §6,§7, │ │ §22,§31, │ │ §25,§29    │
│ 18,19  │ │         │ │        │ │ §21,30 │ │ §32      │ │            │
└────────┘ └─────────┘ └────────┘ └────────┘ └──────────┘ └────────────┘
     ▲                                  ▲                       ▲
┌────────────┐                   ┌─────────────┐        ┌──────────────┐
│ DEVICE/OS  │                   │ CONNECTORS  │        │ MOBILE BRIDGE│
│ §28,§36    │                   │ mail,cal,web│        │ §10          │
│            │                   │ §38,§39,§6  │        │              │
└────────────┘                   └─────────────┘        └──────────────┘

  Cross-cutting: Vault §14 · Audit/Journal §16,§26 · Sandbox+Git §17 · Config/Setup §41
```

### 1.2 Process & runtime model

- **Language/runtime:** Python 3.12 as the primary orchestration language (best ecosystem for STT/TTS/ML/agent libraries), with performance-critical audio paths using native binaries (whisper.cpp). Node.js only where a JS library is superior (e.g. some browser tooling).
- **Process supervisor:** the assistant runs as a **long-lived daemon** managed by the OS (§2). A lightweight **watchdog** process monitors the main process and restarts on crash — the watchdog is deliberately tiny and lives in the immutable core so a bug in the main app can never disable recovery.
- **Concurrency:** `asyncio` event loop for the brain loop and I/O; a **worker pool** (separate processes) for CPU-heavy jobs (STT, TTS, local LLM inference, sub-agents) so voice never blocks on a long task.
- **Internal event bus:** in-process async pub/sub for the single-machine build (e.g. an `asyncio`-based broker), with the option to back it by **Redis Streams** if durability across restarts is needed for the task queue (§9). Redis also doubles as the durable task queue and short-term cache.
- **State store:** **SQLite** (via WAL mode) is the system of record for structured data — tasks, memory metadata, journal, device inventory, schedule. It's local, serverless, transactional, and trivially backed up.

### 1.3 On-disk layout (all under the user's chosen root)

```
jarvis/
├── core/                 # IMMUTABLE — AI cannot write here (§23). Kill switch, approval engine, guard.
├── config/               # settings, enrolled voiceprint ref, persona, preferences (§41)
├── vault/                # encrypted secrets (§14)
├── sandbox/              # AI's full-read/write playground, a git repo (§17)
│   └── tools/            # self-built tools (§22,§32)
├── skills/               # skill library (§31), git-tracked
├── memory/
│   ├── jarvis.db         # SQLite: facts, tiers, graph edges, journal (§8,§26)
│   ├── vectors/          # vector index (§8 semantic recall)
│   └── staging/          # speculative work, promoted-or-deleted (§26)
├── models/               # local model weights (LLM, STT, TTS, wakeword, speaker)
├── logs/                 # audit trail (§16)
└── backups/              # encrypted memory backups (§42)
```

### 1.4 Cross-cutting: the security & safety spine

Four mechanisms wrap every action, evaluated **before** anything executes:

1. **Sandbox guard (§17):** a filesystem policy layer. Writes are allowed only under `sandbox/`; everything else is read-only unless a scoped, approved exception exists. Enforced by wrapping all file I/O through one guarded module — the model never gets raw filesystem handles.
2. **Approval engine (§11):** classifies each intended action as *reversible* or *irreversible*. Irreversible → block and request human approval (local voice or phone). Reversible → proceed.
3. **Audit + decision journal (§16, §26):** every action and decision is appended (with reasoning + confidence) to an append-only log before/after execution.
4. **Immutable core + kill switch (§23):** the guard, approval engine, and `"Jarvis, end yourself"` handler live in `core/`, which the AI has no write path to. Kill switch is wired to an OS-level signal that force-terminates all processes.

---

## 2. Master Tech Stack (2026-current)

| Subsystem | Chosen tech | Why this over alternatives |
|---|---|---|
| **Orchestration language** | Python 3.12 + asyncio | Richest STT/TTS/agent/ML ecosystem; async fits the always-on event loop. |
| **Model brain (dev)** | OpenAI API (GPT-class) via adapter | Fast iteration, strong tool-calling while building. |
| **Model brain (final, local)** | **Qwen3-7B** (8 GB VRAM) via **Ollama**; **Gemma-4-27B** for 24 GB; Llama-3.3-70B if 48 GB+ | Qwen3 has native tool-calling in its chat template and is the 2026 sweet spot for reliable local function calls; Ollama = simplest local serving, vLLM if throughput needed. |
| **Wake word** | **openWakeWord** (ONNX) | Free, open, custom-trainable "Hey Jarvis"; Picovoice Porcupine is the paid alternative. |
| **Speaker verification** | **SpeechBrain ECAPA-TDNN** (or Resemblyzer) | Free, on-device voiceprint match; Picovoice Eagle is the paid on-device option. |
| **STT** | **whisper.cpp** (Mac: Metal + CoreML/ANE) / **faster-whisper** (NVIDIA CUDA) | Same Whisper accuracy; whisper.cpp is the cross-platform/Mac real-time winner, faster-whisper wins on CUDA batch. Local latency 50–300 ms. |
| **TTS** | **Kokoro-82M** (Apache-2.0, ~2–3 GB) as the Jarvis voice; **Piper** for CPU-only fallback; **XTTS v2** if voice-*cloning* a specific Jarvis timbre | Kokoro is the 2026 quality/speed default (near-XTTS quality, sub-0.3 s); Piper for <1 GB embedded; XTTS for 6-second zero-shot cloning. |
| **Memory — structured** | SQLite (WAL) | Local, transactional system of record; holds tiers, recall counts, graph edges, journal. |
| **Memory — semantic** | **Qdrant** (embedded/local) or Chroma | Fast local vector recall for cue-based re-fetch. Qdrant scales better; Chroma simplest. |
| **Memory — graph** | **Kuzu** (embedded graph DB) / Graphiti patterns | Embedded, no server; models the knowledge-graph links between memories. |
| **Memory — architecture pattern** | Custom tiered store inspired by **Letta** (OS-style paging) + **Mem0** extraction | Letta's context↔storage paging is the closest existing analog to conscious/subconscious/unconscious tiers (§8). |
| **Agent orchestration** | **LangGraph** | Node/edge graphs with **durable checkpointing + human-in-the-loop interrupts** — exactly what approval gates (§11) and blocked-task handoff (§30) need. CrewAI considered for role-based sub-agents. |
| **Browser automation** | **Playwright** + an LLM-driven layer (browser-use pattern) | Robust cross-browser control; LLM layer handles dynamic pages. |
| **Desktop/OS control** | OS-native APIs + CLI (AppleScript/`osascript`, PowerShell, `nmcli`/`bluetoothctl`) | Direct, scriptable control of WiFi/Bluetooth/audio/apps (§28). |
| **Telephony (built on demand)** | **Vapi / Retell / Twilio** via §32 tool-builder | User-funded, added only when a calling task appears — not pre-installed. |
| **Notifications / mobile (2-way)** | **Telegram Bot API** (confirmed primary); ntfy.sh as fallback | **Completely free** — no per-message or monthly cost; free tier (30 msg/s, 1 msg/s per chat, 50 MB files) is far beyond one-user needs. Rich 2-way: alerts out, commands + tap approvals back (§10). Bot created via @BotFather; token in vault (§14). ntfy.sh kept as a no-chat-app fallback. |
| **Secrets vault** | age/libsodium-encrypted store, OS keychain for master key | Strong local encryption; master key in Keychain/Credential Manager. |
| **Version control / rollback** | **git** (local) with auto-commit hooks | Per-change commits = free undo for everything in the sandbox (§17). |
| **Observability / tracing** | **LangSmith** (dev phase) → **Langfuse self-hosted** (local phase) | Trace every LLM call, tool call, agent step, and retrieval end-to-end. LangSmith is native to LangGraph (near-zero setup) but is cloud — fine while on OpenAI; once fully local, Langfuse gives the same tracing self-hosted so no data leaves the PC. |
| **Tool protocol** | **MCP (Model Context Protocol)** via FastMCP + local registry | Every tool (built-in or self-built) is an MCP server — model-agnostic, directly callable by any LLM, and the whole third-party MCP ecosystem plugs into the same registry (§2A.6). |
| **Scheduler** | APScheduler (+ SQLite jobstore) | Cron-like local scheduling for reminders, nightly consolidation, briefings. |
| **Autostart** | launchd (mac) / systemd (Linux) / Task Scheduler (Win) | Native, reliable boot + keep-alive. |

---

## 2A. Agent Workflow Architecture — What Kind of System Is This?

**Short answer: it is a *hybrid* — a single-agent fast path for conversation, escalating to a supervisor-led multi-agent workflow for real work, with explicit back-and-forth loops at every level.** Defining this precisely, because it drives everything in Section 3.

### 2A.1 The three execution modes

Every request is routed into exactly one of three modes by the orchestrator (§13):

| Mode | When | Shape |
|---|---|---|
| **M1 — Direct response** | Chat, questions, quick facts, personality/friend talk (§33/§34) | Single model call with memory context. No agents. Latency-optimized (§18). |
| **M2 — Single-agent loop** | One well-defined task ("rename these files", "draft this email") | One agent running a **ReAct-style loop**: *think → act (tool) → observe → think…* until done. |
| **M3 — Multi-agent workflow** | Complex/decomposable goals ("research X and build me a report", "plan the trip and book what's refundable") | **Supervisor pattern**: an orchestrator agent decomposes, delegates to specialist sub-agents, and merges. |

Mode selection is itself a routed decision (complexity router, §20). Most voice interactions are M1 — that's what keeps it feeling instant. M3 is reserved for genuinely decomposable work, because multi-agent always costs more latency and tokens.

### 2A.2 The multi-agent topology (M3) — supervisor, not swarm

This is a **hierarchical supervisor architecture**, deliberately *not* a free-for-all agent swarm:

```
                    ┌─────────────────┐
                    │   SUPERVISOR     │  decomposes goal, owns the plan,
                    │  (orchestrator   │  assigns sub-tasks, merges results,
                    │     agent)       │  is the ONLY agent that talks to you
                    └────────┬─────────┘
          ┌────────────┬─────┴──────┬─────────────┐
          ▼            ▼            ▼             ▼
   ┌────────────┐┌────────────┐┌────────────┐┌────────────┐
   │ RESEARCHER ││  EXECUTOR  ││   CODER    ││  (dynamic:  │
   │ web/memory ││ browser/OS ││ tools/skill││ per-skill   │
   │ retrieval  ││  actions   ││  building  ││ specialists)│
   └─────┬──────┘└─────┬──────┘└─────┬──────┘└─────┬──────┘
         └─────────────┴──────┬──────┴──────────────┘
                              ▼
                    ┌─────────────────┐
                    │  CRITIC/VERIFIER │  checks outputs before merge:
                    │     (agent)      │  grounded? complete? safe? (§24)
                    └─────────────────┘
```

- **Dynamic sub-agent creation.** The specialists in the diagram are archetypes, not a fixed roster — the supervisor **creates sub-agents at runtime**: for each sub-task it *writes the agent's system prompt* (role, goal, constraints, output format), *selects its tool subset* from the MCP registry (§2A.6), *sets its budget* (max steps/time), and spawns it in a worker. An agent definition that proves reusable is saved as a template in `skills/agents/` for next time.
- **Output review before acceptance.** A sub-agent's result is never merged raw. It passes through: (1) **schema check** — does the output match the format the supervisor asked for; (2) **critic review** (§24) — grounded, complete, safe; (3) **supervisor acceptance** — does it actually advance the plan. Fail → re-delegate with the critique attached (max 2 rounds); still failing → escalate to you (§30). Accepted outputs merge into shared state with their citations and confidence carried along.
- **Sub-agents never talk to each other directly.** All coordination goes through the supervisor via **shared graph state** (a typed state object checkpointed by LangGraph). This kills the classic multi-agent failure mode of agents confusing each other in open-ended chatter.
- **Sub-agents are scoped:** each gets a focused prompt, only the tools it needs, and a budget (max steps, max time). A researcher can't touch the browser-executor's tools and vice versa.
- **Parallelism:** independent sub-tasks fan out to parallel workers (§7); dependent ones are sequenced by the supervisor's plan DAG.
- **The critic is mandatory for consequential output.** Nothing merges into a final answer or action without the verify node (grounding + completeness + safety), per §24.

### 2A.3 Back-and-forth: how "thinking" actually iterates

There are **four distinct feedback loops**, each with a defined trigger and exit:

1. **Inner ReAct loop (within any agent):** *think → tool call → observe result → think again.* Exit: task done, or step-budget hit → report partial + reason (§21). This is where moment-to-moment "thinking with its hands" happens.
2. **Plan revision loop (supervisor level):** after each sub-agent returns, the supervisor re-evaluates the plan — *plan → delegate → observe results → re-plan if reality diverged.* Exit: goal met, or plan judged infeasible → graceful failure (§21). This is the back-and-forth *between* planning and doing.
3. **Critique loop (quality):** critic rejects a sub-agent's output with reasons → the supervisor re-delegates with the critique attached (max 2 rounds to prevent ping-pong). Exit: pass, or escalate to you. This is agent-to-agent back-and-forth, but always refereed by the supervisor.
4. **Human-in-the-loop interrupts (you):** at any depth, an irreversible action (§11), a blocker (§30), or low-confidence-high-stakes (§24) fires a LangGraph `interrupt()` — the **entire graph checkpoints and pauses** at that node, you answer (voice or phone), and execution **resumes from the exact checkpoint**, not from scratch. This is what makes the back-and-forth *with you* cheap and lossless.

**Budgets everywhere:** every loop has a hard iteration/time cap. Loops without exits are how agent systems melt down; here, hitting a cap is itself a defined exit (report + ask), never a silent spin.

### 2A.4 State, memory, and hand-offs between agents

- **Shared state object:** one typed state (goal, plan, sub-results, citations, confidence, pending approvals) flows through the graph; it *is* the inter-agent contract, checkpointed at every node transition (SQLite-backed LangGraph checkpointer).
- **Memory access is tiered by role:** the supervisor and researcher read from memory (§8); only designated writers commit new memories post-merge — sub-agents don't pollute long-term memory mid-task. Task-local scratch lives in the state object and dies with the task (unless promoted).
- **Voice stays responsive during M3:** the whole workflow runs on the worker pool (§1.2); the brain loop remains free, so you can talk to Jarvis *about* the running task ("how's it going?" reads the live state/checkpoints) or interrupt it — conversation and work are concurrent, not blocking.

### 2A.5 Observability — LangSmith tracing at every component

Every AI-touching step emits a **trace span**, so any output can be debugged back to its inputs:

- **What's traced:** STT final text → memory retrieval (query, hits, scores) → prompt assembly (persona + context + skill) → every model call (tokens in/out, latency, model used) → every tool/agent call (args, result, errors) → critic verdicts → final response → TTS text. Multi-agent runs appear as a **single nested trace tree** (supervisor → sub-agents → tools), so a bad merge is traceable to the exact sub-agent step that caused it.
- **Feedback wiring:** your explicit reactions ("no, that's wrong") and §26 journal outcomes are attached to traces as feedback scores — building a dataset for evaluating prompt/skill changes before deploying them (§22/§27 regression runs against traced examples).
- **Dev vs local phase:** **LangSmith** during the OpenAI phase (native to LangGraph, zero-friction). At the go-local milestone (Phase 5), switch to **self-hosted Langfuse** — same span model, OTel-compatible, runs on your machine, so tracing survives the privacy cutover. The tracing wrapper is written against a thin interface so this swap, like the model swap (§1), is config, not rewrite.
- **Relationship to §16/§26:** the audit log answers *"what did it do"* (compliance), the decision journal answers *"why"* (reasoning), traces answer *"how, exactly, mechanically"* (debugging). Three layers, one correlation ID per action tying them together.

### 2A.6 Every tool is an MCP server

All tools — built-in and self-built (§22/§32) — are exposed via the **Model Context Protocol (MCP)**, the open standard for LLM↔tool communication. This is a deliberate architectural choice, not a convenience:

- **When Jarvis builds a tool, it builds it *as* an MCP server:** the §22 tool-generator's output template is an MCP server (Python `FastMCP`) exposing the tool's functions with typed schemas, not a bare script. Generated alongside: the schema, a test, and a manifest entry.
- **One MCP registry, local-first:** a lightweight **MCP host/registry** inside Jarvis manages all servers — launching them on demand (stdio for local tools, HTTP/SSE for service-backed ones like the Twilio caller), health-checking, and exposing a unified tool catalog. The supervisor assembles each sub-agent's toolset by picking entries from this registry (§2A.2).
- **Why MCP instead of framework-native tools:**
  1. **Model-agnostic by construction** — OpenAI now, Qwen3 later, any future model: they all speak MCP through the adapter, so the tool library survives every model swap (§1) untouched.
  2. **Direct LLM usability** — any MCP-compatible client (including Jarvis's own sub-agents, or even external apps you point at it) can call the tools without glue code.
  3. **Ecosystem for free** — thousands of existing third-party MCP servers (calendar, mail, Slack, GitHub…) can be plugged into the same registry via §32's guided setup, instead of hand-building every connector.
- **Safety unchanged:** MCP calls route through the same choke points — sandbox guard (§17), approval engine (§11), audit (§16), and tracing (§2A.5). A tool being an open-standard server does not exempt it from the spine; the registry only launches servers listed in the approved manifest.

---

## 3. The 42 Requirements — Solution Design, One by One

*Each entry: **What** it does · **How** it works · **Tech** · **Data flow / integration** · **Risks & mitigations.***

### §1 — Core Intelligence (OpenAI now, local later)
- **What:** a swappable "brain" behind one interface.
- **How:** a `ModelAdapter` interface with methods like `chat()`, `stream()`, `tool_call()`, `embed()`. Concrete adapters: `OpenAIAdapter` (dev) and `OllamaAdapter` (final). A router picks the adapter from config; the rest of the system only ever sees the interface. Prompt templates and tool schemas are model-neutral (JSON tool-calling spec) so no rewrite is needed on switch.
- **Tech:** OpenAI API → **Qwen3-7B via Ollama** (native tool-calling); vLLM if throughput matters; **Gemma-4-27B** on 24 GB.
- **Data flow:** brain loop (§13) → ModelAdapter → tokens streamed back to TTS (§18) and memory (§8).
- **Risks:** local model weaker at reasoning → mitigated by the reasoning tier (§20) and keeping tool schemas strict so the model orchestrates rather than "thinks hard." Adapter drift → one conformance test suite both adapters must pass.

### §2 — Auto-start on boot
- **What:** launches on startup, self-heals, idles cheap.
- **How:** OS service manager starts the **watchdog**, which spawns and supervises the main daemon; on crash it restarts with backoff. Idle state loads only the wake-word model (tens of MB) and keeps heavy models lazy-loaded until first use.
- **Tech:** launchd / systemd / Task Scheduler; watchdog is a minimal script in `core/`.
- **Data flow:** boot → watchdog → daemon → event bus online → standby listening (§3).
- **Risks:** boot-loop on persistent crash → watchdog caps restart rate and, after N fails, boots into "safe mode" (voice + kill switch only) and notifies phone (§10).

### §3 — Voice listening + speaker verification
- **What:** wakes on "Hey Jarvis," obeys only the owner.
- **How:** continuous mic stream → **openWakeWord** detects the phrase on-device (low CPU) → on trigger, the next utterance is embedded and compared to the enrolled voiceprint via **cosine similarity**; below threshold = ignored. **Barge-in** = a VAD monitor on the mic during TTS playback; detected speech ducks/stops playback instantly.
- **Tech:** openWakeWord (ONNX) + **SpeechBrain ECAPA-TDNN** speaker embeddings; WebRTC VAD for barge-in.
- **Data flow:** mic → wakeword → speaker check → (pass) STT §4 → brain loop.
- **Risks:** false accepts/rejects → tunable threshold + short "confirm it's you" fallback; recordings of the owner could spoof → optional liveness/challenge phrase for high-risk actions.

### §4 — Local STT
- **What:** offline speech-to-text.
- **How:** post-wakeword audio is streamed through a VAD-segmented pipeline to Whisper; partial hypotheses stream out for low latency, finalized on end-of-speech.
- **Tech:** **whisper.cpp** (Mac: Metal + CoreML on the Neural Engine, 3×+ faster) / **faster-whisper** (CUDA). `small`/`medium` for latency, `large-v3` when accuracy matters.
- **Data flow:** audio frames → STT → text → intent/brain loop; text also to journal.
- **Risks:** accents/jargon errors → domain vocabulary hints + the confirmation step for critical actions (§35).

### §5 — Local Jarvis-style TTS
- **What:** natural spoken replies, free.
- **How:** the brain streams text sentence-by-sentence into the TTS engine, which emits audio for sentence 1 while sentence 2 generates (overlap = low perceived latency).
- **Tech:** **Kokoro-82M** as the default voice (Apache-2.0, ~40 ms–0.3 s); **Piper** CPU-only fallback; **XTTS v2** if cloning a bespoke Jarvis timbre from ~6 s of reference.
- **Data flow:** brain tokens → sentence chunker → TTS → audio out (interruptible by §3 barge-in).
- **Risks:** flat prosody (Piper) → prefer Kokoro; cloning quality → XTTS with a clean reference sample.

### §6 — Autonomous task execution + fallback planning
- **What:** does the task; if no built-in way, plans one; if no capability, builds one.
- **How:** an intent classifier routes a request to (a) a known skill/tool, (b) a **planner** that decomposes into steps and drives browser/OS actions, or (c) capability acquisition (§32). The planner is a LangGraph graph: *plan → act → observe → re-plan* with a step budget; failures loop back to re-plan.
- **Tech:** LangGraph planner; Playwright + browser-use for web; OS control for desktop.
- **Data flow:** request → planner → tool/agent calls → result → memory (procedural, §8) + journal.
- **Risks:** infinite loops / runaway cost → step + time budgets, and every irreversible step hits §11.

### §7 — Sub-agent orchestration
- **What:** splits complex goals across focused agents, merges results.
- **How:** an **orchestrator** node decomposes the goal, spawns sub-agents (each = a scoped prompt + tool subset), runs independent ones **in parallel** in worker processes, then a **merge/verify** node reconciles outputs (and can spawn a critic agent to check them).
- **Tech:** LangGraph (supervisor pattern) or CrewAI role-crews; worker-process pool for isolation. **Full topology, loop definitions, and state contract: Section 2A.**
- **Data flow:** goal → orchestrator → N sub-agents (sandboxed) → critic → merge → single result.
- **Risks:** conflicting outputs / hallucinated merges → explicit verify node + grounding (§24); resource spikes → concurrency cap tied to §16 throttling.

### §8 — Brain-like memory (conscious / subconscious / unconscious)
- **What:** tiered memory that moves by recall frequency, consolidates nightly, and re-fetches on cue.
- **How:** every memory row carries `tier`, `recall_count`, `last_recalled`, `salience`. **Working set** (conscious) = what's loaded into the model context now. **Warm** (subconscious) = high recall/recent, kept in a fast index. **Cold** (unconscious) = compressed archive. A scheduled **consolidation job** (nightly, §25) recomputes tiers: promote frequently-recalled, decay the rest along a forgetting curve, **extract facts** from the day's episodes, and **link** them into the knowledge graph. **Retrieval** = a cue (query embedding + graph neighborhood) pulls candidates from warm→cold; on recall, `recall_count`++ and the item is **reconsolidated** (re-embedded/updated) — recall strengthens and can revise it. This mirrors hippocampus→neocortex systems consolidation and retrieval-induced reconsolidation.
- **Tech:** SQLite (metadata, tiers, edges) + **Qdrant** (vectors) + **Kuzu** (graph); architecture patterned on **Letta** (OS-style paging = the tier mechanism) and **Mem0** (fact-extraction pipeline). Memory types (episodic/semantic/procedural) are tags spanning tiers.
- **Data flow:** conversation/task → episodic write → nightly consolidation → semantic/procedural + graph links → cue-based recall into context.
- **Risks:** unbounded growth → cold-tier compression + salience-based pruning of true noise (never user data without §11); wrong "forgetting" → nothing is deleted, only demoted, so it's always recoverable; retrieval misses → hybrid vector+graph+keyword recall.

### §9 — Background execution + conversational updates
- **What:** tasks run in the background; it talks like an assistant.
- **How:** requests become **jobs** on a durable queue; workers execute; status events publish to the bus and are voiced/notified conversationally. The brain loop stays responsive because work is off-loop.
- **Tech:** Redis Streams (or SQLite-backed) task queue; APScheduler for timed jobs; state machine per job (queued→running→blocked→done/failed).
- **Data flow:** request → job → worker → status events → voice/phone (§10) + journal.
- **Risks:** lost jobs on restart → durable queue survives reboot (§27 preserves state); noisy updates → batching + "only interrupt for important" rule.

### §10 — Mobile notifications + remote control (2-way)
- **What:** alerts you on phone when away; you send commands/approvals back.
- **How:** a **presence detector** (keyboard/mouse idle time, mic activity, optionally device on network) decides local-vs-phone routing. Outbound alerts and inbound commands flow over a bidirectional channel; inbound messages are authenticated (chat ID allowlist) and passed through the same brain loop as voice, then re-secured by §11 for anything risky.
- **Tech:** **ntfy.sh** (self-hostable, priority + action buttons) or **Telegram Bot API** (rich 2-way). Approvals rendered as tap buttons.
- **Data flow:** event → presence check → phone push; phone reply → auth → brain loop → action.
- **Risks:** channel compromise → allowlist + the phone can *approve* but high-value irreversible actions can require a second factor; message reliability → delivery receipts + retry.

### §11 — Safety: reversibility check before every action
- **What:** irreversible actions stop and ask first.
- **How:** the **approval engine** wraps the action dispatcher. Each proposed action is classified: sandbox file change / read = reversible (git can undo, §17) → auto-proceed; money, send, post, delete-outside-sandbox, self-core-change = irreversible → **hard interrupt** (LangGraph human-in-the-loop) that pauses the graph, surfaces *what + why irreversible*, and resumes only on explicit approval (voice §35 or phone §10).
- **Tech:** rule-based classifier + LLM check for ambiguous cases; LangGraph `interrupt()`; policy list in the immutable core.
- **Data flow:** action intent → classifier → (irreversible) approval request → wait → approve/deny → execute/abort → journal.
- **Risks:** misclassification → default to "ask" when uncertain; approval fatigue → scoped, remembered approvals for repeated low-risk patterns (never for money/deletes).

### §12 — Full PC + internet access
- **What:** read access to PC + web to research and act.
- **How:** a **connector layer** exposes web fetch/search, filesystem (read-anywhere / write-sandbox per §17), and OS info as tools. All access is logged (§16) and bounded by the sandbox guard and approval engine.
- **Tech:** HTTP client + search API/local crawler; guarded filesystem module; OS info via native APIs.
- **Data flow:** tool call → guard/approval → execute → result → memory/journal.
- **Risks:** unbounded web/data access → domain policy + rate limits; the *proactive* use of this lives in §25, not here.

### §13 — Central orchestrator / brain loop
- **What:** the always-on controller tying it all together.
- **How:** an async supervisor consuming the event bus. Canonical pipeline: **wake §3 → STT §4 → speaker check §3 → intent → memory recall §8 → model route §1 → plan/dispatch §6/§7 → approval §11 → execute → merge → TTS §5 / notify §10 → memory+journal write.** It's a state machine, so any step can interrupt (barge-in, kill switch, blocked task) without corrupting state.
- **Tech:** asyncio supervisor + LangGraph for the reasoning/act sub-graphs; event bus for decoupling.
- **Data flow:** it *is* the data flow — every subsystem plugs into it.
- **Risks:** single point of failure → watchdog (§2) restarts; deadlocks → per-stage timeouts and a supervisor heartbeat.

### §14 — Encrypted secrets & credential vault
- **What:** secure store for keys, passwords, logins.
- **How:** secrets encrypted at rest with a symmetric key; the **master key** is held in the OS keychain (not on disk in plaintext), loaded into memory at startup. Access is brokered — tools request a secret by name and the vault injects it at call time; the model never sees raw secrets in its context.
- **Tech:** libsodium/age encryption; macOS Keychain / Windows Credential Manager / libsecret; secret-injection wrapper.
- **Data flow:** startup unlock → in-memory keyring → tool asks by name → injected into request.
- **Risks:** memory scraping → minimize secret lifetime in memory; model leakage → secrets never enter prompts, only tool internals.

### §15 — Pause & mic mute
- **What:** soft, resumable pause of listening/actions.
- **How:** a "stop/pause" intent flips a global `paused` flag the brain loop checks between stages; in-flight reversible work suspends, irreversible work already needs approval anyway. Mic mute cuts the audio capture source. Distinct from the hard shutdown in §23.
- **Tech:** shared state flag on the event bus; audio source toggle.
- **Data flow:** "pause" → flag set → loop idles → "resume" → continues.
- **Risks:** stuck-paused → visible state indicator + phone status; confusion with kill switch → different phrasing and behavior, documented at setup (§41).

### §16 — Audit log & resource/cost control
- **What:** logs every action; bounds CPU/GPU/spend.
- **How:** an **append-only audit log** records each action (actor, inputs, output, timestamp). A **resource governor** watches CPU/GPU/RAM and throttles background work (lowers concurrency, pauses §25) under load so foreground voice stays snappy. On the OpenAI phase, a **spend meter** tracks tokens and enforces a cap.
- **Tech:** structured logs (JSONL) in `logs/`; psutil/GPU counters for the governor; token accounting in the ModelAdapter.
- **Data flow:** every action → audit; governor reads system metrics → adjusts worker pool.
- **Risks:** log tampering → append-only + part of §42 backups; runaway spend → hard cap halts cloud calls and notifies.

### §17 — Sandbox directory + git-backed rollback
- **What:** full read/write in one dir, read-only elsewhere, auto-commit for undo.
- **How:** all file writes route through the **sandbox guard**, which resolves the real path and rejects anything outside `sandbox/` (blocks symlink escapes, `..`, etc.). After each successful change, a hook **auto-commits** to the local git repo with a descriptive message. Outside-sandbox writes require a scoped §11 approval and are recorded specially.
- **Tech:** path-canonicalization guard module; git with programmatic commits; per-task branches optional for easy revert.
- **Data flow:** write request → guard → allow/deny → write → auto-commit → journal.
- **Risks:** guard bypass → single choke-point for all I/O, no raw handles to the model; repo bloat → periodic gc, large artifacts git-ignored.

### §18 — Low latency (streaming pipeline)
- **What:** < 1.5 s to first spoken word.
- **How:** overlap the whole chain — STT streams partials, the model streams tokens, a sentence-chunker feeds TTS the moment the first sentence is ready, and audio plays while later sentences generate. Wake-word/speaker checks run continuously so they add ~0 ms at request time. Models are kept warm (resident) to avoid load spikes.
- **Tech:** streaming STT (§4) + streaming ModelAdapter + Kokoro/Piper (fast first-audio) + a sentence splitter.
- **Data flow:** speech → partial text → partial tokens → sentence → audio, all concurrent.
- **Risks:** local model TTFT too slow → smaller/quantized model for chat, bigger only for hard tasks (§20); cold models → keep-warm daemon.

### §19 — Multi-turn conversation context
- **What:** natural back-and-forth, no repeated wake word.
- **How:** after a reply, a short **listening window** stays open (VAD-gated) so follow-ups skip the wake word. The **conscious tier** (§8) holds the last N turns as dialog state; it's summarized into memory and cleared when the exchange times out or ends.
- **Tech:** dialog-state buffer in working memory; VAD to detect continued speech; timeout policy.
- **Data flow:** reply → open window → follow-up → same context → … → timeout → consolidate to §8.
- **Risks:** window catches ambient speech → speaker check (§3) still gates; context bloat → rolling summary.

### §20 — Reasoning tier (honest model strategy)
- **What:** match model size to task difficulty.
- **How:** a **complexity router** scores each request (heuristics + quick classifier). Easy/low-latency → small local model; hard planning → larger local model (if hardware) or the cloud escape hatch (if enabled). It can tell you "this is a hard one — use the bigger model?" rather than failing silently.
- **Tech:** Qwen3-7B (default) ↔ Gemma-4-27B / Llama-3.3-70B (hard) ↔ optional cloud; router in the ModelAdapter.
- **Data flow:** request → complexity score → model choice → answer.
- **Risks:** wrong routing → user can force a tier; big-model latency → only for flagged-hard tasks, with a spoken heads-up.

### §21 — Graceful failure & transparency
- **What:** explains failures, never stalls silently.
- **How:** every tool/agent call is wrapped in structured error handling that captures *what was tried* and *why it failed*; the brain converts that into a plain-language report and offers retry / alternate approach / hand-off. Human-only blockers route to §30.
- **Tech:** typed exceptions + retry/backoff policies; error→narrative via the model.
- **Data flow:** failure → captured context → journal + procedural memory → spoken explanation + options.
- **Risks:** silent hangs → per-step timeouts convert hangs into explicit failures.

### §22 — Self-improvement: builds its own tools
- **What:** writes reusable helper tools; can't touch its own core alone.
- **How:** when it detects a recurring/slow pattern, it generates a tool into `sandbox/tools/`, **writes a test, runs it in the sandbox**, and registers it in the tool catalog on pass — all git-committed. **Every generated tool is emitted as an MCP server** (§2A.6), so any model/agent can call it directly. Any change to `core/` is **blocked** by the sandbox guard and requires an explained §11 approval.
- **Tech:** code-gen via the model; FastMCP server template; sandboxed exec + unit test; MCP registry manifest; git.
- **Data flow:** pattern detected → generate → test → register → available next time.
- **Risks:** bad/insecure tools → tests + sandbox isolation + review of anything that touches network/secrets; tool sprawl → catalog with usage stats, prune unused.

### §23 — Protected core + "Jarvis, end yourself" kill switch
- **What:** immutable safety kernel + instant shutdown.
- **How:** `core/` is owned by a different permission context than the running assistant; the sandbox guard has no allow-rule for it, so the AI literally has no write path. The kill phrase is matched by a **dedicated always-on listener in the core** (independent of the main brain loop) that, on match, sends an OS kill signal to the whole process group — even if the main app is wedged. Core changes need out-of-band, human-approved deployment.
- **Tech:** OS file permissions/ownership; a tiny independent kill-listener process; signal-based teardown.
- **Data flow:** "Jarvis, end yourself" → core listener → SIGKILL process group → dead.
- **Risks:** main app hijacks kill switch → impossible by design (separate process, core-owned); accidental trigger → distinct phrase + optional confirm for non-emergency.

### §24 — Anti-hallucination: grounding & honesty
- **What:** reduces made-up answers; admits uncertainty.
- **How:** important answers use **RAG grounding** — retrieve from memory (§8)/web and cite the source; a **verification pass** double-checks consequential claims/actions before they execute; the model is prompted and rewarded to say "I'm not sure" and ask, and a **confidence score** is logged with each decision (§26). Low confidence + high stakes → it asks instead of acting.
- **Tech:** retrieval + citation; a self-check/critic step; confidence estimation surfaced to the journal.
- **Data flow:** query → retrieve+ground → answer with source → (if consequential) verify → act.
- **Risks:** confident-but-wrong → verification + human confirm on stakes; over-hedging → thresholds tuned so it only hedges when it matters.

### §25 — Always-on background brain (continuous thinking)
- **What:** slow, always-running loop that thinks about how to help + runs nightly memory consolidation.
- **How:** a **low-priority background scheduler** runs reflection cycles at throttled intervals: scan recent conversations/memory for signals (e.g. a mentioned 5-year goal), infer possible helpful actions, and produce **proposals** into `memory/staging/` (§26) — never acting on its own, only surfacing "want me to…?" The **nightly consolidation job** (§8) replays and reorganizes the day's memory. All of it yields to foreground load via the resource governor (§16).
- **Tech:** APScheduler low-priority jobs; niced worker; the same model/agents at reduced concurrency.
- **Data flow:** idle → reflect → proposals to staging → offered in conversation; nightly → consolidate memory.
- **Risks:** resource hogging → hard caps + pause under load; creepy over-reach → everything stays in staging until you say yes, and is journaled.

### §26 — Staging folder + full decision journal
- **What:** speculative work held provisionally; every decision recorded with reasoning.
- **How:** background outputs (§25) land in `memory/staging/` with metadata; surfaced conversationally; **promote** → moved into real memory/files, **reject** → deleted. Separately, the **decision journal** appends, for every decision/action, *what, why, alternatives considered, confidence, outcome* — a human-readable layer over the audit log (§16).
- **Tech:** staging dir + lifecycle state; JSONL/SQLite journal keyed to actions.
- **Data flow:** proposal → staging → user choice → promote/delete; each action → journal entry.
- **Risks:** staging clutter → TTL auto-expiry of un-actioned proposals; journal size → rolled + backed up (§42).

### §27 — Smooth self-restart after updates
- **What:** applies tool/code updates and restarts cleanly, ideally when you're away.
- **How:** on an update, it **snapshots state** (queue, dialog, current tasks) to disk, prefers a low-activity window (presence, §10), restarts via the watchdog, then **health-checks**; if the new code fails to boot, it **auto-reverts** to the last good git commit (§17) and restores state.
- **Tech:** state snapshot serializer; watchdog-driven restart; git revert on failed health check; boot self-test.
- **Data flow:** update → snapshot → restart → health check → ok / rollback → restore.
- **Risks:** bricking → rollback guarantees a known-good boot; lost in-flight work → durable queue + snapshot.

### §28 — System & device access (propose, then approve)
- **What:** control WiFi/Bluetooth/audio/apps; discover new capabilities; activate only on approval.
- **How:** an **OS-control tool layer** wraps native commands. In idle time it can *discover* capabilities and **propose** them; each capability is gated behind a §11 approval before first use and recorded. iOS is honestly limited to what Apple allows (Shortcuts, push, companion app) — no free iPhone control.
- **Tech:** AppleScript/`osascript`, PowerShell, `nmcli`/`bluetoothctl`, media keys; iOS Shortcuts + push.
- **Data flow:** proposal → approval → capability enabled → tool available → journaled.
- **Risks:** dangerous OS actions → irreversible ones still hit §11; privilege creep → per-capability consent, revocable.

### §29 — Daily learning (reads, distills, sandbox-tests)
- **What:** grows knowledge daily by reading; tests what it learns safely.
- **How:** a scheduled learner pulls sources tied to your goals/interests (from §8), **summarizes/distills** into semantic memory with citations, and links them into the graph. Anything actionable it learns (code, techniques) is **tried inside the sandbox** first, never on the live system.
- **Tech:** web fetch/search + reader; summarizer; sandbox exec for experiments; memory writer.
- **Data flow:** sources → distill → semantic memory + graph; experiments → sandbox → (if good) tool/skill.
- **Risks:** low-quality/incorrect sources → provenance tracking + verification (§24); model IQ ceiling is fixed → honest per §20 (knowledge grows, not raw reasoning).

### §30 — Blocked-task handoff (presence-aware)
- **What:** on human-only blockers, parks the task, gets you when reachable, keeps working else.
- **How:** a blocker (captcha/2FA/login/decision) raises a `NeedsHuman` interrupt (LangGraph); the job moves to a **"waiting on you" queue**; presence (§10) decides ask-on-screen vs phone; the worker pool **picks up other jobs** meanwhile; on your input the blocked job **resumes from its checkpoint**.
- **Tech:** LangGraph interrupts + checkpointing; waiting queue; presence detector; §10 channel.
- **Data flow:** block → interrupt → waiting queue + notify → (other jobs run) → your input → resume.
- **Risks:** forgotten blocks → visible queue + reminders; resume state loss → durable checkpoints.

### §31 — Skills (learns and applies capabilities)
- **What:** a library of loadable skills; auto-selects the right one; learns new ones.
- **How:** each **skill** = a manifest (name, description, trigger cues, bundled tools, playbook prompt) in `skills/`. On a task, a **skill-router** matches the request (embedding + description match, à la how Claude selects skills) and loads that skill's context. Missing skills trigger acquisition (§32).
- **Tech:** skill manifests (markdown+metadata); embedding-based router; git-tracked catalog.
- **Data flow:** request → skill match → load skill context/tools → execute.
- **Risks:** wrong skill fired → confidence threshold + fallback to general planner; skill rot → usage stats + review.

### §32 — Capability acquisition ("can I do this? if not, build it?")
- **What:** for any unmet request, find a way or build a reusable tool — guiding external-service setup.
- **How:** decision flow: (1) have a skill/tool? use it; (2) buildable? propose; (3) needs an external service (Vapi/Retell/Twilio, an image/SMS API)? **explain, then walk you through account + funding + keys** (stored in vault §14); (4) build in sandbox, test, **save for reuse** — packaged as an MCP server in the registry (§2A.6). Before building from scratch, it first checks whether an existing **third-party MCP server** already provides the capability and can just be plugged in. Money/keys are always your action; irreversible bits hit §11.
- **Tech:** the §22 tool-builder + a guided-setup dialog; provider adapters generated on demand; third-party MCP server discovery.
- **Data flow:** unmet request → build-or-guide → tool created → registered → reused thereafter.
- **Risks:** insecure integrations → sandbox + review for network/secret tools; cost surprises → you fund and approve every paid provider.

### §33 — Personality (one caring, witty assistant)
- **What:** a single consistent persona — intelligent, witty, and genuinely caring; mood-aware, not mood-switching.
- **How:** a fixed **system persona** injected into every prompt defines tone and values. A lightweight **affect sensor** reads mood from text sentiment + voice prosody; when it detects "off," it gently checks in — but the persona never changes, it just becomes more attentive. Off-topic questions get a witty grounded reply.
- **Tech:** persona prompt in `config/`; text sentiment model + prosody features from the audio; policy: "notice mood → adjust attentiveness, not identity."
- **Data flow:** input (+ audio prosody) → affect estimate → persona-consistent response, more caring if low mood.
- **Risks:** misread emotion → phrase as a gentle question, never an assumption; over-familiarity → tone bounded by persona config, tunable at setup (§41).

### §34 — Friend mode (talks with you, not just at you)
- **What:** light, balanced conversation during work.
- **How:** a **chattiness setting** governs how often it volunteers non-task talk; it reads context (focus vs. open) from activity/presence to stay quiet when you're heads-down and sociable when you're not. Purely additive to the persona (§33).
- **Tech:** chattiness parameter; context/presence signals; conversation policy.
- **Data flow:** activity signal → chattiness gate → occasional friendly interjection.
- **Risks:** annoying over-talk → conservative default + "less chatty" voice command; interrupting focus → presence-gated silence.

### §35 — Voice-safe permissions (no typing needed)
- **What:** all control by voice; safety via confirmation, not perfect STT.
- **How:** commands/approvals are spoken. For **critical/irreversible** actions the system requires an explicit spoken **yes/no confirmation** with the action read back ("delete X — yes or no?"); routine reversible actions proceed frictionlessly. Confirmation guards against STT misreads (§4) since 100% accuracy is not real.
- **Tech:** the §11 approval engine wired to a spoken confirm dialog; speaker check (§3) on the confirmation too.
- **Data flow:** command → intent → (if risky) read-back + confirm → execute.
- **Risks:** misheard critical command → read-back catches it before execution; spoofed confirm → speaker verification on the yes/no.

### §36 — Device awareness (knows your setup)
- **What:** detects and remembers every connected device.
- **How:** an **event listener** on USB/Bluetooth/audio subsystems logs connect/disconnect; each device is written to memory (§8) with type and name; new devices can trigger a helpful offer (never silent action). Enables things like "route audio to your headphones."
- **Tech:** OS device APIs (IOKit / WMI / udev + BlueZ); device inventory table in SQLite.
- **Data flow:** device event → inventory update → memory → optional offer.
- **Risks:** noisy device churn → debounce + only surface meaningful changes; privacy → inventory is local, in §42 backups only.

### §37 — Pre-task narration (says the plan first)
- **What:** 1–2 line "here's what I'm about to do" before big/irreversible tasks.
- **How:** the planner (§6) emits a **short intent summary** before executing a task flagged significant/irreversible; for irreversible ones it waits (ties to §11), for merely big-but-reversible it narrates then proceeds. Small/reversible tasks skip it to stay fast.
- **Tech:** task-significance classifier; summary generation; gate before execution.
- **Data flow:** plan ready → significance check → narrate (± wait) → execute.
- **Risks:** narrating everything (annoying) → threshold so only significant tasks trigger it.

### §38 — Calendar, reminders & time-awareness
- **What:** manages schedule, reminders, and knows the time/your routine.
- **How:** a **local calendar/reminder store** with a scheduler firing time-based events into the bus (voiced or pushed). Optional two-way sync to Google/Outlook is a §32-built connector with approval. Routine awareness comes from patterns in memory (§8).
- **Tech:** SQLite calendar + APScheduler; CalDAV/Google/Graph API connectors on demand; nudge engine.
- **Data flow:** create/parse reminder → store → scheduler fires → notify (local/phone) ; proposed reminders → staging (§26).
- **Risks:** missed fires on downtime → catch-up scan on boot; timezone/DST bugs → store UTC, render local.

### §39 — Email & messaging
- **What:** read, summarize, triage, and draft — never send without you.
- **How:** connectors pull mail/messages; the model **summarizes and flags** what needs you and **drafts replies in your voice** (using style from memory); **sending is always gated by §11** with the draft shown. Connectors are §32-built with OAuth stored in the vault.
- **Tech:** Gmail/Graph/IMAP + messaging APIs via connectors; style-conditioned drafting; approval-gated send.
- **Data flow:** inbox → summarize/triage → draft → your approval → send.
- **Risks:** wrong-recipient/irreversible send → hard approval + read-back; credential safety → vault (§14), scoped scopes.

### §40 — Proactive daily briefing
- **What:** regular "where things stand" summary.
- **How:** a scheduled job assembles calendar (§38), waiting-on-you queue (§30), overnight work (§25), and notable memory changes into a **morning brief**, delivered by voice or to phone if away; an evening/on-demand brief covers what it did and is thinking about.
- **Tech:** APScheduler job + a briefing template; the "morning"-style render for phone/voice.
- **Data flow:** schedule → gather from subsystems → compose → deliver (voice/§10).
- **Risks:** brief overload → prioritized, short by default, drill-down on request.

### §41 — First-run setup & onboarding
- **What:** guided initial configuration.
- **How:** a wizard walks through **voice enrollment** (§3), choosing the **sandbox path** (§17), linking the **phone** (§10), adding **first credentials** (§14), and a **kill-switch explainer** (§23); sets preferences (name, wake word, quiet hours, chattiness §34). Writes to `config/`.
- **Tech:** setup wizard (voice + minimal UI); enrollment recorder; config writer.
- **Data flow:** wizard answers → config + voiceprint + vault seeded → system ready.
- **Risks:** bad enrollment → multi-sample capture + re-enroll option; misconfig → sane defaults + re-run setup anytime.

### §42 — Encrypted memory backup
- **What:** memory/skills/tools/journal backed up and portable.
- **How:** a scheduled job creates **encrypted snapshots** of `memory/`, `skills/`, `sandbox/tools/`, and the journal to a user-chosen location (external drive / their own cloud); **restore** rebuilds Jarvis on a new machine with all memory intact. Backups are encrypted with a key you hold.
- **Tech:** encrypted archive (age/libsodium) + incremental snapshots; restore routine; scheduler.
- **Data flow:** schedule → snapshot → encrypt → store; restore → decrypt → rehydrate stores.
- **Risks:** silent backup failure → verification + alert; key loss → clearly documented at setup that the key is unrecoverable by design.

---

## 4. Build Sequence (maps to spec phases)

- **Phase 0 — Setup (§41, §14, §17, §23):** onboarding wizard, vault, sandbox+git, immutable core + kill switch. *Safety and boundaries first.*
- **Phase 1 — Voice + memory on OpenAI (§1–5, §8, §13, §18, §19, §35, §42):** the brain loop, streaming voice pipeline, brain-like memory + nightly consolidation, backups. **LangSmith tracing wired in from day one** (§2A.5) — instrumenting later is always more painful.
- **Phase 2 — Agents + actions (§6, §7, §9, §11, §16, §21, §30, §26, §38, §39, §40):** planner, the M1/M2/M3 workflow modes and supervisor topology (§2A), sub-agents, task queue, approval engine, audit/journal, handoff, calendar/mail/briefing.
- **Phase 3 — Self-improvement + proactive (§22, §31, §32, §25, §29, §12, §20, §24, §27, §33, §34, §37):** tools/skills, capability acquisition, background brain, learning, personality.
- **Phase 4 — Reach out (§10, §28, §36, §2, §15):** mobile 2-way, device control/awareness, autostart, pause.
- **Phase 5 — Go local (§1 swap, §20 tune, §2A.5 swap):** replace OpenAI with Qwen3/Gemma via Ollama, swap LangSmith → self-hosted Langfuse, optimize latency, run fully offline.

## 5. Key Architectural Risks (top of mind)

1. **Local model reasoning ceiling** — the honest limiter; mitigated by tiering (§20) and strict tool schemas so the model orchestrates rather than free-reasons.
2. **Latency budget** — hardest non-functional target; met only by end-to-end streaming (§18) and keep-warm models.
3. **Execution reliability** — browser/OS automation is brittle; mitigated by graceful failure (§21) + human handoff (§30) rather than pretending it won't break.
4. **Safety enforcement must be structural** — approval/sandbox/core are code paths, never prompt instructions the model could rationalize around.
5. **Resource contention** — always-on voice + background brain + local LLM compete; the resource governor (§16) and worker isolation are essential, not optional.





