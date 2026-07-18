# JARVIS — Personal AI Assistant

Private, always-on, voice-driven personal assistant. See the design docs in the parent folder:
`JARVIS_Requirements.md`, `JARVIS_Technical_Architecture.md`, `JARVIS_Development_Plan.md`.

This repository is the **implementation**, built phase by phase.

---

## Phase 0 — Safety Foundation (this build)

Phase 0 is deliberately boring and non-negotiable: it establishes the **safety spine** that every
later capability runs inside. Nothing "smart" happens yet — this is the seatbelt before the engine.

What's included:

| Module | Purpose | Spec |
|---|---|---|
| `jarvis/core/sandbox_guard.py` | Guarded file I/O choke-point — writes only inside the sandbox; everything else read-only. | §17 |
| `jarvis/core/policy.py` | The rules: what paths are writable, what actions are irreversible. Lives in the immutable core. | §11, §17 |
| `jarvis/core/approval.py` | Reversibility check before every action; irreversible → ask the human. | §11 |
| `jarvis/core/kill_switch.py` | Independent "Jarvis, end yourself" listener that hard-kills the process group. | §23 |
| `jarvis/vault/vault.py` | Encrypted secrets store; master key in the OS keychain. | §14 |
| `jarvis/audit/audit_log.py` | Append-only audit trail of every action. | §16 |
| `jarvis/config/config.py` | Load/save configuration (sandbox path, preferences). | §41 |
| `jarvis/onboarding/wizard.py` | First-run setup: sandbox path, git init, first secret, kill-switch explainer. | §41 |
| `jarvis/main.py` | Wires the spine together; demo entry point. | §13 |

The `tests/` folder contains the **red-team suite** — it actively tries to break out of the sandbox
(path traversal, symlink escape, absolute-path escape) and must block 100% of attempts.

---

## Setup (macOS / Apple Silicon)

```bash
cd jarvis
./setup.sh          # creates .venv, installs deps
source .venv/bin/activate
python -m jarvis.main --onboard   # first-run setup wizard
```

## Run the tests

```bash
source .venv/bin/activate
pytest -v
```

All tests — especially the red-team sandbox-escape suite — must pass before moving to Phase 1.

---

## Phase 1 — Voice Loop + Memory (this build)

The first *usable* Jarvis: a swappable brain, brain-like memory, and a voice pipeline.

| Module | Purpose | Spec |
|---|---|---|
| `jarvis/llm/` | Swappable brain: `ModelAdapter` interface + OpenAI + Mock + router (local/OpenAI/Claude). | §1, §20 |
| `jarvis/memory/` | Brain-like tiered memory (conscious/subconscious/unconscious), recall-driven, nightly consolidation. | §8 |
| `jarvis/brain/` | Orchestrator loop, multi-turn dialog window, base persona, voice-safe confirmation, TTFW timing. | §13, §19, §35, §18 |
| `jarvis/voice/` | Wake word, speaker verify, STT, TTS interfaces + text stubs + lazy Mac backends. | §3, §4, §5 |
| `jarvis/tracing/` | Span tracer (no-op / local JSONL / LangSmith-ready) across the whole pipeline. | §2A.5 |
| `jarvis/backup/` | Encrypted memory backup + restore. | §42 |

### Run it (text/chat mode — works offline, no extra deps)

```bash
source .venv/bin/activate
python -m jarvis.main --onboard      # if you haven't already
python -m jarvis.main chat           # talk to Jarvis (brain + memory)
```

Chat mode runs on the offline **MockAdapter** by default. To use the **real OpenAI brain**,
store your key during onboarding (secret name `openai_api_key`) and `pip install openai` —
the brain auto-switches. Traces are written to `~/.jarvis/logs/traces.jsonl`.

### Voice mode (real, always-on)

```bash
pip install -r requirements-voice.txt   # openWakeWord, faster-whisper, Kokoro, SpeechBrain
brew install ffmpeg espeak-ng           # system tools Whisper/Kokoro need

python -m jarvis.main voice-enroll       # (optional) record your voiceprint → owner-only
python -m jarvis.main voice              # always-on: say "Hey Jarvis" to start talking
```

**How it behaves** (the Jarvis interaction model):
- Mic is always on but only listens for **"Hey Jarvis"** while idle.
- Saying it **arms a session** — after that you just talk; no need to repeat the wake word.
- Each utterance: it checks it's **you** (if enrolled), transcribes, and decides if you're
  **talking to it** vs. to a person/phone — replying only when addressed, else just listening.
- After ~30s with no conversation (you're done / walked away) it goes back to idle.

First run downloads the models (once). If audio deps are missing it falls back to text-stub
voice mode automatically. Grant Terminal microphone permission when macOS asks.

### Backup

```bash
python -m jarvis.main backup            # encrypted snapshot of ~/.jarvis/memory
```

---

## Command Reference (all commands)

Always run inside the activated venv (`source .venv/bin/activate`), and use the
`python -m jarvis.main ...` form (avoids the pyenv `pytest`/shim issue).

| Command | What it does |
|---|---|
| `python -m jarvis.main --onboard` | First-run setup: sandbox path, git init, store a secret (e.g. `openai_api_key`), kill-switch explainer. |
| `python -m jarvis.main chat` | Text conversation with the brain + memory (no audio). |
| `python -m jarvis.main voice` | Real always-on voice: say **"Hey Jarvis"**, then talk. |
| `python -m jarvis.main voice-enroll` | Record your voiceprint (3 clips) → Jarvis responds only to you. |
| `python -m jarvis.main voice-test tts` | Diagnostics: play a test sentence (is audio out working?). |
| `python -m jarvis.main voice-test stt` | Diagnostics: record 4s and print the transcript (does it hear you?). |
| `python -m jarvis.main voice-test mic` | Diagnostics: live mic levels for 10s (are levels reaching it?). |
| `python -m jarvis.main set-model gpt-4o` | Set the main brain model (e.g. `gpt-4o`, `gpt-4o-mini`). |
| `python -m jarvis.main set-model` | Show the current brain model. |
| `python -m jarvis.main backup` | Encrypted snapshot of memory. |
| `python -m jarvis.main` | Phase 0 safety demo (write / read / outside / send / kill). |
| `python -m pytest -q` | Run the full test suite. |

### Emergency stop

Say (or type) **"Jarvis, end yourself"** at any time — it shuts everything down
immediately and cannot be disabled by Jarvis. (Robust to the STT mishearing "end" as "and".)

### Environment variables (voice tuning)

Set before the command, e.g. `JARVIS_STT_MODEL=large-v3 python -m jarvis.main voice`.

| Variable | Default | Purpose |
|---|---|---|
| `JARVIS_STT_MODEL` | `medium.en` | Whisper model. `small.en` (faster) · `medium.en` (balanced) · `large-v3` (most accurate). |
| `JARVIS_WAKE_MODE` | `stt` | Wake detection. `stt` (robust, reuses Whisper) · `model` (openWakeWord). |
| `JARVIS_ADDRESSING` | `1` | Smart "is he talking to me?" check. `0` = off (reply to everything in a session). |
| `JARVIS_ADDRESSING_MODEL` | `gpt-4o` | Model for that check (independent of the main brain). |
| `JARVIS_VOICE_DEBUG` | `1` | Verbose voice logs (wake scores, capture, timing). `0` = quiet. |

### Recommended setups

```bash
# Smartest (best replies + reliable addressing), a bit pricier/slower:
python -m jarvis.main set-model gpt-4o
python -m jarvis.main voice

# Balanced (cheap chat brain, reliable addressing):
python -m jarvis.main set-model gpt-4o-mini      # gpt-4o still used for addressing
python -m jarvis.main voice

# Cheapest / fastest:
JARVIS_ADDRESSING=0 JARVIS_STT_MODEL=small.en python -m jarvis.main voice
```

---

## Target platform

Primary: **macOS on Apple Silicon** (M-series). The code is written to stay cross-platform where
cheap, but acceleration and autostart choices assume Mac first. Later phases add
whisper.cpp (Metal/Neural Engine), Kokoro TTS, Ollama, etc.
