"""Consolidator (§8, §25) — the nightly "sleep" pass.

Runs once a day (scheduled by the background brain in Phase 3). It reorganizes memory the
way sleep consolidates a day's experience:

  * PROMOTE: memories recalled often/recently drift toward the conscious/subconscious tiers.
  * DECAY: memories not recalled for a while drift downward toward the unconscious tier,
    mirroring the forgetting curve — but nothing is ever deleted, only demoted.

Fact extraction and knowledge-graph linking (the richer part of §8) arrive in Phase 2;
Phase 1 implements the tier dynamics, which is the core behavior.
"""
from __future__ import annotations

import time

from .store import MemoryStore, Tier


class Consolidator:
    def __init__(
        self,
        store: MemoryStore,
        *,
        decay_after_seconds: float = 7 * 24 * 3600,   # not recalled in ~a week → decay
        promote_recall_threshold: int = 3,            # recalled ≥3 times → promote
    ):
        self.store = store
        self.decay_after = decay_after_seconds
        self.promote_threshold = promote_recall_threshold

    def run(self, *, now: float | None = None) -> dict:
        """Execute one consolidation pass. Returns a summary (for the audit log)."""
        now = now if now is not None else time.time()
        promoted = decayed = 0

        for rec in self.store.all_records():
            age_since_recall = now - rec.last_recalled

            # DECAY: stale memories sink one tier (never below unconscious).
            if age_since_recall > self.decay_after and rec.tier > int(Tier.UNCONSCIOUS):
                self.store.set_tier(rec.id, rec.tier - 1)
                decayed += 1
                continue

            # PROMOTE: frequently recalled memories rise one tier (never above conscious).
            if rec.recall_count >= self.promote_threshold and rec.tier < int(Tier.CONSCIOUS):
                self.store.set_tier(rec.id, rec.tier + 1)
                promoted += 1

        return {
            "promoted": promoted,
            "decayed": decayed,
            "total": self.store.count(),
            "ran_at": now,
        }
