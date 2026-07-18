"""Real audio backends for the Mac (§3, §4, §5) — frame/buffer oriented, lazily imported.

These wrap the actual local models. Every heavy dependency is imported INSIDE a method so
importing this module never forces the deps to be installed. The live loop (live.py) owns the
microphone and feeds these:

  * OpenWakeWord.predict(frame_int16_bytes) -> score           (§3)
  * SpeechBrainVerifier.embed(pcm16_bytes) -> vector / is_owner (§3)
  * FasterWhisperSTT.transcribe(pcm16_bytes) -> text           (§4)
  * KokoroTTS.speak(text) -> plays audio                        (§5)

Audio convention everywhere: 16 kHz, mono, 16-bit little-endian PCM (raw bytes), except TTS
output which Kokoro produces at 24 kHz.
"""
from __future__ import annotations

import os
from typing import Optional

from .base import STT, TTS, SpeakerVerifier, WakeWordDetector

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # 80 ms at 16 kHz — openWakeWord's expected frame size

_INSTALL_HINT = (
    "Voice backends need extra packages:\n"
    "    pip install -r requirements-voice.txt\n"
    "and system tools:  brew install ffmpeg espeak-ng"
)


def _pcm16_to_float32(pcm_bytes: bytes):
    """Convert raw 16-bit PCM bytes to a float32 numpy array in [-1, 1]."""
    import numpy as np  # lazy

    arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype("float32") / 32768.0
    return arr


def _pcm16_to_int16(pcm_bytes: bytes):
    import numpy as np  # lazy

    return np.frombuffer(pcm_bytes, dtype=np.int16)


class OpenWakeWord(WakeWordDetector):
    """Detects the 'hey_jarvis' phrase from 80 ms int16 frames."""

    def __init__(self, model: str = "hey_jarvis", threshold: float = 0.3):
        self._model_name = model
        self.threshold = threshold
        self._model = None
        self._logged_keys = False

    def _load(self):
        if self._model is None:
            try:
                import openwakeword
                from openwakeword.model import Model
            except ImportError as e:
                raise ImportError(f"openWakeWord not installed. {_INSTALL_HINT}") from e
            try:
                openwakeword.utils.download_models()  # no-op if already present
            except Exception:
                pass
            self._model = Model(wakeword_models=[self._model_name])
        return self._model

    def load(self) -> None:
        self._load()

    def predict(self, frame_bytes: bytes) -> float:
        """Return the wake-word probability for one 80 ms frame."""
        model = self._load()
        scores = model.predict(_pcm16_to_int16(frame_bytes))
        if not self._logged_keys:
            self._logged_keys = True
            print(f"[voice] wake model keys: {list(scores.keys())}")
        # scores is {model_name: prob}; take our model's score (or the max of all loaded).
        if self._model_name in scores:
            return float(scores[self._model_name])
        return float(max(scores.values()) if scores else 0.0)

    def is_wake(self, frame_bytes: bytes) -> bool:
        return self.predict(frame_bytes) >= self.threshold

    def wait_for_wake(self) -> bool:  # not used by the live loop (it feeds frames itself)
        raise NotImplementedError("Live loop feeds frames to predict(); see live.py.")


class SpeechBrainVerifier(SpeakerVerifier):
    """ECAPA-TDNN speaker embeddings; matches an utterance to the enrolled owner."""

    def __init__(self, threshold: float = 0.25):
        self.threshold = threshold
        self._model = None
        self._enrolled = None  # numpy vector

    def _load(self):
        if self._model is None:
            try:
                from speechbrain.inference.speaker import EncoderClassifier
            except ImportError as e:
                raise ImportError(f"SpeechBrain not installed. {_INSTALL_HINT}") from e
            self._model = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir=os.path.expanduser("~/.jarvis/models/ecapa"),
            )
        return self._model

    def load(self) -> None:
        self._load()

    def embed(self, pcm_bytes: bytes):
        import torch  # lazy (comes with speechbrain)

        model = self._load()
        wav = torch.tensor(_pcm16_to_float32(pcm_bytes)).unsqueeze(0)
        with torch.no_grad():
            emb = model.encode_batch(wav).squeeze().cpu().numpy()
        return emb

    def enroll(self, samples: list) -> None:
        """samples: list of pcm16 byte buffers of the owner speaking. Averages their embeddings."""
        import numpy as np

        embs = [self.embed(s) for s in samples if s]
        if not embs:
            raise ValueError("No enrollment audio provided.")
        self._enrolled = np.mean(embs, axis=0)

    def set_enrolled_vector(self, vec) -> None:
        self._enrolled = vec

    def get_enrolled_vector(self):
        return self._enrolled

    def owner_score(self, pcm_bytes: bytes):
        """Cosine similarity to the enrolled voiceprint, or None if not enrolled."""
        if self._enrolled is None:
            return None
        import numpy as np

        v = self.embed(pcm_bytes)
        a, b = self._enrolled, v
        return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1.0))

    def is_owner(self, pcm_bytes: bytes) -> bool:
        score = self.owner_score(pcm_bytes)
        return True if score is None else score >= self.threshold


class FasterWhisperSTT(STT):
    def __init__(self, model_size: str = "medium.en", device: str = "auto",
                 compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise ImportError(f"faster-whisper not installed. {_INSTALL_HINT}") from e
            self._model = WhisperModel(self.model_size, device=self.device,
                                       compute_type=self.compute_type)
        return self._model

    def load(self) -> None:
        self._load()

    def transcribe(self, pcm_bytes: bytes) -> str:
        model = self._load()
        audio = _pcm16_to_float32(pcm_bytes)
        segments, _ = model.transcribe(audio, language="en", vad_filter=True)
        return " ".join(seg.text for seg in segments).strip()


class KokoroTTS(TTS):
    def __init__(self, voice: str = "af_heart", lang_code: str = "a"):
        self.voice = voice
        self.lang_code = lang_code
        self._pipe = None

    def _load(self):
        if self._pipe is None:
            try:
                from kokoro import KPipeline
            except ImportError as e:
                raise ImportError(f"Kokoro TTS not installed. {_INSTALL_HINT}") from e
            self._pipe = KPipeline(lang_code=self.lang_code)
        return self._pipe

    def load(self) -> None:
        self._load()

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        pipe = self._load()
        try:
            import sounddevice as sd
        except ImportError as e:
            raise ImportError(f"sounddevice not installed. {_INSTALL_HINT}") from e
        for _, _, audio in pipe(text, voice=self.voice):
            sd.play(audio, samplerate=24000)
            sd.wait()
