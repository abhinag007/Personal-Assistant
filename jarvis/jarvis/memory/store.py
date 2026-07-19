"""MemoryStore (§8) — tiered, recall-frequency-driven memory.

Design (mirrors the brain, per the architecture doc):
  * Every memory has a TIER (conscious / subconscious / unconscious), a RECALL_COUNT,
    and a LAST_RECALLED timestamp.
  * add() writes a new episodic memory into the SUBCONSCIOUS (warm) tier.
  * recall() embeds the cue, cosine-ranks candidates, returns the top-k, and — crucially —
    RECONSOLIDATES each recalled memory: bumps its recall_count, refreshes last_recalled,
    and nudges its tier upward. Recall strengthens memory, like the brain.
  * The nightly Consolidator (separate module) demotes stale memories and promotes hot ones.

Storage is SQLite (system of record) with embeddings stored as JSON. Phase 2+ swaps the
vector search for Qdrant and adds the knowledge graph; the interface stays the same.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Optional

from .embedder import Embedder, HashEmbedder, cosine


class Tier(IntEnum):
    UNCONSCIOUS = 0   # cold archive — never deleted, retrievable on cue
    SUBCONSCIOUS = 1  # warm — recalled recently/often
    CONSCIOUS = 2     # working set — current focus


class MemoryType(str):
    EPISODIC = "episodic"      # what happened, when
    SEMANTIC = "semantic"      # facts about the user / world
    PROCEDURAL = "procedural"  # how a task was done


@dataclass
class MemoryRecord:
    id: str
    text: str
    mem_type: str
    tier: int
    recall_count: int
    salience: float
    created: float
    last_recalled: float
    score: float = 0.0  # similarity at recall time (transient)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    mem_type TEXT NOT NULL,
    tier INTEGER NOT NULL,
    recall_count INTEGER NOT NULL DEFAULT 0,
    salience REAL NOT NULL DEFAULT 0.5,
    created REAL NOT NULL,
    last_recalled REAL NOT NULL,
    embedding TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mem_tier ON memories(tier);
CREATE INDEX IF NOT EXISTS idx_mem_type ON memories(mem_type);

-- Profile: durable identity facts learned from conversation (name, etc.).
-- These are the "who you are" facts (§8 Semantic/Profile) kept for fast, exact lookup.
CREATE TABLE IF NOT EXISTS profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated REAL NOT NULL
);
"""


class MemoryStore:
    def __init__(self, db_path: str | Path, embedder: Optional[Embedder] = None):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._embedder = embedder or HashEmbedder()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ---- writes ----------------------------------------------------------

    def add(
        self,
        text: str,
        mem_type: str = MemoryType.EPISODIC,
        *,
        salience: float = 0.5,
        tier: int = Tier.SUBCONSCIOUS,
    ) -> str:
        mem_id = uuid.uuid4().hex
        now = time.time()
        emb = self._embedder.embed_one(text)
        with self._lock:
            self._conn.execute(
                "INSERT INTO memories (id, text, mem_type, tier, recall_count, salience, "
                "created, last_recalled, embedding) VALUES (?,?,?,?,?,?,?,?,?)",
                (mem_id, text, mem_type, int(tier), 0, salience, now, now, json.dumps(emb)),
            )
            self._conn.commit()
        return mem_id

    # ---- recall ----------------------------------------------------------

    def recall(self, cue: str, k: int = 5, *, reconsolidate: bool = True) -> list[MemoryRecord]:
        """Return the k most relevant memories to `cue`, strengthening them on recall."""
        cue_vec = self._embedder.embed_one(cue)
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, text, mem_type, tier, recall_count, salience, created, "
                "last_recalled, embedding FROM memories"
            ).fetchall()

        scored: list[MemoryRecord] = []
        for r in rows:
            sim = cosine(cue_vec, json.loads(r["embedding"]))
            scored.append(MemoryRecord(
                id=r["id"], text=r["text"], mem_type=r["mem_type"], tier=r["tier"],
                recall_count=r["recall_count"], salience=r["salience"],
                created=r["created"], last_recalled=r["last_recalled"], score=sim,
            ))
        scored.sort(key=lambda m: m.score, reverse=True)
        top = [m for m in scored if m.score > 0][:k]

        if reconsolidate and top:
            self._reconsolidate([m.id for m in top])
        return top

    def _reconsolidate(self, ids: list[str]) -> None:
        """Recall strengthens: bump recall_count, refresh recency, nudge tier up (§8)."""
        now = time.time()
        with self._lock:
            for mem_id in ids:
                row = self._conn.execute(
                    "SELECT tier, recall_count FROM memories WHERE id=?", (mem_id,)
                ).fetchone()
                if row is None:
                    continue
                new_tier = min(int(Tier.CONSCIOUS), row["tier"] + 1)
                self._conn.execute(
                    "UPDATE memories SET recall_count=recall_count+1, last_recalled=?, tier=? WHERE id=?",
                    (now, new_tier, mem_id),
                )
            self._conn.commit()

    # ---- introspection (for consolidation + tests) -----------------------

    def all_records(self) -> list[MemoryRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, text, mem_type, tier, recall_count, salience, created, last_recalled "
                "FROM memories"
            ).fetchall()
        return [MemoryRecord(
            id=r["id"], text=r["text"], mem_type=r["mem_type"], tier=r["tier"],
            recall_count=r["recall_count"], salience=r["salience"],
            created=r["created"], last_recalled=r["last_recalled"],
        ) for r in rows]

    def get(self, mem_id: str) -> Optional[MemoryRecord]:
        with self._lock:
            r = self._conn.execute(
                "SELECT id, text, mem_type, tier, recall_count, salience, created, last_recalled "
                "FROM memories WHERE id=?", (mem_id,)
            ).fetchone()
        if r is None:
            return None
        return MemoryRecord(
            id=r["id"], text=r["text"], mem_type=r["mem_type"], tier=r["tier"],
            recall_count=r["recall_count"], salience=r["salience"],
            created=r["created"], last_recalled=r["last_recalled"],
        )

    def set_tier(self, mem_id: str, tier: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE memories SET tier=? WHERE id=?", (int(tier), mem_id))
            self._conn.commit()

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]

    # ---- profile (durable learned identity facts) ------------------------

    def set_profile(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO profile (key, value, updated) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
                (key, value, time.time()),
            )
            self._conn.commit()

    def get_profile(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute("SELECT value FROM profile WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def all_profile(self) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM profile").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def close(self) -> None:
        with self._lock:
            self._conn.close()
