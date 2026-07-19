"""LiveVoiceLoop (§3, §4, §5, §18, §19) — the real always-on Jarvis voice interaction.

Interaction model (what the user asked for):
  * The mic is ALWAYS on, listening only for the wake word while idle.
  * "Hey Jarvis" ARMS a conversation session — it does not need to be repeated. Jarvis then
    keeps listening continuously.
  * For each utterance in a session: verify it's the owner (ignore other people), transcribe,
    and decide whether it was addressed to Jarvis (vs. talking to a person / phone / self).
    Reply only when addressed; otherwise just keep listening.
  * The session ends when there's no addressed speech for a while (conversation over / user
    walked away), returning to idle — where the wake word is needed again.

State machine:  IDLE --(wake word)--> ACTIVE --(inactivity timeout)--> IDLE

This module owns the mic and orchestrates the backends. Heavy audio deps are imported lazily
via the backend classes, so importing this module is cheap.
"""
from __future__ import annotations

import time
from typing import Optional

from ..brain.loop import BrainLoop
from ..core.policy import ActionRisk
from .activity import UtteranceSegmenter, frame_is_speech, frame_rms, split_on_wake
from .addressing import is_addressed


class LiveVoiceLoop:
    def __init__(
        self,
        brain: BrainLoop,
        wake,            # OpenWakeWord
        stt,             # FasterWhisperSTT
        tts,             # KokoroTTS
        speaker=None,    # SpeechBrainVerifier or None (no owner check)
        *,
        session_timeout: float = 30.0,       # seconds of no speech → end session
        vad_multiplier: float = 2.5,         # speech threshold = ambient_rms * this
        end_silence_frames: int = 16,        # ~1.3 s pause ends an utterance (don't chop sentences)
        require_owner: bool = True,
        use_addressing_model: bool = True,  # decide "is he talking to me?" (§3)
        addressing_adapter=None,            # a capable model for that call (defaults to brain's)
        wake_mode: str = "stt",          # "stt" (robust, reuses Whisper) or "model" (openWakeWord)
        wake_words: tuple = ("jarvis",),
        proactive=None,                  # ProactiveEngine — lets Jarvis speak first (§25)
        proactive_interval: float = 5.0, # seconds between proactive checks while idle
        runtime=None,                    # Runtime — routes spoken requests to agents/tools (§2A)
        barge_in: bool = True,           # let the user interrupt TTS by speaking (§18)
        debug: bool = False,
        log=print,
    ):
        self.brain = brain
        self.wake = wake
        self.stt = stt
        self.tts = tts
        self.speaker = speaker
        # A dedicated (stronger) model for the addressing yes/no; falls back to the brain's.
        self.addressing_adapter = addressing_adapter or brain.adapter
        self.session_timeout = session_timeout
        self.vad_multiplier = vad_multiplier
        self.end_silence_frames = end_silence_frames
        self.require_owner = require_owner and speaker is not None
        self.use_addressing_model = use_addressing_model
        self.wake_mode = wake_mode
        self.wake_words = tuple(w.lower() for w in wake_words)
        self.proactive = proactive
        self.proactive_interval = proactive_interval
        self.runtime = runtime
        self.barge_in = barge_in
        self.debug = debug
        self._mic = None          # set in run(); used by barge-in monitor
        self._barged = False
        self.log = log
        self._speech_threshold = 500.0  # replaced by calibration
        if self.runtime is not None and hasattr(self.runtime, "approval"):
            self.runtime.approval.set_approver(self._approve_by_voice)

    # ---- calibration -----------------------------------------------------

    def warmup(self) -> None:
        """Load all models up front so nothing stalls the loop mid-conversation."""
        backends = [("stt", self.stt), ("tts", self.tts), ("speaker", self.speaker)]
        if self.wake_mode == "model":
            backends.insert(0, ("wake", self.wake))  # only load openWakeWord if actually used
        for name, backend in backends:
            if backend is not None and hasattr(backend, "load"):
                self.log(f"[voice] loading {name} model...")
                try:
                    backend.load()
                except Exception as e:
                    self.log(f"[voice] {name} load warning: {e}")

    def calibrate(self, mic, seconds: float = 1.0) -> None:
        """Sample ambient noise to set the speech threshold."""
        n = max(1, int(seconds / 0.08))  # ~80 ms frames
        readings = [frame_rms(mic.read()) for _ in range(n)]
        ambient = sum(readings) / len(readings) if readings else 100.0
        self._speech_threshold = max(150.0, ambient * self.vad_multiplier)
        self.log(f"[voice] calibrated ambient≈{ambient:.0f}, speech threshold≈{self._speech_threshold:.0f}")

    # ---- main loop -------------------------------------------------------

    def run(self, mic) -> None:
        """Consume mic frames forever, running the IDLE↔ACTIVE state machine.

        `mic` must provide read() -> frame bytes and drain() -> discard buffered frames.
        """
        self.warmup()
        self._mic = mic
        mic.drain()  # discard anything captured during model loading
        self.calibrate(mic)
        self.log(f'[voice] Idle. Say "Hey Jarvis" to start. (wake mode: {self.wake_mode}, Ctrl-C to quit)')
        state = "IDLE"
        segmenter = UtteranceSegmenter(end_silence_frames=self.end_silence_frames)
        last_addressed = time.monotonic()
        peak = 0.0
        dbg_frames = 0
        last_proactive = time.monotonic()

        while True:
            frame = mic.read()

            # ---- IDLE: proactive check, then wait for the wake word ----------
            if state == "IDLE":
                # Jarvis speaks first when something's worth it (§25). Presence routing
                # (speak vs. phone) is handled inside the engine.
                if self.proactive is not None and \
                        (time.monotonic() - last_proactive) >= self.proactive_interval:
                    last_proactive = time.monotonic()
                    try:
                        announcements = self.proactive.poll()
                    except Exception as e:
                        announcements = []
                        if self.debug:
                            self.log(f"[proactive] error: {e}")
                    if announcements:
                        for text in announcements:
                            self.log(f"[jarvis→you] {text}")
                            self.tts.speak(text)
                        mic.drain()
                        state = "ACTIVE"           # open a reply window — no wake word needed
                        segmenter.reset()
                        last_addressed = time.monotonic()
                        continue

                woke = False
                if self.wake_mode == "model":
                    woke = self._idle_model_wake(frame, mic)
                else:
                    # STT wake: segment speech, transcribe, look for "jarvis".
                    is_speech = frame_is_speech(frame, self._speech_threshold)
                    utterance = segmenter.feed(is_speech, frame)
                    if utterance is not None:
                        woke = self._idle_stt_wake(b"".join(utterance), mic)
                        segmenter.reset()
                if woke:
                    state = "ACTIVE"
                    segmenter.reset()
                    last_addressed = time.monotonic()
                continue

            # ---- ACTIVE: converse until silence times out --------------------
            now = time.monotonic()
            is_speech = frame_is_speech(frame, self._speech_threshold)
            was_active = segmenter.active
            utterance = segmenter.feed(is_speech, frame)
            if self.debug:
                if is_speech and not was_active:
                    self.log(f"[voice] hearing you... (rms>{self._speech_threshold:.0f})")
                dbg_frames += 1
                if dbg_frames >= 25:  # ~2 s heartbeat so it never looks dead
                    self.log(f"[voice] listening... ({int(now - last_addressed)}s/"
                             f"{int(self.session_timeout)}s to idle)")
                    dbg_frames = 0

            if utterance is not None:
                text = self._transcribe(b"".join(utterance))
                if text:
                    self.log(f"[you] {text}")
                    if self._respond(text):
                        last_addressed = time.monotonic()
                # Normally drain audio captured while transcribing/replying (incl. our TTS).
                # But if you barged in, KEEP listening so your interruption is captured.
                if not self._barged:
                    mic.drain()
                self._barged = False

            if (now - last_addressed) > self.session_timeout:
                self.log("[voice] No conversation for a while — going idle.")
                state = "IDLE"
                segmenter.reset()

    # ---- wake helpers ----------------------------------------------------

    def _idle_model_wake(self, frame: bytes, mic) -> bool:
        """openWakeWord path (kept as an option). Returns True on wake."""
        try:
            score = self.wake.predict(frame)
            if score >= self.wake.threshold:
                self.log(f"[voice] Wake word ({score:.2f}) — I'm listening.")
                self.tts.speak("Yes?")
                mic.drain()
                return True
        except Exception as e:
            self.log(f"[voice] wake error: {e}")
        return False

    def _idle_stt_wake(self, pcm: bytes, mic) -> bool:
        """STT wake: transcribe the utterance; wake if it contains the wake word.

        Reuses Whisper (which reliably hears 'Hey Jarvis'). If there's a command after the
        wake word ('Hey Jarvis, what's the time'), it's handled immediately.
        """
        text = self._transcribe(pcm, check_owner=False)
        if not text:
            return False
        # Fuzzy match so STT slips (Jervis / Jaarvis / Jarvish) still wake it.
        matched, command = split_on_wake(text, self.wake_words)
        if not matched:
            if self.debug:
                self.log(f"[voice] (idle heard: {text!r} — no wake word)")
            return False
        self.log(f"[voice] Wake word heard: {text!r} — I'm listening.")
        mic.drain()
        if command.strip():
            self._respond(command)  # handle the inline command right away
        else:
            self.tts.speak("Yes?")
        return True

    # ---- transcription + reply (shared by idle-wake and active) ----------

    def _transcribe(self, pcm: bytes, *, check_owner: bool = True) -> str:
        """Owner check (optional) + speech-to-text. Returns text ('' if nothing/other person)."""
        if self.debug:
            self.log(f"[voice] captured {len(pcm) / 2 / 16000:.1f}s of audio — transcribing...")
        if check_owner and self.require_owner:
            try:
                score = self.speaker.owner_score(pcm)
                if score is not None:
                    if self.debug:
                        self.log(f"[voice] speaker match {score:.2f} "
                                 f"(you if ≥ {self.speaker.threshold})")
                    if score < self.speaker.threshold:
                        if self.debug:
                            self.log("[voice] (voice didn't match your voiceprint — ignoring)")
                        return ""  # someone else spoke
            except Exception as e:
                self.log(f"[voice] speaker check error: {e}")
        try:
            text = self.stt.transcribe(pcm)
        except Exception as e:
            self.log(f"[voice] transcription error: {e}")
            return ""
        if not text or not text.strip():
            if self.debug:
                self.log("[voice] (didn't catch any words)")
            return ""
        return text.strip()

    def _respond(self, text: str) -> bool:
        """Kill-switch + addressing check, then reply. Returns True if Jarvis replied."""
        if self.brain.kill_switch and self.brain.kill_switch.check(text):
            return False
        if not is_addressed(self.addressing_adapter, text, use_model=self.use_addressing_model):
            self.log("[voice] (not addressed to me — listening)")
            return False
        from .pipeline import _SentenceSpeaker

        # Barge-in: while Jarvis speaks, watch the mic and stop if you talk over it (§18).
        import threading
        barge_event = threading.Event()
        monitor = None
        if self.barge_in and self._mic is not None:
            from .bargein import BargeInMonitor
            # If a voiceprint is enrolled, verify barge-in speech is YOU — so Jarvis's own
            # audio through speakers can't interrupt it (only your real voice does). This is
            # independent of owner-only *responding* (§3).
            verify = None
            if self.speaker is not None:
                get_vp = getattr(self.speaker, "get_enrolled_vector", None)
                if callable(get_vp) and get_vp() is not None:
                    verify = self.speaker.is_owner
            monitor = BargeInMonitor(self._mic, self._speech_threshold * 2.0, barge_event,
                                     verify=verify, log=self.log if self.debug else None)
            monitor.start()

        sink = _SentenceSpeaker(self.tts, stop_check=barge_event.is_set)
        # Route through the agent runtime (M1 chat / M2-M3 do tasks) if available,
        # else fall back to plain conversation.
        if self.runtime is not None:
            reply = self.runtime.handle(text, speak=sink.feed)
        else:
            reply = self.brain.handle_turn(text, speak=sink.feed)
        sink.flush()

        if monitor is not None:
            monitor.stop()
        self._barged = barge_event.is_set()
        if self._barged:
            self.log("[voice] (interrupted — I'm listening)")
        self.log(f"[jarvis] {reply}")
        return True

    # ---- spoken approval -------------------------------------------------

    def _approve_by_voice(self, request, risk: ActionRisk) -> bool:
        """ApprovalEngine callback for voice mode.

        It speaks the requested action, listens for one short answer, and accepts only clear
        yes/approve/confirm language. This is used by irreversible tools such as run_command
        and gmail_send while the live loop owns the mic.
        """
        prompt = f"Approval required. {request.summary}. Say yes to approve, or no to cancel."
        self.log(f"[approval] {request.summary} ({risk.value})")
        try:
            self.tts.speak(prompt)
        except Exception:
            pass

        answer = self._listen_for_approval_answer(timeout=12.0)
        low = answer.lower().strip()
        approved = any(w in low for w in ("yes", "approve", "approved", "confirm", "do it"))
        denied = any(w in low for w in ("no", "deny", "cancel", "stop", "don't", "do not"))
        if approved and not denied:
            self.log("[approval] approved by voice")
            return True
        self.log(f"[approval] denied or unclear: {answer!r}")
        try:
            self.tts.speak("Cancelled.")
        except Exception:
            pass
        return False

    def _listen_for_approval_answer(self, timeout: float = 12.0) -> str:
        """Capture and transcribe one short yes/no answer from the current mic."""
        if self._mic is None:
            try:
                return input("Approve? (yes/no): ").strip()
            except Exception:
                return ""

        self._mic.drain()
        seg = UtteranceSegmenter(min_speech_frames=2, end_silence_frames=8, max_frames=120)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            frame = self._mic.read()
            utterance = seg.feed(frame_is_speech(frame, self._speech_threshold), frame)
            if utterance is None:
                continue
            text = self._transcribe(b"".join(utterance), check_owner=True)
            if text:
                self.log(f"[approval heard] {text}")
                return text
            seg.reset()
        return ""
