"""MockAdapter — a deterministic, offline brain for tests and dev without an API key (§1).

It never calls the network. Responses are deterministic so tests can assert on them,
and `embed()` produces stable vectors so memory recall is testable without OpenAI.
This is also what runs the conformance suite both adapters must pass.
"""
from __future__ import annotations

import hashlib
import math
from typing import Iterator, Optional

from .adapter import ChatResponse, Message, ModelAdapter

_EMBED_DIM = 64


def _hash_embed(text: str, dim: int = _EMBED_DIM) -> list[float]:
    """Deterministic bag-of-words hashing embedder (unit-normalized).

    Not semantically smart, but stable and dependency-free — enough to test that
    memory recall returns the right items. Real semantic embeddings come from the
    OpenAI/local embedder in production.
    """
    vec = [0.0] * dim
    for token in text.lower().split():
        h = int(hashlib.sha1(token.encode("utf-8")).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class MockAdapter(ModelAdapter):
    name = "mock"

    def chat(self, messages: list[Message], tools: Optional[list[dict]] = None) -> ChatResponse:
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        text = f"[mock reply] I heard: {last_user.strip()}"
        return ChatResponse(
            text=text,
            model=self.name,
            prompt_tokens=sum(len(m.content.split()) for m in messages),
            completion_tokens=len(text.split()),
        )

    def stream(self, messages: list[Message]) -> Iterator[str]:
        # Yield word-by-word so streaming/TTFW logic can be exercised.
        for word in self.chat(messages).text.split():
            yield word + " "

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_hash_embed(t) for t in texts]
