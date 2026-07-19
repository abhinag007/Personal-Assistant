"""Consolidation tests (§8) — nightly promote/decay of memory tiers."""
import time

from jarvis.memory import MemoryStore, Tier
from jarvis.memory.consolidation import Consolidator
from jarvis.memory.embedder import HashEmbedder
from jarvis.memory.scheduler import NightlyConsolidationScheduler


def _store(tmp_path):
    return MemoryStore(tmp_path / "mem.db", embedder=HashEmbedder())


def test_frequently_recalled_is_promoted(tmp_path):
    m = _store(tmp_path)
    mem_id = m.add("hot memory", tier=Tier.UNCONSCIOUS)
    # Simulate several recalls to push recall_count up.
    for _ in range(3):
        m.recall("hot memory", k=1)
    # Force tier back down to isolate the consolidator's promotion behavior.
    m.set_tier(mem_id, int(Tier.UNCONSCIOUS))
    summary = Consolidator(m, promote_recall_threshold=3).run()
    assert summary["promoted"] >= 1
    assert m.get(mem_id).tier > int(Tier.UNCONSCIOUS)


def test_stale_memory_decays(tmp_path):
    m = _store(tmp_path)
    mem_id = m.add("stale memory", tier=Tier.CONSCIOUS)
    # Pretend it was last recalled long ago by running consolidation "in the future".
    future = time.time() + 30 * 24 * 3600  # 30 days later
    summary = Consolidator(m, decay_after_seconds=7 * 24 * 3600).run(now=future)
    assert summary["decayed"] >= 1
    assert m.get(mem_id).tier < int(Tier.CONSCIOUS)


def test_nothing_is_deleted(tmp_path):
    m = _store(tmp_path)
    m.add("keep me forever", tier=Tier.CONSCIOUS)
    future = time.time() + 365 * 24 * 3600
    Consolidator(m).run(now=future)
    # Demoted, never removed.
    assert m.count() == 1


def test_nightly_scheduler_runs_once_after_configured_hour(tmp_path):
    m = _store(tmp_path)
    mem_id = m.add("hot scheduled memory", tier=Tier.UNCONSCIOUS)
    for _ in range(3):
        m.recall("hot scheduled memory", k=1)
    m.set_tier(mem_id, int(Tier.UNCONSCIOUS))
    scheduler = NightlyConsolidationScheduler(
        m, tmp_path / "consolidation_state.json", hour=2, log=lambda *_: None)

    before_hour = time.mktime(time.struct_time((2026, 7, 19, 1, 30, 0, 0, 0, -1)))
    after_hour = time.mktime(time.struct_time((2026, 7, 19, 2, 30, 0, 0, 0, -1)))
    assert scheduler.poll(now=before_hour) is None
    summary = scheduler.poll(now=after_hour)
    assert summary and summary["promoted"] >= 1
    assert scheduler.poll(now=after_hour + 60) is None
