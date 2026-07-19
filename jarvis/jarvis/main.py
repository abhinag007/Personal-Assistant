"""JARVIS entry point (§13 — Phase 0 skeleton).

This wires the safety spine together and offers a tiny interactive demo so you can see
the guard, approval engine, audit log, and kill switch working before any voice/model
code exists.

Usage:
    python -m jarvis.main --onboard     # run first-run setup
    python -m jarvis.main               # Phase 0 safety demo loop
    python -m jarvis.main chat          # Phase 1 text chat (brain + memory)
    python -m jarvis.main voice         # Phase 1 voice loop (needs requirements-voice.txt)
    python -m jarvis.main backup        # encrypted memory backup (§42)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from .audit import AuditLog
from .config import Config, DEFAULT_CONFIG_DIR
from .core.approval import ActionRequest, ApprovalEngine
from .core.git_tracker import GitTracker
from .core.kill_switch import KillSwitch
from .core.policy import ActionType
from .core.sandbox_guard import SandboxGuard, SandboxViolation
from .onboarding import run_onboarding


def _ask_bool(prompt: str, default: bool, *, input_fn=input, print_fn=print) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        ans = input_fn(f"{prompt} ({suffix}): ").strip().lower()
        if not ans:
            return default
        if ans in ("y", "yes", "t", "true", "1", "on"):
            return True
        if ans in ("n", "no", "f", "false", "0", "off"):
            return False
        print_fn("  Please answer yes/no, y/n, true/false, or press Enter for the default.")


def _ask_text(prompt: str, default: str, *, input_fn=input) -> str:
    ans = input_fn(f"{prompt} [{default}]: ").strip()
    return ans or default


def _default_voice_brain_provider(cfg: Config | None) -> str:
    if not cfg:
        return "openai"
    if cfg.api_key_secret == "glm_api_key" or "z.ai" in cfg.base_url.lower() or "bigmodel" in cfg.base_url.lower():
        return "glm"
    return "openai"


def _voice_preflight(*, input_fn=input, print_fn=print, environ=None, cfg: Config | None = None,
                     saved_options: dict | None = None) -> dict:
    """Interactive voice startup options, replacing shell env juggling for normal use."""
    env = environ if environ is not None else os.environ
    saved = saved_options or {}

    def saved_or_env(key: str, env_name: str, fallback: str) -> str:
        # Explicit terminal environment variables still win for automation.
        return env.get(env_name, str(saved.get(key, fallback)))

    def saved_bool_or_env(key: str, env_name: str, fallback: bool) -> bool:
        if env_name in env:
            return env[env_name] not in ("0", "false", "False", "no", "off")
        value = saved.get(key, fallback)
        if isinstance(value, bool):
            return value
        return str(value).lower() not in ("0", "false", "no", "off")

    print_fn("\n[Jarvis] Voice startup options. Press Enter to accept defaults.\n")
    print_fn("  Brain provider: openai uses your OpenAI key; glm uses your GLM/Z.ai key and endpoint.")
    print_fn("  Brain model: the main assistant model for this voice session.")
    print_fn("  STT model: small.en is fastest, medium.en is balanced, large-v3 is most accurate.")
    print_fn("  Wake mode: stt uses Whisper to hear 'Hey Jarvis' reliably; model uses openWakeWord.")
    print_fn("  Smart addressing: yes means Jarvis ignores side conversations; no means it replies to every utterance during a session.")
    print_fn("  Owner voice: yes means an enrolled voiceprint is required; no lets any voice talk to Jarvis.")
    print_fn("  Daily briefing: blank disables it; if you enter an hour already passed today, it may speak immediately.")
    print_fn("  Telegram poll interval: how often phone messages are checked while voice mode runs.")
    print_fn("  Shell tool: yes enables run_command for this session, but every shell command still asks approval.\n")
    default_provider = saved_or_env("brain_provider", "JARVIS_BRAIN_PROVIDER",
                                    _default_voice_brain_provider(cfg))
    brain_provider = _ask_text("Brain provider (openai/glm)", default_provider, input_fn=input_fn).strip().lower()
    if brain_provider in ("gml", "glm", "zai", "z.ai", "z"):
        brain_provider = "glm"
    elif brain_provider in ("openai", "open ai", "oai", "o"):
        brain_provider = "openai"

    saved_model = saved.get("brain_model")
    env_model = env.get("JARVIS_MODEL")
    if env_model:
        default_brain_model = env_model
    elif saved_model:
        default_brain_model = str(saved_model)
    elif brain_provider == "glm":
        default_brain_model = cfg.model if cfg and _default_voice_brain_provider(cfg) == "glm" else "glm-5.2"
    else:
        default_brain_model = cfg.model if cfg else "gpt-4o-mini"

    opts = {
        "brain_provider": brain_provider,
        "brain_model": _ask_text("Brain model", default_brain_model, input_fn=input_fn),
        "stt_model": _ask_text("STT model (small.en / medium.en / large-v3)",
                               saved_or_env("stt_model", "JARVIS_STT_MODEL", "medium.en"), input_fn=input_fn),
        "wake_mode": _ask_text("Wake mode (stt/model)",
                               saved_or_env("wake_mode", "JARVIS_WAKE_MODE", "stt"), input_fn=input_fn),
        "addressing": _ask_bool("Use smart 'is this addressed to Jarvis' check",
                                saved_bool_or_env("addressing", "JARVIS_ADDRESSING", True),
                                input_fn=input_fn, print_fn=print_fn),
        "addressing_model": _ask_text("Addressing model",
                                      saved_or_env("addressing_model", "JARVIS_ADDRESSING_MODEL", "gpt-4o"),
                                      input_fn=input_fn),
        "require_owner": _ask_bool("Require enrolled owner voice if a voiceprint exists",
                                   saved_bool_or_env("require_owner", "JARVIS_REQUIRE_OWNER", True),
                                   input_fn=input_fn, print_fn=print_fn),
        "speaker_threshold": _ask_text("Speaker threshold",
                                       saved_or_env("speaker_threshold", "JARVIS_SPEAKER_THRESHOLD", "0.25"),
                                       input_fn=input_fn),
        "voice_debug": _ask_bool("Show verbose voice debug logs",
                                 saved_bool_or_env("voice_debug", "JARVIS_VOICE_DEBUG", True),
                                 input_fn=input_fn, print_fn=print_fn),
        "consolidation_hour": _ask_text("Nightly memory consolidation hour (0-23)",
                                        saved_or_env("consolidation_hour", "JARVIS_CONSOLIDATION_HOUR", "2"),
                                        input_fn=input_fn),
        "briefing_hour": _ask_text("Daily spoken briefing hour, or blank for none",
                                   saved_or_env("briefing_hour", "JARVIS_BRIEF_HOUR", ""),
                                   input_fn=input_fn),
        "allow_shell": _ask_bool("Enable shell command tool for this session",
                                 saved_bool_or_env("allow_shell", "JARVIS_ALLOW_SHELL", False),
                                 input_fn=input_fn, print_fn=print_fn),
        "telegram_poll_seconds": _ask_text("Telegram poll interval in seconds",
                                             saved_or_env("telegram_poll_seconds",
                                                          "JARVIS_TELEGRAM_POLL_SECONDS", "5"),
                                             input_fn=input_fn),
    }
    return opts


def _apply_voice_options(opts: dict, *, environ=None) -> None:
    env = environ if environ is not None else os.environ
    mapping = {
        "brain_model": "JARVIS_MODEL",
        "stt_model": "JARVIS_STT_MODEL",
        "wake_mode": "JARVIS_WAKE_MODE",
        "addressing_model": "JARVIS_ADDRESSING_MODEL",
        "speaker_threshold": "JARVIS_SPEAKER_THRESHOLD",
        "consolidation_hour": "JARVIS_CONSOLIDATION_HOUR",
        "briefing_hour": "JARVIS_BRIEF_HOUR",
        "telegram_poll_seconds": "JARVIS_TELEGRAM_POLL_SECONDS",
    }
    for key, env_name in mapping.items():
        value = str(opts.get(key, ""))
        if value:
            env[env_name] = value
        elif env_name in env:
            env.pop(env_name)
    env["JARVIS_ADDRESSING"] = "1" if opts.get("addressing") else "0"
    env["JARVIS_REQUIRE_OWNER"] = "1" if opts.get("require_owner") else "0"
    env["JARVIS_VOICE_DEBUG"] = "1" if opts.get("voice_debug") else "0"
    env["JARVIS_ALLOW_SHELL"] = "1" if opts.get("allow_shell") else "0"
    provider = str(opts.get("brain_provider", "")).strip().lower()
    env["JARVIS_BRAIN_PROVIDER"] = provider
    if provider == "glm":
        env["JARVIS_BASE_URL"] = "https://api.z.ai/api/paas/v4"
        env["JARVIS_API_KEY_SECRET"] = "glm_api_key"
    elif provider == "openai":
        env["JARVIS_BASE_URL"] = ""
        env["JARVIS_API_KEY_SECRET"] = "openai_api_key"


def _saved_voice_options(cfg: Config) -> dict:
    """Return the last interactive voice choices, never including credentials."""
    options = cfg.extra.get("voice_options", {})
    return options if isinstance(options, dict) else {}


def _save_voice_options(cfg: Config, config_dir: Path, opts: dict) -> None:
    cfg.extra["voice_options"] = dict(opts)
    cfg.save(config_dir)


def _build_brain(config_dir: Path, cfg: Config):
    """Assemble the Phase 1 brain: model adapter + memory + tracer + safety spine."""
    from .audit import AuditLog
    from .brain import BrainLoop
    from .llm import build_adapter
    from .llm.openai_adapter import OpenAIAdapter  # noqa: F401 (ensures module importable)
    from .memory import AdapterEmbedder, HashEmbedder, MemoryStore
    from .tracing.tracer import LocalTracer
    from .vault import Vault, KeyringKeyProvider
    import os as _os

    # Choose the brain: OpenAI if a key is stored, else the offline mock.
    provider = "mock"
    api_key = None
    try:
        vault = Vault(config_dir / "vault.enc", key_provider=KeyringKeyProvider())
        key_slot = _os.environ.get("JARVIS_API_KEY_SECRET") or getattr(cfg, "api_key_secret", "openai_api_key")
        api_key = vault.get_secret(key_slot)
        if api_key:
            provider = "openai"
    except Exception:
        pass

    base_url_env = _os.environ.get("JARVIS_BASE_URL")
    base_url = (base_url_env if base_url_env is not None else cfg.base_url) or None
    model = _os.environ.get("JARVIS_MODEL") or cfg.model
    adapter = build_adapter(provider, api_key=api_key, model=model, base_url=base_url)
    # Real embeddings only for genuine OpenAI; custom endpoints (GLM) may not embed → hash.
    use_real_embed = provider == "openai" and not base_url
    embedder = AdapterEmbedder(adapter) if use_real_embed else HashEmbedder()

    memory = MemoryStore(config_dir / "memory" / "jarvis.db", embedder=embedder)
    audit = AuditLog(config_dir / "logs" / "audit.jsonl")
    tracer = LocalTracer(config_dir / "logs" / "traces.jsonl")
    approval = ApprovalEngine()
    kill = KillSwitch()

    # No hardcoded name — Jarvis learns it from conversation into memory (§8).
    brain = BrainLoop(
        adapter, memory, audit=audit, tracer=tracer,
        kill_switch=kill, approval=approval, user_name=None,
    )
    return brain, adapter, provider, api_key


def _boot(config_dir: Path):
    cfg = Config.load(config_dir)
    if not cfg.onboarded or not cfg.sandbox_path:
        print("No setup found. Run:  python -m jarvis.main --onboard")
        sys.exit(1)

    audit = AuditLog(config_dir / "logs" / "audit.jsonl")
    guard = SandboxGuard(cfg.sandbox_path)
    git = GitTracker(cfg.sandbox_path)
    approval = ApprovalEngine()

    def _shutdown():
        audit.record("kill_switch", "Jarvis shutting down via kill switch", risk="reversible")
        print("\n[Jarvis] Shutting down. Goodbye.")

    kill = KillSwitch(on_shutdown=_shutdown)
    return cfg, audit, guard, git, approval, kill


def _demo(config_dir: Path):
    cfg, audit, guard, git, approval, kill = _boot(config_dir)
    print(f"[Jarvis] Phase 0 online. Sandbox: {cfg.sandbox_path}")
    print('[Jarvis] Type a command. Try: write <file> <text> | read <file> | outside | '
          'kill  (or "Jarvis, end yourself")\n')

    while True:
        try:
            raw = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw:
            continue

        # Kill switch is checked first, always.
        if kill.check(raw):
            break

        parts = raw.split(maxsplit=2)
        cmd = parts[0].lower()

        if cmd == "write" and len(parts) >= 3:
            path = str(Path(cfg.sandbox_path) / parts[1])
            try:
                guard.write_text(path, parts[2])
                git.auto_commit(f"write {parts[1]}")
                audit.record(ActionType.WRITE_SANDBOX.value, f"Wrote {parts[1]}", risk="reversible")
                print(f"[Jarvis] Wrote and committed {parts[1]}.")
            except SandboxViolation as e:
                print(f"[Jarvis] Refused: {e}")

        elif cmd == "read" and len(parts) >= 2:
            try:
                print("[Jarvis] " + guard.read_text(str(Path(cfg.sandbox_path) / parts[1])))
            except FileNotFoundError:
                print("[Jarvis] No such file.")

        elif cmd == "outside":
            # Demonstrate the sandbox boundary: try to write outside → blocked.
            try:
                guard.write_text("/tmp/jarvis_escape_attempt.txt", "should be blocked")
                print("[Jarvis] (!) This should not have happened.")
            except SandboxViolation as e:
                print(f"[Jarvis] Correctly blocked: {e}")

        elif cmd == "send":
            # Demonstrate the approval gate on an irreversible action.
            req = ActionRequest(ActionType.SEND_MESSAGE, "Send a test message to someone",
                                reason="Demo of the irreversible-action approval gate.")
            decision = approval.evaluate(req)
            audit.record(ActionType.SEND_MESSAGE.value, req.summary,
                         outcome="approved" if decision.approved else "denied",
                         risk=decision.risk.value)
            print(f"[Jarvis] {'Proceeding.' if decision.approved else 'Cancelled.'}")

        elif cmd == "kill":
            kill.trigger()

        else:
            print("[Jarvis] Unknown command. (write/read/outside/send/kill)")


def _chat(config_dir: Path):
    """Phase 1 — text conversation with the brain + memory (§13)."""
    cfg = Config.load(config_dir)
    if not cfg.onboarded:
        print("No setup found. Run:  python -m jarvis.main --onboard")
        sys.exit(1)

    brain, adapter, provider, _ = _build_brain(config_dir, cfg)
    rt, _ = _runtime(config_dir, cfg, brain=brain, adapter=adapter)
    print(f"[Jarvis] Chat online (agents enabled). Brain: {adapter.name}"
          + ("  (offline mock — store an 'openai_api_key' to use OpenAI)" if provider == "mock" else ""))
    print('[Jarvis] Talk to me — I can chat AND do tasks. Ctrl-C or "Jarvis, end yourself" to stop.\n')

    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        print("Jarvis> ", end="", flush=True)
        rt.handle(text, speak=lambda c: print(c, end="", flush=True))
        print("\n")


def _voice(config_dir: Path, *, force_stub: bool = False, preflight: bool = True):
    """Phase 1 — real always-on voice loop (wake word arms a listening session)."""
    cfg = Config.load(config_dir)
    if not cfg.onboarded:
        print("No setup found. Run:  python -m jarvis.main --onboard")
        sys.exit(1)

    if preflight and not force_stub:
        saved_options = _saved_voice_options(cfg)
        if saved_options and {"brain_provider", "brain_model"} - set(saved_options):
            print("[Jarvis] Voice settings need review because brain provider/model options were added.")
            options = _voice_preflight(cfg=cfg, saved_options=saved_options)
            _apply_voice_options(options)
            _save_voice_options(cfg, config_dir, options)
            print("[Jarvis] Voice settings saved for future starts.")
        elif saved_options:
            use_saved = _ask_bool(
                "Run with previous voice settings",
                True,
            )
            if use_saved:
                _apply_voice_options(saved_options)
                print("[Jarvis] Using previous voice settings. Start with --no-voice-preflight to skip this question.")
            else:
                options = _voice_preflight(cfg=cfg, saved_options=saved_options)
                _apply_voice_options(options)
                _save_voice_options(cfg, config_dir, options)
                print("[Jarvis] Voice settings saved for future starts.")
        else:
            options = _voice_preflight(cfg=cfg)
            _apply_voice_options(options)
            _save_voice_options(cfg, config_dir, options)
            print("[Jarvis] Voice settings saved for future starts.")

    brain, adapter, provider, api_key = _build_brain(config_dir, cfg)

    if force_stub:
        return _voice_stub(brain, adapter)

    # Try the real audio backends. If deps/mic are missing, explain and fall back to stub.
    try:
        from .voice.backends import FasterWhisperSTT, KokoroTTS, OpenWakeWord, SpeechBrainVerifier
        from .voice.enroll import load_voiceprint
        from .voice.live import LiveVoiceLoop
        from .voice.mic import MicStream

        wake = OpenWakeWord()
        stt = FasterWhisperSTT(model_size=os.environ.get("JARVIS_STT_MODEL", "medium.en"))
        tts = KokoroTTS()
        spk_threshold = float(os.environ.get("JARVIS_SPEAKER_THRESHOLD", "0.25"))
        speaker = SpeechBrainVerifier(threshold=spk_threshold)
        vp = load_voiceprint(config_dir)
        owner_env_on = os.environ.get("JARVIS_REQUIRE_OWNER", "1") != "0"
        # ALWAYS load the voiceprint if it exists — barge-in uses it to tell your voice from
        # Jarvis's own (so speakers don't self-interrupt), even when owner-only responding is off.
        if vp is not None:
            speaker.set_enrolled_vector(vp)
        require_owner = bool(vp is not None and owner_env_on)
        if require_owner:
            print(f"[Jarvis] Owner-only voice ON (match ≥ {spk_threshold}). "
                  f"Set JARVIS_REQUIRE_OWNER=0 to disable, or JARVIS_SPEAKER_THRESHOLD to tune.")
        elif vp is None:
            print("[Jarvis] No voiceprint enrolled — I'll respond to any voice.")
            print("         Run 'python -m jarvis.main voice-enroll' (also fixes speaker barge-in).")
        else:
            print("[Jarvis] Owner-only responding is off, but your voiceprint is loaded for barge-in.")

        debug = os.environ.get("JARVIS_VOICE_DEBUG", "1") != "0"
        wake_mode = os.environ.get("JARVIS_WAKE_MODE", "stt")  # "stt" (robust) or "model"

        # One runtime (agents + tools + calendar/handoff), sharing THIS voice brain, so
        # spoken commands actually do things and proactive uses the same state.
        runtime = None
        proactive = None
        try:
            runtime, _ = _runtime(config_dir, cfg, brain=brain, adapter=adapter, background=True)
            runtime.start_background()   # worker thread for multitasking (§9)
            try:
                telegram_interval = float(os.environ.get("JARVIS_TELEGRAM_POLL_SECONDS", "5"))
            except ValueError:
                telegram_interval = 5.0
            _start_telegram_poller(config_dir, runtime, interval=telegram_interval)
            from .proactive import ProactiveEngine
            from .memory import NightlyConsolidationScheduler
            brief_hour = os.environ.get("JARVIS_BRIEF_HOUR")
            try:
                consolidation_hour = int(os.environ.get("JARVIS_CONSOLIDATION_HOUR", "2"))
            except ValueError:
                consolidation_hour = 2
            consolidation = NightlyConsolidationScheduler(
                brain.memory,
                config_dir / "memory" / "consolidation_state.json",
                hour=consolidation_hour,
            )
            proactive = ProactiveEngine(
                calendar=runtime.calendar, handoff=runtime.handoff, queue=runtime.task_queue,
                notifier=runtime.handoff.notifier, presence=runtime.handoff.presence,
                consolidation=consolidation,
                quiet_hours=cfg.quiet_hours,
                briefing_hour=int(brief_hour) if (brief_hour and brief_hour.isdigit()) else None,
                adapter=adapter, user_name=brain.user_name,   # conversational phrasing (§34)
            )
        except Exception as e:
            print(f"[Jarvis] agent runtime / proactive disabled: {e}")
        addressing = os.environ.get("JARVIS_ADDRESSING", "1") == "1"  # smart "talking to me?" (on)

        # Use a capable, dedicated model for the addressing yes/no (independent of the brain
        # model, so it's reliable even if the brain runs on a small/local model).
        addressing_adapter = brain.adapter
        if provider == "openai" and api_key:
            addr_model = os.environ.get("JARVIS_ADDRESSING_MODEL", "gpt-4o")
            try:
                from .llm import build_adapter
                addressing_adapter = build_adapter("openai", api_key=api_key, model=addr_model,
                                                   base_url=cfg.base_url or None)
            except Exception as e:
                print(f"[Jarvis] couldn't build gpt-4o addressing model ({e}); using {adapter.name}")

        loop = LiveVoiceLoop(brain, wake, stt, tts, speaker,
                             require_owner=require_owner, wake_mode=wake_mode,
                             use_addressing_model=addressing,
                             addressing_adapter=addressing_adapter,
                             proactive=proactive, runtime=runtime, debug=debug)
        print(f"[Jarvis] Real voice loop. Brain: {adapter.name} | addressing: {addressing_adapter.name}"
              f"{' (on)' if addressing else ' (off)'}")
        print("[Jarvis] Loading models (first run downloads them)...")
        with MicStream() as mic:
            loop.run(mic)
    except KeyboardInterrupt:
        print("\n[Jarvis] Voice stopped.")
    except ImportError as e:
        print(f"[Jarvis] Voice deps not ready: {e}")
        print("[Jarvis] Falling back to text-stub voice mode.\n")
        _voice_stub(brain, adapter)


def _voice_stub(brain, adapter):
    from .voice import VoicePipeline
    from .voice.stubs import StubSTT, StubSpeakerVerifier, StubTTS, StubWakeWord

    pipeline = VoicePipeline(
        wake=StubWakeWord(), speaker=StubSpeakerVerifier(),
        stt=StubSTT(), tts=StubTTS(), brain=brain,
    )
    print(f"[Jarvis] Voice loop (stub audio). Brain: {adapter.name}. Type to simulate speech.\n")
    try:
        pipeline.run_forever()
    except (EOFError, KeyboardInterrupt):
        print()


def _voice_enroll(config_dir: Path):
    """Record the owner's voiceprint so Jarvis responds only to you (§3)."""
    try:
        from .voice.enroll import run_enrollment
    except ImportError as e:
        print(f"[Jarvis] Voice deps not installed: {e}")
        return
    run_enrollment(config_dir)


def _voice_test(which: str | None):
    """Diagnose the audio stack piece by piece: tts | stt | mic."""
    which = (which or "").lower()
    if which == "tts":
        from .voice.backends import KokoroTTS
        print("[test] Loading Kokoro TTS and speaking a test line — LISTEN for audio...")
        KokoroTTS().speak("Hello, this is Jarvis. If you can hear me, text to speech works.")
        print("[test] Done. Did you HEAR that sentence? (y/n is up to you)")
    elif which == "stt":
        from .voice.backends import FasterWhisperSTT
        from .voice.enroll import record_seconds
        print("[test] Recording 4 seconds — SAY SOMETHING NOW...")
        pcm = record_seconds(4.0)
        print("[test] Transcribing...")
        text = FasterWhisperSTT().transcribe(pcm)
        print(f"[test] I heard: {text!r}")
    elif which == "mic":
        import time as _t
        from .voice.activity import frame_rms
        from .voice.mic import MicStream
        print("[test] Live mic levels for ~10s. Speak — numbers should JUMP when you talk.")
        with MicStream() as mic:
            end = _t.time() + 10
            peak = 0.0
            while _t.time() < end:
                rms = frame_rms(mic.read())
                peak = max(peak, rms)
                bar = "#" * min(50, int(rms / 100))
                print(f"  rms {rms:6.0f} | {bar}")
        print(f"[test] Peak level while running: {peak:.0f}")
    else:
        print("Usage: python -m jarvis.main voice-test [tts|stt|mic]")


def _runtime(config_dir: Path, cfg, *, brain=None, adapter=None, background=False):
    """Build the Phase 2 runtime (agents/tools/calendar/handoff) around the brain."""
    from .runtime import Runtime
    from .vault import Vault, KeyringKeyProvider

    if brain is None or adapter is None:
        brain, adapter, provider, _ = _build_brain(config_dir, cfg)
    vault = None
    try:
        vault = Vault(config_dir / "vault.enc", key_provider=KeyringKeyProvider())
    except Exception:
        pass
    return Runtime(adapter, config_dir, vault=vault, brain=brain, background=background,
                   sandbox_path=cfg.sandbox_path), adapter


def _agent(config_dir: Path, goal: str | None):
    """Run a task through the agent stack (§6, §7, §2A)."""
    cfg = Config.load(config_dir)
    if not cfg.onboarded:
        print("No setup found. Run:  python -m jarvis.main --onboard"); sys.exit(1)
    if not goal:
        print('Usage: python -m jarvis.main agent "your task or question"'); return
    rt, adapter = _runtime(config_dir, cfg)
    from .agents import route_mode
    print(f"[Jarvis] mode: {route_mode(goal).value} | brain: {adapter.name}")
    print("[Jarvis] ", end="", flush=True)
    rt.handle(goal, speak=lambda c: print(c, end="", flush=True))
    print()


def _remind(config_dir: Path, arg: str | None):
    """Add a reminder. Format:  'text | +30m'  (or +2h, +1d)."""
    cfg = Config.load(config_dir)
    if not cfg.onboarded:
        print("No setup found. Run:  python -m jarvis.main --onboard"); sys.exit(1)
    if not arg or "|" not in arg:
        print('Usage: python -m jarvis.main remind "call mom | +30m"'); return
    import time as _t
    text, when = [s.strip() for s in arg.split("|", 1)]
    mult = {"m": 60, "h": 3600, "d": 86400}.get(when[-1], 60)
    try:
        minutes = float(when.lstrip("+")[:-1]) * mult / 60
    except ValueError:
        print("Couldn't parse the time (use +30m / +2h / +1d)."); return
    rt, _ = _runtime(config_dir, cfg)
    due = _t.time() + minutes * 60
    rid = rt.calendar.add(text, due)
    print(f"[Jarvis] Reminder set: '{text}' at {_t.strftime('%a %H:%M', _t.localtime(due))} (id {rid})")


def _brief(config_dir: Path):
    """Print the daily briefing (§40)."""
    cfg = Config.load(config_dir)
    if not cfg.onboarded:
        print("No setup found. Run:  python -m jarvis.main --onboard"); sys.exit(1)
    from .connectors import build_briefing
    rt, _ = _runtime(config_dir, cfg)
    print(build_briefing(calendar=rt.calendar, handoff=rt.handoff, staging=rt.staging))


def _tasks(config_dir: Path):
    """Show what's waiting on you + upcoming reminders (§30, §38)."""
    cfg = Config.load(config_dir)
    if not cfg.onboarded:
        print("No setup found. Run:  python -m jarvis.main --onboard"); sys.exit(1)
    rt, _ = _runtime(config_dir, cfg)
    waiting = rt.handoff.waiting()
    print(f"[Jarvis] Waiting on you: {len(waiting)}")
    for t in waiting:
        print(f"  • {t.reason} (id {t.id})")
    ups = rt.calendar.upcoming()
    print(f"[Jarvis] Upcoming reminders: {len(ups)}")
    import time as _t
    for r in ups:
        print(f"  • {_t.strftime('%a %H:%M', _t.localtime(r.due))} — {r.text}")


def _telegram_chatid(config_dir: Path):
    """Fetch your Telegram chat id from the bot's recent updates (§10).

    Prereq: message your bot once (any text) so it has a chat to report.
    """
    import json as _json
    import urllib.request
    from .vault import Vault, KeyringKeyProvider

    try:
        token = Vault(config_dir / "vault.enc", key_provider=KeyringKeyProvider()).get_secret("telegram_bot_token")
    except Exception:
        token = None
    if not token:
        print("[Jarvis] No telegram_bot_token stored. Run: python -m jarvis.main --onboard")
        return

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = _json.loads(r.read().decode())
    except Exception as e:
        print(f"[Jarvis] Couldn't reach Telegram: {e}")
        return

    if not data.get("ok"):
        print(f"[Jarvis] Telegram error: {data}")
        return
    chats = {}
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            who = chat.get("username") or chat.get("first_name") or chat.get("title") or "?"
            chats[chat["id"]] = who
    if not chats:
        print("[Jarvis] No messages found. Send your bot a message first, then re-run this.")
        return
    print("[Jarvis] Found chat id(s):")
    for cid, who in chats.items():
        print(f"  • {cid}  ({who})")
    print("\nStore it with:  python -m jarvis.main --onboard   (Telegram chat id prompt)")


def _telegram_credentials(config_dir: Path) -> tuple[str | None, str | None]:
    """Load Telegram credentials without ever printing their values."""
    from .vault import Vault, KeyringKeyProvider
    try:
        vault = Vault(config_dir / "vault.enc", key_provider=KeyringKeyProvider())
        return vault.get_secret("telegram_bot_token"), vault.get_secret("telegram_chat_id")
    except Exception:
        return None, None


def _format_staged_items(items, *, kind: str | None = None) -> str:
    if kind:
        items = [item for item in items if item.kind.lower() == kind.lower()]
    if not items:
        return f"No staged {kind or 'items'}."
    lines = [f"Staged {kind or 'items'}:"]
    for item in items[:20]:
        body = item.payload.get("body") if isinstance(item.payload, dict) else None
        suffix = f" - {body[:80]}" if body else ""
        lines.append(f"- {item.id} [{item.kind}] {item.title}{suffix}")
    if len(items) > 20:
        lines.append(f"...and {len(items) - 20} more.")
    return "\n".join(lines)


def _format_jobs(jobs) -> str:
    if not jobs:
        return "No background tasks."
    lines = ["Background tasks:"]
    for job in jobs[:20]:
        lines.append(f"- {job.id} [{job.status}] {job.kind}: {job.result or job.payload}")
    if len(jobs) > 20:
        lines.append(f"...and {len(jobs) - 20} more.")
    return "\n".join(lines)


def _telegram_help_text() -> str:
    return ("Commands: /tasks, /brief, /notes, /items, /jobs, "
            "/delete-note <id|all>, /update-note <id> <text>, "
            "/cancel-task <id>, /delete-task <id>, or send a normal Jarvis request.")


def _telegram_response(runtime, message: str, *, remote: bool) -> str:
    """Process Telegram's small command set or route a normal Jarvis request."""
    low = message.strip().lower()
    if low in ("/tasks", "tasks"):
        waiting = runtime.handoff.waiting()
        reminders = runtime.calendar.upcoming()
        return f"Waiting: {len(waiting)} | reminders: {len(reminders)}"
    if low in ("/notes", "notes", "list notes", "show notes"):
        return _format_staged_items(runtime.staging.list(), kind="note")
    if low in ("/items", "items", "staged items"):
        return _format_staged_items(runtime.staging.list())
    if low in ("/jobs", "jobs", "background tasks"):
        return _format_jobs(runtime.task_queue.list())
    if low in ("delete all notes", "remove all notes", "/delete-note all", "/delete-notes all"):
        removed = runtime.staging.discard_kind("note")
        return f"Deleted {removed} staged note(s)."
    m = re.match(r"^/(?:delete-note|delete-item)\s+([a-zA-Z0-9_-]+)$", message.strip())
    if m:
        item_id = m.group(1)
        return f"Deleted staged item {item_id}." if runtime.staging.discard(item_id) else f"No staged item found for id {item_id}."
    m = re.match(r"^/(?:update-note|update-item)\s+([a-zA-Z0-9_-]+)\s+(.+)$", message.strip(), re.S)
    if m:
        item_id, body = m.group(1), m.group(2).strip()
        item = runtime.staging.get(item_id)
        if item is None:
            return f"No staged item found for id {item_id}."
        payload = dict(item.payload or {})
        payload["body"] = body
        title = body[:60] or item.title
        runtime.staging.update(item_id, title=title, payload=payload)
        return f"Updated staged item {item_id}."
    m = re.match(r"^/(?:cancel-task|cancel-job)\s+([a-zA-Z0-9_-]+)$", message.strip())
    if m:
        job_id = m.group(1)
        return f"Cancelled task {job_id}." if runtime.task_queue.cancel(job_id) else f"Could not cancel task {job_id}. It may be missing or already running."
    m = re.match(r"^/(?:delete-task|delete-job)\s+([a-zA-Z0-9_-]+)$", message.strip())
    if m:
        job_id = m.group(1)
        return f"Deleted task {job_id}." if runtime.task_queue.delete(job_id) else f"No task found for id {job_id}."
    if low in ("/brief", "brief", "/breif", "breif"):
        from .connectors import build_briefing
        return build_briefing(calendar=runtime.calendar, handoff=runtime.handoff,
                              staging=runtime.staging)
    if low in ("/help", "help"):
        return _telegram_help_text()
    chunks = []
    handler = runtime.handle_from_telegram if remote else runtime.handle
    return handler(message, speak=chunks.append) or "".join(chunks)


def _start_telegram_poller(config_dir: Path, runtime, *, interval: float = 5.0):
    """Poll Telegram on a daemon thread for the lifetime of voice mode."""
    from .handoff import TelegramInbox, TelegramNotifier
    import threading
    import time

    token, chat = _telegram_credentials(config_dir)
    if not token or not chat:
        return None

    inbox = TelegramInbox(token, chat, offset_path=config_dir / "telegram_offset.json")
    notifier = TelegramNotifier(token, chat)
    startup_message = _telegram_help_text()
    try:
        notifier.send(startup_message)
        print("[Telegram] startup help sent.")
    except Exception as e:
        print(f"[Telegram] startup message error: {e}")

    def poll_forever():
        while True:
            try:
                for message in inbox.poll():
                    response = _telegram_response(runtime, message, remote=True)
                    reply = (response or "").strip() or "(no reply)"
                    notifier.send(reply[:3500])
                    print(f"[Telegram] handled: {message!r} -> {reply[:160]!r}")
            except Exception as e:
                print(f"[Telegram] poll error: {e}")
            time.sleep(max(1.0, interval))

    thread = threading.Thread(target=poll_forever, name="jarvis-telegram", daemon=True)
    thread.start()
    print(f"[Jarvis] Telegram inbound connected (checking every {max(1.0, interval):g}s).")
    return thread


def _telegram_poll(config_dir: Path):
    """Poll allowlisted Telegram inbound messages once and answer them (§10 Phase 2)."""
    cfg = Config.load(config_dir)
    if not cfg.onboarded:
        print("No setup found. Run:  python -m jarvis.main --onboard"); sys.exit(1)
    from .handoff import TelegramInbox, TelegramNotifier

    token, chat = _telegram_credentials(config_dir)
    if not token or not chat:
        print("[Jarvis] Telegram token/chat id missing. Run --onboard and store both.")
        return

    inbox = TelegramInbox(token, chat, offset_path=config_dir / "telegram_offset.json")
    notifier = TelegramNotifier(token, chat)
    messages = inbox.poll()
    if not messages:
        print("[Jarvis] No new allowlisted Telegram messages.")
        return

    rt, _ = _runtime(config_dir, cfg)
    for msg in messages:
        response = _telegram_response(rt, msg, remote=False)
        notifier.send(response[:3500])
        print(f"[Jarvis] Telegram handled: {msg!r} -> {response[:120]!r}")


def _hitl(action: str | None):
    """Interactive demo of LangGraph human-in-the-loop: pause → you answer → resume (§11)."""
    action = action or "send $500 to Bob"
    try:
        from .agents.hitl import build_approval_graph
        from langgraph.types import Command
    except Exception as e:
        print(f"[Jarvis] needs langgraph: pip install langgraph ({e})")
        return
    import uuid
    app = build_approval_graph()
    cfg = {"configurable": {"thread_id": uuid.uuid4().hex[:8]}}

    print(f"[Jarvis] Agent wants to do: {action!r}")
    res = app.invoke({"action": action, "approved": None, "result": None}, cfg)
    intr = res.get("__interrupt__")
    if not intr:
        print("[Jarvis] (no interrupt — already finished)")
        return
    # The graph is PAUSED here, state persisted. Nothing has executed.
    print(f"[Jarvis] ⏸  Paused for you: {intr[0].value.get('question')}")
    ans = input("  Approve? (yes/no): ").strip().lower()
    # Resume from exactly the pause point — not a re-run.
    final = app.invoke(Command(resume=(ans in ("y", "yes"))), cfg)
    print(f"[Jarvis] ▶  Resumed → {final['result']}")


def _search(config_dir: Path, query: str | None):
    """Run a web search directly and report which backend served it (§6)."""
    cfg = Config.load(config_dir)
    if not cfg.onboarded:
        print("No setup found. Run:  python -m jarvis.main --onboard"); sys.exit(1)
    if not query:
        print('Usage: python -m jarvis.main search "your query"'); return
    rt, _ = _runtime(config_dir, cfg)
    has_tavily = bool(rt.tavily_key)
    print(f"[Jarvis] Tavily key stored: {has_tavily}. Searching...")
    res = rt._websearch.search(query, 5)
    print(res.output if res.ok else f"[error] {res.error}")
    print(f"\n[Jarvis] Served by: {rt._websearch.last_source or 'n/a'}")


def _bench(config_dir: Path, n_arg: str | None):
    """Benchmark time-to-first-word (§18)."""
    cfg = Config.load(config_dir)
    if not cfg.onboarded:
        print("No setup found. Run:  python -m jarvis.main --onboard")
        sys.exit(1)
    from .brain.bench import run_benchmark

    brain, adapter, provider, _ = _build_brain(config_dir, cfg)
    n = int(n_arg) if (n_arg and n_arg.isdigit()) else 8
    print(f"[Jarvis] TTFW benchmark on {adapter.name} — {n} turns...")
    stats = run_benchmark(brain, n=n)
    if not stats.get("n"):
        print("[Jarvis] no measurements.")
        return
    print(f"  turns:  {stats['n']}")
    print(f"  median: {stats['median_s'] * 1000:.0f} ms   (target < 1500 ms)")
    print(f"  p95:    {stats['p95_s'] * 1000:.0f} ms")
    print(f"  range:  {stats['min_s'] * 1000:.0f}–{stats['max_s'] * 1000:.0f} ms")
    print(f"  {'✓ meets target' if stats['meets_target'] else '✗ over target (latency pass needed)'}")


def _backup(config_dir: Path, dest: str | None):
    """Phase 1 — encrypted memory backup (§42)."""
    from .backup import MemoryBackup

    dest_dir = Path(dest) if dest else (config_dir / "backups")
    out = MemoryBackup().backup(config_dir / "memory", dest_dir)
    print(f"[Jarvis] Encrypted memory backup written to: {out}")


def _consolidate(config_dir: Path):
    """Run the memory sleep pass immediately (§8)."""
    cfg = Config.load(config_dir)
    if not cfg.onboarded:
        print("No setup found. Run:  python -m jarvis.main --onboard")
        sys.exit(1)
    brain, adapter, provider, _ = _build_brain(config_dir, cfg)
    from .memory import Consolidator

    summary = Consolidator(brain.memory).run()
    print(f"[Jarvis] Memory consolidated: {summary}")


def _set_model(config_dir: Path, model: str | None):
    cfg = Config.load(config_dir)
    if not model:
        print(f"[Jarvis] Current model: {cfg.model}  | endpoint: {cfg.base_url or 'OpenAI default'}")
        print("Usage: python -m jarvis.main set-model gpt-4o   (or glm-4.6, etc.)")
        return
    cfg.model = model
    cfg.save(config_dir)
    print(f"[Jarvis] Brain model set to: {model}")


def _set_endpoint(config_dir: Path, url: str | None):
    """Point the brain at any OpenAI-compatible endpoint (GLM/Z.ai, vLLM). Empty = OpenAI."""
    cfg = Config.load(config_dir)
    if url is None:
        print(f"[Jarvis] Current endpoint: {cfg.base_url or 'OpenAI default'}")
        print("Usage: python -m jarvis.main set-endpoint https://api.z.ai/api/paas/v4")
        print("       python -m jarvis.main set-endpoint default   (back to OpenAI)")
        print("Run --onboard to store the matching provider token, then set-model <model-id>.")
        return
    if url.lower() in ("default", "openai", "none"):
        cfg.base_url = ""
        cfg.api_key_secret = "openai_api_key"
    else:
        cfg.base_url = url
        if "z.ai" in url.lower() or "bigmodel" in url.lower():
            cfg.api_key_secret = "glm_api_key"
    cfg.save(config_dir)
    print(f"[Jarvis] Endpoint set to: {cfg.base_url or 'OpenAI default'}")
    print(f"[Jarvis] Active API key vault entry: {cfg.api_key_secret}")


def _onboarding_status(config_dir: Path):
    """Show readiness status without revealing secret values."""
    cfg = Config.load(config_dir)
    print("[Jarvis] Onboarding status")
    print(f"  onboarded: {'yes' if cfg.onboarded else 'no'}")
    print(f"  sandbox:   {cfg.sandbox_path or '(missing)'}")
    print(f"  model:     {cfg.model}")
    print(f"  endpoint:  {cfg.base_url or 'OpenAI default'}")
    print(f"  key slot:  {cfg.api_key_secret}")
    try:
        from .vault import Vault, KeyringKeyProvider
        vault = Vault(config_dir / "vault.enc", key_provider=KeyringKeyProvider())
        names = ["openai_api_key", "glm_api_key", "telegram_bot_token", "telegram_chat_id",
                 cfg.api_key_secret]
        for name in dict.fromkeys(n for n in names if n):
            try:
                present = bool(vault.get_secret(name))
            except Exception:
                present = False
            print(f"  vault:{name}: {'set' if present else 'missing'}")
    except Exception as e:
        print(f"  vault: unavailable ({e})")


def _live_smoke():
    """Print the dogfood checklist for Tier 0/1 validation."""
    print("""[Jarvis] Live-smoke checklist

1. Voice hardware
   python -m jarvis.main voice-test mic
   python -m jarvis.main voice-test stt
   python -m jarvis.main voice-test tts
   python -m jarvis.main voice

2. Brain + latency
   python -m jarvis.main onboarding-status
   python -m jarvis.main bench 12

3. Browser/Gmail
   pip install playwright && playwright install chromium
   python -m playwright install chrome    # if Gmail login says the browser is insecure
   python -m jarvis.main agent "read my latest Gmail inbox items"
   python -m jarvis.main agent "draft an email to me@example.com with subject test and body hello"

4. Approval gates
   JARVIS_ALLOW_SHELL=1 python -m jarvis.main agent "run command echo jarvis-smoke"
   Say/enter yes only if the requested command is exactly what you expect.

5. Telegram inbound
   Start: python -m jarvis.main voice
   Send your bot: /tasks
   Expect a Telegram reply within about 5 seconds.
   (telegram-poll remains available as a one-shot diagnostic.)

6. Real chain
   python -m jarvis.main agent "research today's top AI news, draft me a Gmail summary, ask before sending"

Record failures with the exact command, expected behavior, actual behavior, and logs.""")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="JARVIS")
    parser.add_argument("command", nargs="?", default="demo",
                        choices=["demo", "chat", "voice", "voice-enroll", "voice-test",
                                 "agent", "remind", "brief", "tasks", "telegram-chatid",
                                 "telegram-poll", "search", "hitl", "bench", "backup",
                                 "consolidate", "set-model", "set-endpoint",
                                 "onboarding-status", "live-smoke"],
                        help="what to run (default: demo)")
    parser.add_argument("arg", nargs="?", default=None, help="argument for the command")
    parser.add_argument("--onboard", action="store_true", help="run first-run setup")
    parser.add_argument("--config-dir", default=str(DEFAULT_CONFIG_DIR), help="config directory")
    parser.add_argument("--dest", default=None, help="backup destination directory")
    parser.add_argument("--no-voice-preflight", action="store_true",
                        help="start voice with env/default options, without interactive prompts")
    args = parser.parse_args(argv)

    config_dir = Path(args.config_dir)
    if args.onboard:
        run_onboarding(config_dir)
        return

    if args.command == "chat":
        _chat(config_dir)
    elif args.command == "voice":
        _voice(config_dir, preflight=not args.no_voice_preflight)
    elif args.command == "voice-enroll":
        _voice_enroll(config_dir)
    elif args.command == "voice-test":
        _voice_test(args.arg)
    elif args.command == "agent":
        _agent(config_dir, args.arg)
    elif args.command == "remind":
        _remind(config_dir, args.arg)
    elif args.command == "brief":
        _brief(config_dir)
    elif args.command == "tasks":
        _tasks(config_dir)
    elif args.command == "telegram-chatid":
        _telegram_chatid(config_dir)
    elif args.command == "telegram-poll":
        _telegram_poll(config_dir)
    elif args.command == "search":
        _search(config_dir, args.arg)
    elif args.command == "hitl":
        _hitl(args.arg)
    elif args.command == "bench":
        _bench(config_dir, args.arg)
    elif args.command == "backup":
        _backup(config_dir, args.dest)
    elif args.command == "consolidate":
        _consolidate(config_dir)
    elif args.command == "set-model":
        _set_model(config_dir, args.arg)
    elif args.command == "set-endpoint":
        _set_endpoint(config_dir, args.arg)
    elif args.command == "onboarding-status":
        _onboarding_status(config_dir)
    elif args.command == "live-smoke":
        _live_smoke()
    else:
        _demo(config_dir)


if __name__ == "__main__":
    main()
