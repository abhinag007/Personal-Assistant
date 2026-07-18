"""ModelAdapter interface + shared data types (§1).

The whole system depends only on this interface. Concrete adapters (OpenAI, Claude,
Ollama, Mock) implement it. Streaming (§18) is first-class: `stream()` yields text
chunks so the TTS layer can start speaking before the full reply is generated.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator, Optional


@dataclass
class Message:
    """A single chat message. role ∈ {system, user, assistant, tool}."""

    role: str
    content: str
    name: Optional[str] = None  # for tool messages


@dataclass
class ToolCall:
    """A tool/function call requested by the model (used from Phase 2 onward)."""

    name: str
    arguments: dict = field(default_factory=dict)
    call_id: Optional[str] = None


@dataclass
class ChatResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    # Rough token accounting for the spend meter (§16) during the OpenAI phase.
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ModelAdapter(ABC):
    """The one interface the rest of Jarvis programs against."""

    #: Human-readable identity, e.g. "openai:gpt-4o" or "mock".
    name: str = "abstract"

    @abstractmethod
    def chat(self, messages: list[Message], tools: Optional[list[dict]] = None) -> ChatResponse:
        """Single-shot completion. Returns the full response."""

    @abstractmethod
    def stream(self, messages: list[Message]) -> Iterator[str]:
        """Yield text chunks as they are generated (for low-latency TTS, §18)."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return an embedding vector per input text (for memory recall, §8)."""

    # Convenience default so callers can do adapter.system_user("...", "...").
    @staticmethod
    def system_user(system: str, user: str) -> list[Message]:
        return [Message("system", system), Message("user", user)]
