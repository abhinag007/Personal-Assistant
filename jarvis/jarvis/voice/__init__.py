"""Voice I/O (§3, §4, §5, §18).

Interfaces + text-mode stubs (always available, no audio hardware needed) + lazy real
backends (openWakeWord, whisper.cpp/faster-whisper, Kokoro/Piper, SpeechBrain) that are
only imported when you actually run voice mode on the Mac.

This split means the whole pipeline is testable now (via stubs) while the real audio
backends drop in without touching the brain loop.
"""
from .base import (  # noqa: F401
    STT,
    TTS,
    SpeakerVerifier,
    WakeWordDetector,
)
from .stubs import (  # noqa: F401
    StubSTT,
    StubSpeakerVerifier,
    StubTTS,
    StubWakeWord,
)
from .pipeline import VoicePipeline  # noqa: F401
