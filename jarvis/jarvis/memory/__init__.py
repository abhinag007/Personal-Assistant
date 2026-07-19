"""Brain-like memory (§8) — conscious / subconscious / unconscious tiers.

Public surface:
  * MemoryStore   — add/recall memories; tiers move by recall frequency.
  * Tier, MemoryType — enums.
  * Consolidator  — the nightly "sleep" pass (promote/decay/relink).
  * Embedder / AdapterEmbedder / HashEmbedder — vectorization strategies.
"""
from .embedder import AdapterEmbedder, Embedder, HashEmbedder  # noqa: F401
from .store import MemoryRecord, MemoryStore, MemoryType, Tier  # noqa: F401
from .consolidation import Consolidator  # noqa: F401
from .scheduler import NightlyConsolidationScheduler  # noqa: F401
