"""Voice enrollment (§3) — teach Jarvis the owner's voiceprint.

Records a few seconds of you speaking, computes the speaker embedding, and saves it so the
live loop can verify it's you and ignore other people. Run via `python -m jarvis.main
voice-enroll`.
"""
from __future__ import annotations

from pathlib import Path

from .backends import SAMPLE_RATE, SpeechBrainVerifier


def record_seconds(seconds: float, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Record `seconds` of mono int16 audio from the default mic; return raw PCM bytes."""
    import sounddevice as sd  # lazy

    frames = sd.rec(int(seconds * sample_rate), samplerate=sample_rate,
                    channels=1, dtype="int16")
    sd.wait()
    return frames.tobytes()


def run_enrollment(config_dir: str | Path, *, samples: int = 3, seconds: float = 4.0,
                   print_fn=print, input_fn=input) -> Path:
    """Interactive enrollment; saves the averaged voiceprint under config_dir."""
    import numpy as np

    config_dir = Path(config_dir)
    (config_dir / "models").mkdir(parents=True, exist_ok=True)
    verifier = SpeechBrainVerifier()

    print_fn("\n=== Voice enrollment ===")
    print_fn(f"I'll record {samples} short clips of your voice ({seconds:.0f}s each).")
    clips = []
    for i in range(samples):
        input_fn(f"  Clip {i + 1}/{samples}: press Enter, then speak naturally...")
        print_fn("   recording...")
        clips.append(record_seconds(seconds))
        print_fn("   got it.")

    verifier.enroll(clips)
    vec = verifier.get_enrolled_vector()
    out = config_dir / "voiceprint.npy"
    np.save(out, vec)
    print_fn(f"  ✓ Voiceprint saved to {out}. Jarvis will now respond only to your voice.\n")
    return out


def load_voiceprint(config_dir: str | Path):
    """Load a saved voiceprint vector, or None if not enrolled."""
    import numpy as np

    path = Path(config_dir) / "voiceprint.npy"
    if not path.exists():
        return None
    return np.load(path)
