"""Brain router (§1, §20) — selects which model answers.

Phase 1 supports choosing the active brain from config/vault:
  * "mock"   → offline deterministic (default when no key)
  * "openai" → OpenAIAdapter (dev phase)
  * "claude" → placeholder (wired in a later phase)
  * "local"  → placeholder for Ollama (Phase 5)

The complexity-based escalation ladder (§20) will layer on top of this router later;
for Phase 1 it simply returns the configured default brain.
"""
from __future__ import annotations

from typing import Optional

from .adapter import ModelAdapter
from .mock_adapter import MockAdapter


def build_adapter(
    provider: str = "mock",
    *,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> ModelAdapter:
    provider = (provider or "mock").lower()

    if provider == "mock":
        return MockAdapter()

    if provider == "openai":
        if not api_key:
            raise ValueError("OpenAI provider requires an API key (store it via onboarding, §14).")
        from .openai_adapter import OpenAIAdapter

        # base_url lets you point at any OpenAI-compatible endpoint (GLM/Z.ai, local vLLM).
        return OpenAIAdapter(api_key=api_key, model=model or "gpt-4o-mini", base_url=base_url)

    if provider == "claude":
        raise NotImplementedError("Claude adapter is added in a later phase.")

    if provider == "local":
        raise NotImplementedError("Local Ollama adapter is added in Phase 5.")

    raise ValueError(f"Unknown model provider: {provider!r}")


class BrainRouter:
    """Holds the active adapter and (later) routes by task complexity (§20)."""

    def __init__(self, default: ModelAdapter):
        self._default = default

    @property
    def active(self) -> ModelAdapter:
        return self._default

    def for_task(self, difficulty: str = "normal") -> ModelAdapter:
        # Phase 1: always the default brain. Escalation ladder arrives with §20.
        return self._default
