"""Embedders (§8) — turn text into vectors for semantic recall.

Two implementations:
  * AdapterEmbedder — uses the active ModelAdapter (OpenAI now, local later).
  * HashEmbedder    — deterministic, offline, dependency-free; used for tests/offline.

Both share the same interface so the store doesn't care which is in use.
"""
from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod


class Embedder(ABC):
    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class HashEmbedder(Embedder):
    """Deterministic bag-of-words hashing embedder (unit-normalized)."""

    def __init__(self, dim: int = 64):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for token in text.lower().split():
                h = int(hashlib.sha1(token.encode("utf-8")).hexdigest(), 16)
                vec[h % self.dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class AdapterEmbedder(Embedder):
    """Wraps a ModelAdapter's embed() (real semantic embeddings)."""

    def __init__(self, adapter, dim: int = 1536):
        self._adapter = adapter
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._adapter.embed(texts)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
