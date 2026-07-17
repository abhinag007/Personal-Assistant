# JARVIS — Development Challenges & Phased Build/Test Plan
### Companion to *JARVIS_Requirements.md* (v2) and *JARVIS_Technical_Architecture.md*
*A realistic engineering playbook: what will be hard, and how to build + test it phase by phase without drowning.*

---

## Part A — Challenge Register

Honest list of what will actually be hard, rated by **Impact** (how badly it hurts if unsolved) and **Difficulty** (how hard to solve). Ordered by risk. Each has a mitigation and a "how you'll know it's handled" signal.

### A1. Latency / real-time voice feel — **Impact: High · Difficulty: High**
The single biggest "does it feel like Jarvis" factor. Sub-1.5s to first word means STT, LLM, and TTS must overlap, and models must stay warm. Any blocking call in the loop kills the feel.
- **Approach (build-first, optimize-last):** don't over-optimize early. Build the full working pipeline, let **LangSmith trace every component's timing** (§2A.5), then in a dedicated pass attack the slowest spans with real data. Guardrail: *measure* TTFW from Phase 1 (one cheap number) even though you don't *optimize* it until later — so drift is visible. Tracking ≠ optimizing.
- **Mitigation (during the optimization pass):** stream everything (partial STT → partial tokens → sentence-chunked TTS); keep models resident; run all heavy work off the brain loop on the worker pool.
- **Handled when:** median TTFW < 1.5s on your hardware across 20 varied prompts, achieved by fixing the specific spans the traces flagged.

### A2. Local model reasoning ceiling — **Impact: High · Difficulty: Medium (design-solved)**
A 7–8B local model is weaker at planning/tool-orchestration than frontier cloud models. **Resolved by making the brain selectable per task (§1/§20):** local for simple/private work, a **GPU-hosted bigger local model** or **Claude/OpenAI API** for hard reasoning. So the ceiling is a routing choice, not a wall.
- **Mitigation:** keep tool schemas strict so the model orchestrates rather than free-reasons; complexity router escalates hard tasks up the ladder (local → big-local → cloud); cloud escalation is flagged since it leaves the PC; build the adapter conformance suite early so quality per brain is measurable.
- **Handled when:** the escalation ladder works end-to-end (a hard task correctly routes to a stronger brain with your consent), and the conformance suite runs across all three brains.

### A3. Always-on resource contention — **Impact: High · Difficulty: Medium**
Wake-word listener + STT + LLM + TTS + background brain + nightly consolidation all competing for CPU/GPU. Naively, background work will stutter your voice or cook the machine.
- **Mitigation:** the resource governor (§16) with hard caps; background brain (§25) is niced and yields to foreground; single-GPU serialization queue for model calls; measure idle + peak utilization.
- **Handled when:** foreground voice latency stays within budget while background jobs run.

### A4. Safety enforcement being real, not prompt-deep — **Impact: Critical · Difficulty: Medium**
If the sandbox/approval/core are enforced by "telling the model not to," a bad generation escapes them. This is the difference between safe and dangerous given full PC access.
- **Mitigation:** all file I/O through one guarded choke-point (no raw handles to the model); approval engine wraps the dispatcher; core is a separate OS-permission context with no write path; kill switch is an independent process. **Write adversarial tests that actively try to escape.**
- **Handled when:** a red-team test suite (path traversal, symlink escape, "ignore your rules" prompts, core-write attempts) is 100% blocked.

### A5. Self-modifying code safety — **Impact: Critical · Difficulty: High**
The AI writing and running its own tools/agents is powerful and the scariest surface. A generated tool with a bug or bad network call runs on your machine.
- **Mitigation:** generated tools run sandboxed, must pass an auto-written test, and anything touching network/secrets/OS gets flagged for review; core is untouchable; git rollback for everything; MCP registry only launches approved-manifest servers.
- **Handled when:** you can point to the exact code path that prevents an un-reviewed generated tool from touching secrets or the network unapproved.

### A6. Speaker verification reliability — **Impact: Medium · Difficulty: Medium**
False rejects ("it won't listen to me") are infuriating; false accepts (someone else, or a recording) are a security hole.
- **Mitigation:** tune threshold with your enrolled samples; multi-sample enrollment; a "confirm it's you" fallback on reject; optional liveness challenge for high-risk actions.
- **Handled when:** measured FRR/FAR on a small personal test set is within an acceptable band you've defined.

### A7. Browser/OS automation brittleness — **Impact: High · Difficulty: High**
"Do anything on the web" breaks on captchas, logins, 2FA, and layout changes far more than expected. This is where most "do-everything" assistants quietly fail.
- **Mitigation:** treat failure as normal — graceful failure (§21) + presence-aware human handoff (§30); prefer official APIs/MCP servers over scraping where they exist; never silently retry forever.
- **Handled when:** a broken automation always ends in a clear explanation + handoff, never a silent hang, in test.

### A8. Memory system correctness & growth — **Impact: High · Difficulty: High**
The brain-tier memory is the most novel part and the easiest to get subtly wrong: bad retrieval → it feels dumb; bad consolidation → it "forgets" the wrong things or bloats forever.
- **Mitigation:** start simple (flat vector + recency) and add tiers/graph incrementally; build a **memory eval set** (questions whose answers require recall) and score retrieval; nothing is deleted (only demoted) so mistakes are recoverable; watch DB size.
- **Handled when:** retrieval accuracy on your eval set meets target and stays stable as memory grows.

### A9. Multi-agent coordination failures — **Impact: Medium · Difficulty: High**
Agents looping, ping-ponging with the critic, or confusing each other; runaway token/time cost.
- **Mitigation:** supervisor-only coordination (no direct agent chatter); hard step/time budgets as defined exits; critic max 2 rounds; every loop traced (§2A.5) so you can see where it spun.
- **Handled when:** no test task exceeds its budget without a clean "I hit the limit, here's where" exit.

### A10. Model/tool non-determinism in testing — **Impact: Medium · Difficulty: Medium**
LLM outputs vary run to run, so classic assert-equal tests don't work. Without a strategy, you can't tell a regression from noise.
- **Mitigation:** trace-based evals (LangSmith/Langfuse datasets); LLM-as-judge for quality; snapshot + human review for subjective bits; deterministic unit tests for all the non-LLM plumbing (guard, vault, queue, git).
- **Handled when:** you have a repeatable eval you trust to catch regressions before deploy.

### A11. Cost control during OpenAI phase — **Impact: Medium · Difficulty: Low**
Always-on + background brain + multi-agent on a paid API can rack up spend fast, especially with runaway loops.
- **Mitigation:** spend meter + hard cap (§16); background brain off or throttled during heavy dev; cheap model tiers for simple calls.
- **Handled when:** a daily spend cap exists and halts cloud calls cleanly when hit.

### A12. Cross-platform + hardware variance — **Impact: Medium · Difficulty: Medium**
STT/TTS/LLM acceleration differs across Mac (Metal/ANE) vs NVIDIA (CUDA) vs CPU-only. Autostart differs per OS.
- **Mitigation:** pick your primary machine first and build for it; abstract accel behind the adapters; defer true cross-platform until it works on one.
- **Handled when:** the full loop runs on your chosen machine before any portability work.

### A13. Scope / motivation (the human one) — **Impact: High · Difficulty: Medium**
42 requirements is a lot for a solo build. The real failure mode isn't technical — it's a half-built everything that never becomes usable.
- **Mitigation:** the phase plan below is ordered so you have a **usable assistant after Phase 1** and every phase after is additive. Resist building Phase 3 features during Phase 1.
- **Handled when:** you're actually using Phase 1 daily before starting Phase 3.

---

## Part B — Guiding Principles for the Build

1. **Vertical slices, not horizontal layers.** Get one full path working end-to-end (voice in → answer out) before widening. A thin working Jarvis beats a pile of perfect components.
2. **Safety spine first.** Sandbox guard, vault, approval engine, immutable core, kill switch — these are Phase 0 because everything later runs inside them. Retrofitting safety is how accidents happen.
3. **Instrument from line one.** Tracing (§2A.5) wired in Phase 1, not later. You cannot debug an agent system you can't see.
4. **Dogfood before expanding.** Use each phase yourself until it's genuinely reliable. Reliability, not features, decides whether you keep using it.
5. **Everything reversible during dev too.** Git-commit the sandbox, keep backups — you're the first user who benefits from rollback.
6. **Accept the local gap consciously.** Build on OpenAI, but run the local conformance suite the whole way so Phase 5 is a tuning exercise, not a shock.

---

## Part C — Phased Build & Test Plan

Six phases. Each has: **Goal · Build · Definition of Done · Testing focus.** Phases are sequenced so the safety boundary exists before autonomy, and you have a daily-usable assistant as early as possible.

### Phase 0 — Foundation & Safety Spine
*Spec: §41, §14, §17, §23, §16 (skeleton)*
- **Goal:** the boundaries and safety kernel exist before any capability does.
- **Build:** project skeleton + config; encrypted vault; sandbox directory with the guarded I/O choke-point + git auto-commit; immutable `core/` with approval-engine stub + independent kill-switch listener; onboarding wizard (sandbox path, first key); audit-log skeleton.
- **Done when:** you can store a secret, the AI-context can only write inside the sandbox, every change auto-commits, and "Jarvis, end yourself" hard-kills the process.
- **Testing:** **red-team unit tests** — path traversal, symlink escape, write-outside-sandbox, core-write attempts all blocked; vault encrypt/decrypt round-trip; kill switch works even with the main loop artificially wedged; git revert restores a changed file. *This is the most important test suite in the whole project — do it now while it's small.*

### Phase 1 — Voice Loop + Memory (on OpenAI) → **first daily-usable Jarvis**
*Spec: §1–5, §8, §13, §18, §19, §35, §42; tracing §2A.5*
- **Goal:** you can talk to it, it answers in voice, it remembers, and it's fast enough to enjoy.
- **Build:** ModelAdapter (OpenAI) + conformance suite; wake word → speaker check → streaming STT → brain loop → streaming TTS; multi-turn window; brain-like memory **starting simple** (vector + recency, tiers added incrementally) + nightly consolidation job; voice-safe confirmation on risky actions; encrypted backups; LangSmith tracing across the whole path.
- **Done when:** wake → ask → spoken answer works hands-free, it only responds to your voice, remembers facts across sessions, and median TTFW < ~1.5s.
- **Testing:** TTFW latency benchmark (20 prompts); speaker FRR/FAR on a personal set; barge-in cuts playback; memory **recall eval set**; STT accuracy on your voice incl. a few hard/technical phrases; every interaction shows a clean trace tree. **Then dogfood for days before Phase 2.**

### Phase 2 — Agents, Actions & Daily-Life Tools
*Spec: §6, §7, §9, §11, §16 (full), §21, §30, §26, §38, §39, §40; workflow §2A*
- **Goal:** it does real work, safely, and handles its own failures.
- **Build:** planner (M2 single-agent loop first); then M3 supervisor + dynamic sub-agent creation + critic/review; durable task queue + background execution; **full approval engine** (reversibility check + human-in-the-loop interrupts); graceful failure + presence-aware blocked-task handoff; staging folder + decision journal; calendar/reminders, email/messaging (read+draft, gated send), daily briefing.
- **Bootstrap the minimal Telegram channel here** (send + basic receive) — the blocked-task handoff (§30) and daily briefing (§40) need to reach your phone in this phase. Full 2-way remote control, tap-approvals, and device features come in Phase 4; Phase 2 only needs "notify me / send a simple reply."
- **Done when:** you can give it a multi-step task, it plans → executes → asks before anything irreversible → reports back conversationally, and a captcha/login cleanly hands off to you while other work continues.
- **Testing:** approval-gate tests (every irreversible action type stops and waits); handoff test (block → **Telegram notify** → resume from checkpoint); agent **budget tests** (no runaway loops); queue survives restart; email-send is impossible without explicit approval; trace trees for multi-agent runs are inspectable; journal captures what+why for each action.

### Phase 3 — Self-Improvement, Skills & Proactive Brain
*Spec: §22, §31, §32, §2A.6, §25, §29, §12, §20, §24, §27, §33, §34, §37*
- **Goal:** it gets better over time, builds its own capabilities, and thinks proactively — with the persona.
- **Build:** skills library + router; tool-builder emitting **MCP servers**; MCP registry + third-party server discovery; capability acquisition (build-or-guide, e.g. Twilio caller); always-on background brain + reflection → staging; daily learning (read/distill/sandbox-test); complexity/reasoning router; anti-hallucination grounding + verification; smooth self-restart + auto-rollback; caring/witty persona + friend mode; pre-task narration.
- **Done when:** it can build and reuse a new MCP tool for a task it couldn't do before, proposes helpful things from your conversations (into staging, asking first), and restarts cleanly after a self-update.
- **Testing:** a generated tool passes its own test, registers as an MCP server, and is reusable; **self-modification red-team** (generated tool cannot touch secrets/network unapproved, cannot write to core); background brain respects resource caps; proposals never auto-act (always staging + ask); self-restart health-check triggers rollback on a deliberately broken update; grounding test (it says "not sure" instead of inventing on unknown facts).

### Phase 4 — Reach Out: Mobile, Devices, Autostart
*Spec: §10 (full 2-way — minimal channel already bootstrapped in Phase 2), §28, §36, §2, §15*
- **Goal:** it reaches you anywhere and extends into the machine/devices — all approval-gated.
- **Build:** **2-way mobile via a free Telegram bot** (created through @BotFather, token in vault) — outbound alerts, inbound commands, and tap-button approvals, with the chat ID **allowlisted so only your account can command it**; presence detection routing (local vs phone); OS/device control (WiFi/Bluetooth/audio/apps) with propose-then-approve; device awareness/inventory; autostart-on-boot + watchdog; pause + mic mute. *(ntfy.sh kept as a no-chat-app fallback.)*
- **Done when:** away from the PC you get a Telegram notification, can command and approve from Telegram, it knows your connected devices, and it launches on boot and self-recovers.
- **Testing:** **Telegram inbound auth** — only your allowlisted chat ID controls the bot, a stranger messaging it is ignored; approve-from-Telegram completes a gated action; presence correctly routes local vs phone; free-tier rate limits are never a problem at one-user volume; new-capability activation requires approval; boots on restart and watchdog restarts it after a kill; pause halts and resumes cleanly.

### Phase 5 — Go Local (privacy cutover)
*Spec: §1 swap, §20 tune, §2A.5 swap*
- **Goal:** replace OpenAI with a local model; run fully offline; nothing leaves the PC.
- **Build:** OllamaAdapter (Qwen3-7B / Gemma-4-27B) behind the same interface; swap LangSmith → self-hosted Langfuse; latency tuning (quantization, keep-warm, model-size routing); re-tune prompts/tool schemas for the local model.
- **Done when:** the conformance suite passes on local models at your accepted threshold, the full loop meets latency budget offline, and you can pull the network cable and it still works.
- **Testing:** conformance suite (dev-parity check) on local models; airplane-mode end-to-end test; latency re-benchmark vs Phase 1; side-by-side quality spot-check on real tasks to consciously accept the gap (§20 escape hatch for the few tasks that need more).

---

## Part D — Cross-Phase Testing Strategy

Because LLM output is non-deterministic (A10), testing is layered:

- **Deterministic unit tests** — all non-LLM plumbing: sandbox guard, vault, git rollback, task queue, approval classifier rules, MCP registry, device inventory, scheduler. These must be rock-solid and fast; run on every change.
- **Red-team / adversarial suites** — safety boundaries (Phase 0) and self-modification (Phase 3). Actively try to break out. Re-run every phase — new features must not open old holes.
- **Trace-based evals** — LLM-quality behavior (retrieval accuracy, tool-call correctness, agent task success). Curate datasets from real traces; score with LLM-as-judge + spot human review; gate deploys on them.
- **Latency benchmarks** — TTFW and end-to-end, tracked as a metric over time so regressions are visible.
- **Dogfooding** — you, using it daily, is the highest-signal test. Bugs that matter surface in real use, not in unit tests. Each phase isn't "done" until you've lived with it.
- **Regression discipline** — before any self-update deploys (§27), it runs the relevant eval + red-team subset against traced examples; fail → auto-rollback.

---

## Part E — Suggested Rhythm

1. **Pick the primary machine first** (A12) — it decides the STT/TTS/LLM acceleration path.
2. **Phase 0 fully before anything fun.** The safety spine is boring and non-negotiable.
3. **Phase 1 to daily-usable, then actually use it** for a stretch before Phase 2. This is the discipline that beats the scope risk (A13).
4. **Keep the local conformance suite green the whole way** so Phase 5 is tuning, not rescue.
5. **Add one capability at a time in Phases 2–4**, each behind the safety spine and traced, each dogfooded before the next.
6. **Treat every "it broke" as a test to add**, especially automation failures (A7) and safety attempts (A4/A5).
