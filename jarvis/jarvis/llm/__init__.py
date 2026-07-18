"""Model adapter layer (§1) — the swappable brain.

Everything in the system talks to `ModelAdapter`, never to a concrete provider. This is
what makes the brain selectable per task (local / OpenAI / Claude) and what makes the
eventual go-local switch a config change, not a rewrite.
"""
from .adapter import (  # noqa: F401
    ChatResponse,
    Message,
    ModelAdapter,
    ToolCall,
)
from .mock_adapter import MockAdapter  # noqa: F401
from .router import BrainRouter, build_adapter  # noqa: F401
