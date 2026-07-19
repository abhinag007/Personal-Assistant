"""Configuration (§41).

Small JSON-backed settings store: where the sandbox lives, basic preferences, and
whether onboarding has completed. Deliberately dependency-free.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Default config location: ~/.jarvis (overridable, e.g. in tests).
DEFAULT_CONFIG_DIR = Path(os.path.expanduser("~")) / ".jarvis"


@dataclass
class Config:
    sandbox_path: str = ""
    assistant_name: str = "Jarvis"
    model: str = "gpt-4o-mini"       # model for the brain (§1); switch with set-model
    base_url: str = ""               # OpenAI-compatible endpoint (GLM/Z.ai, vLLM); set-endpoint
    api_key_secret: str = "openai_api_key"  # vault key for the active OpenAI-compatible provider
    wake_word: str = "hey jarvis"
    chattiness: str = "balanced"     # quiet | balanced | chatty (§34)
    quiet_hours: str = ""            # e.g. "22:00-07:00"
    onboarded: bool = False
    extra: dict = field(default_factory=dict)

    # ---- persistence -----------------------------------------------------

    @staticmethod
    def _path(config_dir: str | os.PathLike | None = None) -> Path:
        d = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
        return d / "config.json"

    @classmethod
    def load(cls, config_dir: str | os.PathLike | None = None) -> "Config":
        path = cls._path(config_dir)
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f: data[f] for f in cls().__dict__ if f in data}
        return cls(**known)

    def save(self, config_dir: str | os.PathLike | None = None) -> Path:
        path = self._path(config_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path
