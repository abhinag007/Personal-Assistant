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


def _build_brain(config_dir: Path, cfg: Config):
    """Assemble the Phase 1 brain: model adapter + memory + tracer + safety spine."""
    from .audit import AuditLog
    from .brain import BrainLoop
    from .llm import build_adapter
    from .llm.openai_adapter import OpenAIAdapter  # noqa: F401 (ensures module importable)
    from .memory import AdapterEmbedder, HashEmbedder, MemoryStore
    from .tracing.tracer import LocalTracer
    from .vault import Vault, KeyringKeyProvider

    # Choose the brain: OpenAI if a key is stored, else the offline mock.
    provider = "mock"
    api_key = None
    try:
        vault = Vault(config_dir / "vault.enc", key_provider=KeyringKeyProvider())
        api_key = vault.get_secret("openai_api_key")
        if api_key:
            provider = "openai"
    except Exception:
        pass

    adapter = build_adapter(provider, api_key=api_key, model=cfg.model)
    # Real semantic embeddings when on OpenAI; deterministic hash embedder offline.
    embedder = AdapterEmbedder(adapter) if provider == "openai" else HashEmbedder()

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
    print(f"[Jarvis] Phase 1 chat online. Brain: {adapter.name}"
          + ("  (offline mock — store an 'openai_api_key' to use OpenAI)" if provider == "mock" else ""))
    print('[Jarvis] Talk to me. Ctrl-C or "Jarvis, end yourself" to stop.\n')

    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        print("Jarvis> ", end="", flush=True)
        brain.handle_turn(text)
        print()
        if brain.last_ttfw is not None:
            print(f"   (ttfw {brain.last_ttfw * 1000:.0f} ms)\n")


def _voice(config_dir: Path, *, force_stub: bool = False):
    """Phase 1 — real always-on voice loop (wake word arms a listening session)."""
    cfg = Config.load(config_dir)
    if not cfg.onboarded:
        print("No setup found. Run:  python -m jarvis.main --onboard")
        sys.exit(1)

    brain, adapter, provider, api_key = _build_brain(config_dir, cfg)

    if force_stub:
        return _voice_stub(brain, adapter)

    # Try the real audio backends. If deps/mic are missing, explain and fall back to stub.
    try:
        from .voice.backends import FasterWhisperSTT, KokoroTTS, OpenWakeWord, SpeechBrainVerifier
        from .voice.enroll import load_voiceprint
        from .voice.live import LiveVoiceLoop
        from .voice.mic import MicStream

        import os as _os
        wake = OpenWakeWord()
        stt = FasterWhisperSTT(model_size=_os.environ.get("JARVIS_STT_MODEL", "medium.en"))
        tts = KokoroTTS()
        spk_threshold = float(_os.environ.get("JARVIS_SPEAKER_THRESHOLD", "0.25"))
        speaker = SpeechBrainVerifier(threshold=spk_threshold)
        vp = load_voiceprint(config_dir)
        owner_env_on = _os.environ.get("JARVIS_REQUIRE_OWNER", "1") != "0"
        if vp is not None and owner_env_on:
            speaker.set_enrolled_vector(vp)
            require_owner = True
            print(f"[Jarvis] Owner-only voice ON (match ≥ {spk_threshold}). "
                  f"Set JARVIS_REQUIRE_OWNER=0 to disable, or JARVIS_SPEAKER_THRESHOLD to tune.")
        else:
            require_owner = False
            if vp is None:
                print("[Jarvis] No voiceprint enrolled — I'll respond to any voice.")
                print("         Run 'python -m jarvis.main voice-enroll' to make me owner-only.")
            else:
                print("[Jarvis] Owner-only disabled via JARVIS_REQUIRE_OWNER=0.")

        import os
        debug = os.environ.get("JARVIS_VOICE_DEBUG", "1") != "0"
        wake_mode = os.environ.get("JARVIS_WAKE_MODE", "stt")  # "stt" (robust) or "model"

        # Proactive speaker (§25): Jarvis speaks first (reminders/tasks/briefing), routing to
        # your phone when you're away. Built from the Phase 2 runtime.
        proactive = None
        try:
            rt, _ = _runtime(config_dir, cfg)
            from .proactive import ProactiveEngine
            brief_hour = os.environ.get("JARVIS_BRIEF_HOUR")
            proactive = ProactiveEngine(
                calendar=rt.calendar, handoff=rt.handoff,
                notifier=rt.handoff.notifier, presence=rt.handoff.presence,
                quiet_hours=cfg.quiet_hours,
                briefing_hour=int(brief_hour) if (brief_hour and brief_hour.isdigit()) else None,
                adapter=adapter, user_name=brain.user_name,   # conversational phrasing (§34)
            )
        except Exception as e:
            print(f"[Jarvis] proactive speaker disabled: {e}")
        addressing = os.environ.get("JARVIS_ADDRESSING", "1") == "1"  # smart "talking to me?" (on)

        # Use a capable, dedicated model for the addressing yes/no (independent of the brain
        # model, so it's reliable even if the brain runs on a small/local model).
        addressing_adapter = brain.adapter
        if provider == "openai" and api_key:
            addr_model = os.environ.get("JARVIS_ADDRESSING_MODEL", "gpt-4o")
            try:
                from .llm import build_adapter
                addressing_adapter = build_adapter("openai", api_key=api_key, model=addr_model)
            except Exception as e:
                print(f"[Jarvis] couldn't build gpt-4o addressing model ({e}); using {adapter.name}")

        loop = LiveVoiceLoop(brain, wake, stt, tts, speaker,
                             require_owner=require_owner, wake_mode=wake_mode,
                             use_addressing_model=addressing,
                             addressing_adapter=addressing_adapter,
                             proactive=proactive, debug=debug)
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


def _runtime(config_dir: Path, cfg):
    """Build the Phase 2 runtime (agents/tools/calendar/handoff) around the brain."""
    from .runtime import Runtime
    from .vault import Vault, KeyringKeyProvider

    brain, adapter, provider, _ = _build_brain(config_dir, cfg)
    vault = None
    try:
        vault = Vault(config_dir / "vault.enc", key_provider=KeyringKeyProvider())
    except Exception:
        pass
    return Runtime(adapter, config_dir, vault=vault), adapter


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
    print("[Jarvis] " + rt.handle(goal))


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


def _set_model(config_dir: Path, model: str | None):
    cfg = Config.load(config_dir)
    if not model:
        print(f"[Jarvis] Current model: {cfg.model}")
        print("Usage: python -m jarvis.main set-model gpt-4o   (e.g. gpt-4o, gpt-4o-mini)")
        return
    cfg.model = model
    cfg.save(config_dir)
    print(f"[Jarvis] Brain model set to: {model}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="JARVIS")
    parser.add_argument("command", nargs="?", default="demo",
                        choices=["demo", "chat", "voice", "voice-enroll", "voice-test",
                                 "agent", "remind", "brief", "tasks",
                                 "bench", "backup", "set-model"],
                        help="what to run (default: demo)")
    parser.add_argument("arg", nargs="?", default=None, help="argument for the command")
    parser.add_argument("--onboard", action="store_true", help="run first-run setup")
    parser.add_argument("--config-dir", default=str(DEFAULT_CONFIG_DIR), help="config directory")
    parser.add_argument("--dest", default=None, help="backup destination directory")
    args = parser.parse_args(argv)

    config_dir = Path(args.config_dir)
    if args.onboard:
        run_onboarding(config_dir)
        return

    if args.command == "chat":
        _chat(config_dir)
    elif args.command == "voice":
        _voice(config_dir)
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
    elif args.command == "bench":
        _bench(config_dir, args.arg)
    elif args.command == "backup":
        _backup(config_dir, args.dest)
    elif args.command == "set-model":
        _set_model(config_dir, args.arg)
    else:
        _demo(config_dir)


if __name__ == "__main__":
    main()
