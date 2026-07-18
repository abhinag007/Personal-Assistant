"""Memory tests (§8) — recall, reconsolidation (recall strengthens), tiers."""
from jarvis.memory import MemoryStore, MemoryType, Tier
from jarvis.memory.embedder import HashEmbedder


def _store(tmp_path):
    return MemoryStore(tmp_path / "mem.db", embedder=HashEmbedder())


def test_add_and_recall(tmp_path):
    m = _store(tmp_path)
    m.add("Abhi loves black coffee in the morning", MemoryType.SEMANTIC)
    m.add("Abhi is building a Jarvis assistant", MemoryType.SEMANTIC)
    hits = m.recall("what does Abhi drink", k=1)
    assert hits
    assert "coffee" in hits[0].text


def test_recall_reconsolidates_and_bumps_count(tmp_path):
    m = _store(tmp_path)
    mem_id = m.add("Abhi lives for building things")
    before = m.get(mem_id)
    assert before.recall_count == 0
    # Recall it via a matching cue.
    m.recall("building things", k=3)
    after = m.get(mem_id)
    assert after.recall_count == 1
    assert after.last_recalled >= before.last_recalled
    # Recall nudged it up a tier (subconscious -> conscious).
    assert after.tier >= before.tier


def test_new_memory_starts_subconscious(tmp_path):
    m = _store(tmp_path)
    mem_id = m.add("a fresh memory")
    assert m.get(mem_id).tier == int(Tier.SUBCONSCIOUS)


def test_persistence(tmp_path):
    m = _store(tmp_path)
    m.add("persistent fact about Abhi")
    m.close()
    m2 = MemoryStore(tmp_path / "mem.db", embedder=HashEmbedder())
    assert m2.count() == 1
