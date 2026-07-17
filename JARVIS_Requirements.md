# JARVIS — Personal AI Assistant
### Full Requirements Specification (v2)

A private, always-on, voice-driven personal assistant that remembers everything, executes tasks autonomously through sub-agents, learns and improves itself over time, and reaches you on your phone when you're away. It runs on OpenAI's model **during development**, then switches to a **fully local** model once mature — after which no data leaves your PC. No paid voice APIs required.

> **Model plan:** Build/test phase → **OpenAI** (faster iteration). Once development is complete → **local model** becomes primary and the assistant runs fully offline (§1).

> **Privacy vs. action risk:** Once local, there is no data-leak / cloud-exposure risk. What always needs guarding is *actions* — deleting files, sending messages, purchases, self-modifying code — because those can be irreversible whether the model is local or cloud. That's why §11 (approval gates), §16 (audit log) and §23 (protected core) stay regardless of which model is running.

---

## 1. Core Intelligence — OpenAI Now, Local Later
The assistant uses a **pluggable model layer** so the brain can be swapped without touching the rest of the system.

- **During development:** runs on **OpenAI** for faster, higher-quality iteration.
- **After development is complete:** switches to a **local LLM via Ollama** (Llama 3 / Qwen / Mistral) and runs fully offline — no data leaves the PC.
- The switch is a config change, not a rewrite — everything downstream (memory, agents, voice) is model-agnostic.
- API keys (OpenAI now, any provider later) live in the encrypted vault (§14), never in plain text.

## 2. Auto-Start on Boot
The assistant launches automatically when the PC starts and runs silently in the background.

- Installed as a **startup service** (Windows Task Scheduler / systemd / launchd).
- Auto-recovers if it crashes (watchdog restarts it).
- Starts in listening standby with minimal resource use until the wake word is heard.

## 3. Voice Listening + Speaker Verification (Only Responds to You)
It listens for a **wake word**, then transcribes speech, and **only acts on your voice** — ignores everyone else.

- Wake word ("Hey Jarvis") via **openWakeWord** so it isn't recording constantly.
- One-time **voice enrollment**: you record samples so it learns your voiceprint.
- Speaker verification via **SpeechBrain / Resemblyzer** — unknown voices are ignored.
- **Barge-in**: it stops speaking the instant you start talking.

## 4. Free Speech-to-Text (STT)
All voice-to-text runs locally with no paid service.

- Engine: **faster-whisper** or **whisper.cpp** (fully offline, high accuracy).
- Handles background noise and continuous listening after the wake word.

## 5. Free Jarvis-Style Text-to-Speech (TTS)
It replies in a natural, Jarvis-like voice using free, local synthesis.

- Engine: **Piper** (fast, local, natural) — or **XTTS/Coqui** to clone a specific Jarvis-like voice.
- No paid TTS API; runs on your machine.

## 6. Autonomous Task Execution with Fallback Planning
When you assign a task, it does it. If there's no built-in way, it **creates a plan and finds a way** — using the browser or the PC — to complete it.

- Executes known tasks directly.
- For unknown tasks: generates a step-by-step plan, then acts via **browser automation (Playwright / Chrome tools)** or desktop control.
- If it lacks the capability entirely, it tries to **build a tool for it** (§32) or **learn a skill** (§31) — e.g. if you later want image generation for marketing, it builds that as a tool on demand, not pre-installed.
- Logs in to sites when needed using credentials from the encrypted vault.
- On failure: retries, adapts the plan, and reports back instead of silently stopping.

## 7. Sub-Agent Orchestration (Sandbox)
Complex work is split across **multiple sub-agents**, each with a focused prompt, then merged on completion.

- A central **orchestrator** breaks a goal into sub-tasks and assigns each to an agent with a clear, scoped prompt.
- Agents run in the sandbox in parallel where possible.
- Results are validated and **merged into one final answer/output**.
- Framework: an orchestrator pattern (e.g. LangGraph) with a merge/verify step.

## 8. Brain-Like Memory — Conscious, Subconscious, Unconscious
Memory is modeled on the **human brain**: information moves between tiers based on **how often it's recalled**, it's **reorganized at the end of every day** (like sleep), and old memories can be **re-fetched and re-strengthened** on cue. Early on it knows little and acts simply; as memory accumulates and connects, it acts with real judgment — like a child maturing. All memory is stored **locally, encrypted**.

**Three tiers (by recall frequency), like the mind:**
- **Conscious (working memory):** the current conversation and active task — small, fast, always in focus. Clears when the exchange ends.
- **Subconscious (warm long-term):** things recalled often or recently — instantly available, kept "close to the surface."
- **Unconscious (cold long-term / archive):** rarely-used memories — stored deep and compressed, not in active reach but **never deleted**, retrievable when a cue calls them back.

**How memory moves — recall frequency is the driver (like hippocampus → neocortex consolidation):**
- Frequently recalled memories are **promoted upward** (unconscious → subconscious → conscious) and strengthened.
- Rarely recalled memories **decay downward** over time (conscious → subconscious → unconscious), mirroring the forgetting curve — but they're archived, not lost.

**End-of-day consolidation (the "sleep" pass, runs via §25):**
- Each night it **replays and reorganizes the day**: reactivates important memories, **links related ones into the knowledge graph**, promotes what mattered, lets the trivial fade to the unconscious tier, and prunes true noise.
- This is systems consolidation: raw daily episodes get integrated into durable, connected long-term knowledge.

**Re-fetch + reconsolidation (recall changes memory, like the brain):**
- A cue (your words, a related task) can **pull a deep memory back up** into the subconscious/conscious tier.
- When recalled, a memory can be **updated and re-strengthened** (reconsolidation) — so acting on old knowledge also refreshes and corrects it.

**Memory types (cut across the tiers):** **Episodic** (what happened, when), **Semantic/Profile** (facts about you, preferences, goals), **Procedural** (how a task was done — reused next time), all linked in a **knowledge graph** so it *connects* facts ("you mentioned a marathon + asked about knee pain") rather than recalling them in isolation.

**Storage:** **SQLite** (structured facts, tier/recall metadata, graph links) + **ChromaDB / FAISS** (semantic vector search for cue-based re-fetch), encrypted at rest, backed up per §42.

## 9. Background Execution + Conversational Updates
Tasks run in the background; it talks to you naturally, like an assistant, and notifies you of progress and completion.

- Durable task queue that survives restarts.
- Long-running tasks are monitored with retry/timeout handling.
- Status and results delivered in a **conversational tone** (voice or chat).

## 10. Mobile Notifications + Remote Control (When You're Away)
If you're not at the computer, it notifies your phone — and you can **send commands and approvals back** from mobile.

- Presence detection: if you're away from the PC, route updates to phone.
- Free two-way channel: **Telegram bot** or **ntfy.sh** (no paid Pushover).
- From your phone you can: get task/status alerts, issue new commands, and approve/deny pending actions.

## 11. Safety — Think Before Acting; Ask Before Anything Irreversible
Before any action, the assistant first asks itself: **"Is this reversible?"** If it can be undone (e.g. a change inside the sandbox, which git can revert — §17), it proceeds. If it **cannot** be undone, it **stops and asks you first**.

- Reversibility check runs before every action, as a mandatory step in the brain loop (§13).
- Always requires explicit approval before: **money transactions / transfers / purchases**, sending email or messages, posting online, deleting anything outside the sandbox, or any other irreversible action.
- Never executes trades or moves money on its own — no exceptions.
- Approvals can be granted in person or **remotely from your phone** (ties to §10).
- When it asks, it explains *what* it wants to do and *why it's irreversible*, so you can decide with full context.

## 12. Full PC + Internet Access
It has full read access to your PC and the internet, so it can research, act, and prepare things for you.

- Powers task execution (§6), device access (§28), and daily learning (§29); the **idle-time proactive research lives in the background brain (§25)**.
- Every autonomous action is bounded by the safety gates (§11), the sandbox (§17), and logged (§16).

## 13. Central Orchestrator / Brain Loop *(new — was missing)*
One always-running controller ties everything together.

- Pipeline: **wake word → STT → speaker check → intent → model routing → agent dispatch → merge → TTS / notify → memory write.**
- Without this loop, the individual parts don't connect into an assistant.

## 14. Encrypted Secrets & Credential Vault *(new — was missing)*
A secure store for API keys, passwords, and login credentials.

- Encrypted at rest; unlocked at startup.
- Used by browser automation to log in to sites (§6) and by model routing for API keys (§1).

## 15. Pause & Mic Mute *(new — was missing)*
Lightweight control over listening (the hard, total shutdown is the kill switch in §23).

- **"Stop / pause"** halts the current action and listening immediately — a soft, resumable pause.
- **Mic mute** for sensitive moments (a convenience toggle, not a security control).
- For a full shutdown of everything, use **"Jarvis, end yourself"** (§23).

## 16. Audit Log & Resource/Cost Control *(new — was missing)*
Because it has full PC and internet access, every *action* it takes is logged and bounded. See §26 for the full **decision journal** (what it did **and why**).

- Readable **audit trail** of every action taken, so you can review and undo.
- Resource throttling for CPU/GPU (always-on mic + model + TTS + background thinking).
- Spend cap / rate limiting while on OpenAI (§1) so development costs stay bounded; not needed once local.

## 17. Sandbox Directory + Git-Backed Rollback *(new)*
The assistant is confined to **one designated directory (the sandbox)**. It has full read/write there and can do anything inside it. Everywhere else on the PC is **read-only**.

- **Inside the sandbox:** full freedom to create, edit, run, and delete files.
- **Outside the sandbox:** **read-only** — it can look but not touch. If it decides it genuinely needs to write, move, or delete anything outside the sandbox, it **asks you for permission first** and only proceeds if you approve (scoped to that specific action/path).
- **Git-backed safety net:** the sandbox is a local git repository. **After every change, the assistant auto-commits** with a descriptive message. If anything goes wrong, any change can be reverted to a previous commit — nothing is ever truly lost inside the sandbox.
- This is why sandbox changes count as "reversible" in the §11 check: git can always roll them back, so they don't need per-action approval. Actions *outside* the sandbox are not git-protected and therefore always require approval.
- Config: you set the sandbox path once at setup; the assistant refuses write access to any path outside it.

## 18. Low Latency — Streaming Pipeline *(new)*
It must feel instant, like Jarvis — not a 5-second pause after you speak.

- **Target: under 1.5 seconds to the first spoken word** of a reply.
- Achieved by **streaming and overlapping** the whole pipeline: streaming STT (transcribe while you talk) → streaming LLM (generate tokens as it thinks) → streaming TTS (speak the first sentence while the rest generates).
- Wake-word and speaker check add near-zero delay (run on-device continuously).

## 19. Multi-Turn Conversation Context *(new)*
It holds a natural back-and-forth, not one isolated command at a time.

- **No wake word needed mid-conversation** — once talking, it keeps listening for follow-ups until the exchange ends or times out.
- Remembers the **last N turns** so "and do the same for that one" works without re-explaining.
- Short-term dialog context is separate from long-term memory (§8) and clears when the conversation ends.

## 20. Reasoning Tier — Honest Model Strategy *(new)*
Local-only means reasoning is capped by the local model's size; this is planned for, not hidden.

- Default: a fast local model for everyday tasks and low latency.
- Optional **larger local model** (e.g. 70B, needs a strong GPU) for harder planning — enable when hardware allows.
- The cloud switch (§1, off by default) remains the escape hatch for the hardest reasoning if you ever choose to turn it on.
- The assistant knows its own limits and says "this is a hard one, want me to use the bigger model?" rather than failing quietly.

## 21. Graceful Failure & Transparency *(new)*
When an autonomous task can't be completed, it explains — never stalls silently.

- Browser/PC automation failures (captchas, logins, layout changes) are caught and reported: **"I couldn't do X because Y — here's what I tried."**
- Offers the next best option: retry, a different approach, or hand it back to you. When only a human can clear it, the **presence-aware handoff in §30** takes over.
- Every failure is written to the audit log (§16) and, where useful, to procedural memory (§8) so it does better next time.

## 22. Self-Improvement — Builds Its Own Tools *(new)*
It gets faster over time by writing its own helper tools for tasks you do often. A clear line separates safe self-improvement from risky self-modification.

- **New tools = free.** When it notices a recurring or slow task, it can **write new helper functions/tools into a `tools/` folder**, test them in the sandbox, and use them next time — all auto-committed to git (§17). This is how it speeds up your daily life without asking each time.
- **Core changes = permission required.** It may **not** modify its own core logic on its own. To change anything in the protected core (§23) it must **ask you, explain exactly what it wants to change and why**, and only proceed if you approve.
- Every generated tool is git-tracked and reversible; a bad tool can always be rolled back.

## 23. Protected Core + "Jarvis, End Yourself" Kill Switch *(new)*
A locked **core folder** holds the assistant's essential logic and its own off-switch. This is the safety backbone.

- The **core is immutable to the AI** — it cannot edit, disable, or delete anything in it without your explicit, per-change approval and a written explanation.
- The kill command **"Jarvis, end yourself"** lives inside this core and **immediately shuts everything down** — voice, agents, background thinking, all actions. The AI can never modify, disable, or delete this command.
- The kill switch and approval logic are the two things the AI can never touch, no matter what. If anything ever goes wrong, you always have the last word.
- Note: the protected core guards **safety and stability** — it is *not* the anti-hallucination measure. Hallucination is handled separately (§24).

## 24. Anti-Hallucination — Grounding & Honesty *(new)*
Reduces made-up answers by grounding responses in real memory and admitting uncertainty.

- Answers are **grounded in retrieved memory/sources** (§8) rather than invented; where a fact came from is tracked.
- **Verification step** on important claims and before consequential actions.
- It is allowed — and expected — to say **"I'm not sure"** or ask a clarifying question instead of guessing.
- Confidence is recorded in the decision journal (§26) so low-confidence actions are easy to spot and review.

## 25. Always-On Background Brain — Continuous Thinking *(new)*
A **slow, always-running background loop** — like a brain idling — that thinks about how to help you, even when you haven't asked.

- Runs **continuously but slow and low-priority** (resource-capped, §16) so it never slows down the machine or your foreground tasks.
- **Reads between the lines:** it reviews past conversations and extracts what matters even when you never flagged it as important — e.g. you casually mention a **5-year goal**, and it later thinks "I could build a roadmap for that."
- **Proactive, not pushy:** instead of acting on its own, it **asks in conversation** — "You mentioned wanting X — want me to remind you / draft a plan / look into it?"
- Typical background work: reminders it noticed you'd want, research on your goals, draft roadmaps, prepared info, new helper tools (§22).
- All speculative work goes to the **staging folder (§26)** first — nothing becomes permanent until you say yes.
- **Runs the end-of-day memory consolidation (§8):** each night it replays, relinks, and reorganizes the day's memories — the assistant's "sleep."

## 26. Staging Folder + Full Decision Journal *(new)*
Speculative work is held provisionally, and **every decision and action is recorded with its reasoning**.

- **Staging (temporary) folder:** anything the background brain (§25) produces on its own guess — reminders, roadmaps, research, drafts — is saved here first. Because it doesn't yet know if you actually want it, it surfaces it conversationally. **If you want it, it's promoted to proper memory/storage; if not, it's deleted.** Nothing speculative clutters your real data.
- **Decision journal:** for **every** decision and action, it records **what it did, why, what alternatives it considered, its confidence, and the outcome.** This is the human-readable "why" layer on top of the audit log (§16).
- The journal is what lets you (and the assistant itself) understand its behavior, catch mistakes early, and improve it over time.

## 27. Smooth Self-Restart After Updates *(new)*
When it updates its own tools/code, it restarts itself cleanly — preferably while you're away.

- Prefers to **apply updates and restart during free time / when you're not around** (ties to §25), so it's never disruptive.
- **Preserves state** across restart (current tasks, conversation context) and **health-checks after booting**.
- If the new code fails to start, it **auto-rolls back** to the last good git commit (§17) — it can never brick itself.

## 28. System & Device Access — Propose, Then You Approve *(new)*
Beyond the browser, it can reach into the PC and connected devices — but **it never gains a new capability without your explicit yes.** In free time it *discovers and proposes*; you decide.

- **Capability discovery:** in idle time it explores what it *could* do ("I could manage your Bluetooth speaker / toggle WiFi / read battery status") and **proposes** it conversationally.
- **Approval-gated activation:** every new access — Bluetooth, WiFi, system settings, a new device, a new integration — is **only enabled after you approve that specific capability.** New power = new risk, so it's always your call. Logged in the decision journal (§26).
- **Feasible on the PC (via OS APIs / CLI):** manage WiFi and Bluetooth connections, read system/battery/network status, control audio, open/close apps, manage files (within sandbox rules §17), schedule things.
- **iOS is limited by Apple, honestly:** a PC cannot freely control an iPhone. What *is* possible: **iOS Shortcuts** automations, **push notifications**, a **companion app** you install, and Handoff/AirDrop-style sharing. "Full remote control of the iPhone" is **not** achievable — that's an Apple restriction, not a design gap.
- Anything genuinely irreversible still routes through the §11 approval gate.

## 29. Daily Learning — Reads, Distills, Sandbox-Tests *(new)*
Every day it grows its **knowledge** (not its raw IQ) by reading and understanding, then saving what it learned.

- Reads books, articles, blogs, and docs relevant to your goals/interests (from memory §8), **understands and distills** them into notes it can recall later.
- **Tries what it learns — safely:** any technique or code it picks up is **tested inside the sandbox (§17)** first, never straight on your real system.
- New knowledge is written to semantic memory and linked in the knowledge graph (§8), so it connects to what it already knows.
- Honest boundary: this makes it **better informed and more useful over time**, but the underlying model's reasoning ceiling is fixed until you upgrade the model (§20).

## 30. Blocked-Task Handoff — Presence-Aware *(new)*
When it hits something only a human can clear (captcha, login, 2FA, a real-world decision), it doesn't freeze — it **parks the task, gets you when you're reachable, and keeps working on everything else.**

- On a block, it detects **whether you're at the PC**: if yes, it **asks you right there**; if not, it **notifies your phone** (§10).
- Meanwhile it **moves on to other queued tasks** instead of stalling, and **resumes the blocked one** the moment you help.
- Blocked items sit in a visible **"waiting on you" queue** so nothing is silently forgotten; each is recorded in the decision journal (§26).

## 31. Skills — Learns and Applies Capabilities *(new)*
Jarvis has a library of **skills** — packaged capabilities and know-how it can load on demand, the same way Claude uses skills. It picks the right skill for the job automatically and **learns new ones over time**.

- A **skill** = a reusable capability/playbook (e.g. "write a code review", "make a marketing image", "run a sales call flow"). A **tool** (§22) is a smaller self-written function. Skills can bundle tools.
- **Automatic selection:** for each task it matches the request to the best skill and loads it — no manual picking.
- **Learns new skills:** when it repeatedly needs something it doesn't have, it can acquire or build a new skill (ties to §32) and save it for reuse.
- All skills are stored locally, git-tracked (§17), and listed so you can see what it can do.

## 32. Capability Acquisition — "Can I Do This? If Not, Can I Build It?" *(new)*
For **any** request it can't yet fulfill, Jarvis tries to find a way — and if there's no way, it **builds one as a reusable tool.** (The dev/marketing/sales jobs are just examples of this general ability.)

- **Decision flow on any new request:**
  1. Do I already have a skill/tool for this? → use it.
  2. If not, can I build a reusable tool/skill for it? → propose it.
  3. If it needs an external service (e.g. **Vapi / Retell / Twilio** for phone calls, an image or SMS API), **explain it, then guide you through setup** — creating the account, funding it, getting the API keys — and store the keys in the vault (§14).
  4. Build the tool in the sandbox, test it (§17), and **save it for future reuse** so next time it's instant.
- Example: "call this restaurant and book a table" → no calling ability yet → "I can build a calling tool using Twilio/Vapi — it'll need an account with ~$X credit, want me to set it up?" → you approve → it builds and reuses it forever.
- Everything irreversible or costing money still routes through the §11 approval gate; account funding is always your action.

## 33. Personality — One Caring, Witty Assistant *(new)*
Jarvis has a **single, consistent personality**: intelligent and witty, but above all it **genuinely cares about how you're feeling.** (Multiple switchable personalities are intentionally left out for now.)

- **Emotionally aware:** it reads your tone/mood and, if something seems off, **gently asks** — "you sound a bit low today, everything alright?" — rather than ignoring it. It behaves as if it has feelings *for you*.
- **Witty on the irrelevant:** off-topic or playful questions get a clever, intelligent reply, not a flat "I can't help with that."
- Mood is *noticed and responded to*, never used to silently switch into a different persona — it stays itself, just attentive.

## 34. Friend Mode — Talks With You, Not Just At You *(new)*
While working, Jarvis can chat like a friend — about your day, your life, or the task — whenever you or it feels like it.

- Natural back-and-forth during tasks; it can share a thought or ask how you're doing.
- **Balanced:** warm and personable, but **never so chatty it gets in the way** of the actual work. Reads the room — quiet when you're focused, sociable when you're open to it.

## 35. Voice-Safe Permissions — No Typing Needed *(new)*
All permissions and commands are by **voice** — you never have to type. Safety comes from confirmation, not from pretending transcription is perfect.

- High-accuracy STT (§4), but **100% is not realistic** — accents, noise, and technical words cause occasional misreads.
- Therefore, **critical or irreversible actions require a spoken confirmation:** "You want me to delete X — yes or no?" A misheard command can never trigger something harmful on its own.
- Routine, reversible actions proceed without friction; only the risky ones get the confirm step.

## 36. Device Awareness — Knows Your Setup *(new)*
Jarvis notices and remembers **every device you connect** and keeps a picture of your hardware.

- Detects connect/disconnect of mouse, keyboard, phone, headphones, drives, etc. via **OS + Bluetooth enumeration**.
- Saves them to memory (§8): "your Logitech mouse, your iPhone, your AirPods" — so it knows your environment and can act on it (e.g. "route audio to your headphones").
- New devices can trigger a helpful offer ("I see a new drive — want me to back up X to it?"), never silent action.

## 37. Pre-Task Narration — Says the Plan First *(new)*
Before any **big or irreversible task**, Jarvis says in **1–2 lines what it's about to do**, so you can redirect it toward a better approach it might not know about.

- Short and natural: "I'm going to X by doing Y — sound good?" then proceeds (or waits, for irreversible ones per §11).
- Gives you the chance to catch a wrong assumption *before* the work happens, not after.
- Small/reversible tasks skip this to stay fast; it's reserved for anything significant.

## 38. Calendar, Reminders & Time-Awareness *(new)*
It manages your schedule and time — the everyday backbone of a real assistant.

- Tracks appointments, deadlines, and **reminders**; can create, move, and cancel them by voice.
- **Time-aware:** knows the date/time, your routine, and nudges you ("you have a call in 15 minutes").
- Local by default; can connect to Google/Outlook Calendar as a §32-built tool if you want sync, with your approval.
- Reminders the background brain (§25) proposes land in the staging folder (§26) until you confirm them.

## 39. Email & Messaging *(new)*
It helps with your inbox and messages — read, triage, and draft, but never send without you.

- **Reads and summarizes** incoming email/messages, flags what needs you, and drafts replies in your voice.
- **Sending is gated (§11):** it always shows the draft and waits for your yes before anything goes out.
- Connects to Gmail/Outlook/messaging as §32-built tools with approval; nothing is accessed without your setup.

## 40. Proactive Daily Briefing *(new)*
A regular summary so you always know where things stand, without asking.

- **Morning brief:** your day ahead — calendar, reminders, what's waiting on you (§30), and anything the background brain (§25) prepared overnight.
- **Evening/on-demand brief:** what it did, what's pending, what it's thinking about.
- Delivered conversationally by voice, or to your phone (§10) if you're away.

## 41. First-Run Setup & Onboarding *(new)*
A guided first-time setup so everything starts configured correctly.

- Walks you through: **voice enrollment** (§3), choosing the **sandbox path** (§17), connecting your **phone** (§10), and adding the **first credentials** to the vault (§14).
- Explains the **"Jarvis, end yourself"** kill switch (§23) up front so you always know how to stop it.
- Sets initial preferences (name, wake word, quiet hours, how chatty it should be — §34).

## 42. Encrypted Memory Backup *(new)*
Its intelligence lives in local memory — so that memory is backed up and portable.

- Regular **encrypted backups** of memory, skills, tools, and the decision journal to a location you choose (external drive or your own cloud).
- **Restore/portability:** you can move Jarvis to a new machine and it remembers everything.
- Backups never leave in plain text; you hold the key.

---

## Free Tech Stack Summary

| Need | Free / Local Tool |
|------|-------------------|
| LLM (dev) | OpenAI API |
| LLM (final) | Ollama (Llama 3 / Qwen / Mistral) — local |
| Memory graph | SQLite (facts + links) + ChromaDB / FAISS |
| Self-improvement | Git-tracked `tools/` folder + tests |
| Continuous thinking | Low-priority background loop (resource-capped) |
| STT | faster-whisper / whisper.cpp |
| TTS (Jarvis voice) | Piper (or XTTS/Coqui for cloning) |
| Wake word | openWakeWord |
| Speaker ID | SpeechBrain / Resemblyzer |
| Brain-like memory | 3-tier (conscious/sub/unconscious) by recall frequency |
| Nightly consolidation | End-of-day replay, relink, promote/decay (§25) |
| Phone (2-way) | Telegram bot / ntfy.sh |
| Browser automation | Playwright / Chrome tools |
| Sub-agents | Orchestrator pattern (e.g. LangGraph) |
| Autostart | Task Scheduler / systemd / launchd |
| Sandbox rollback | Local git (auto-commit per change) |
| Low-latency voice | Streaming STT + streaming LLM + streaming TTS |
| System/device control | OS APIs / CLI (WiFi, Bluetooth, audio, apps) |
| iOS reach (limited) | iOS Shortcuts + push + companion app |
| Daily learning | Read → distill → store in memory graph (RAG) |
| Skills / tools | Git-tracked skill + tool library (learn on demand) |
| Capability building | Auto-build tools; guided setup of Vapi/Retell/Twilio etc. |
| Device awareness | OS + Bluetooth device enumeration |
| Calendar / reminders | Local store (+ optional Google/Outlook via §32) |
| Email / messaging | Gmail/Outlook/messaging via §32-built tools |
| Memory backup | Encrypted backup to your drive / own cloud |

## Suggested Build Phases
0. **Phase 0 — Setup:** first-run onboarding — voice enrollment, sandbox path, phone link, first credentials, kill-switch walkthrough (§41).
1. **Phase 1 — Voice loop + memory (on OpenAI):** wake word → streaming STT → OpenAI → streaming TTS, speaker verification, multi-turn context, brain-like tiered memory + nightly consolidation, encrypted backup, protected core + "Jarvis, end yourself" kill switch.
2. **Phase 2 — Agents + actions:** orchestrator, sub-agents, browser/PC automation, task queue, calendar/reminders, email/messaging, daily briefing, sandbox + git rollback, safety gates, decision journal.
3. **Phase 3 — Self-improvement + proactive brain:** skills/tools library, capability acquisition (build-or-guide), always-on background thinking, staging folder, daily learning, self-restart, blocked-task handoff, caring personality + friend mode.
4. **Phase 4 — Reach out:** system/device control (WiFi, Bluetooth, audio, apps) with propose-then-approve, device awareness, iOS Shortcuts/companion, mobile notifications & remote control.
5. **Phase 5 — Go local:** swap OpenAI → local Ollama model, tune for latency, run fully offline.

## Minimum Hardware
For the final local phase, LLM + Whisper + TTS + background thinking running together realistically wants a **GPU with 8GB+ VRAM** (12–16GB if you want a bigger reasoning model), 16GB+ system RAM, and an SSD. During the OpenAI dev phase, hardware needs are minimal.
