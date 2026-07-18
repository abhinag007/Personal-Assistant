"""Staging store (§26) — speculative work held provisionally.

Anything Jarvis produces on its own guess (a drafted reminder, a roadmap, research) lands
here first. It's surfaced to you; if you want it, it's **promoted** to real storage; if not,
it's **discarded**. Nothing speculative clutters your real data.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class StagedItem:
    id: str
    kind: str          # e.g. "reminder", "roadmap", "research", "draft"
    title: str
    payload: dict
    created: float


class StagingStore:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, item_id: str) -> Path:
        return self.dir / f"{item_id}.json"

    def add(self, kind: str, title: str, payload: dict) -> str:
        item_id = uuid.uuid4().hex[:12]
        data = {"id": item_id, "kind": kind, "title": title,
                "payload": payload, "created": time.time()}
        self._path(item_id).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return item_id

    def list(self) -> list[StagedItem]:
        items = []
        for p in sorted(self.dir.glob("*.json")):
            d = json.loads(p.read_text())
            items.append(StagedItem(d["id"], d["kind"], d["title"], d["payload"], d["created"]))
        return items

    def get(self, item_id: str) -> Optional[StagedItem]:
        p = self._path(item_id)
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        return StagedItem(d["id"], d["kind"], d["title"], d["payload"], d["created"])

    def discard(self, item_id: str) -> bool:
        p = self._path(item_id)
        if p.exists():
            p.unlink()
            return True
        return False

    def promote(self, item_id: str, promoter) -> bool:
        """Hand the item to a `promoter(StagedItem)` callback, then remove it from staging."""
        item = self.get(item_id)
        if item is None:
            return False
        promoter(item)
        self.discard(item_id)
        return True
