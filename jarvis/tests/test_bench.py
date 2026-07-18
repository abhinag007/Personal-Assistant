"""TTFW benchmark tests (§18)."""
from jarvis.brain import BrainLoop
from jarvis.brain.bench import run_benchmark
from jarvis.llm import MockAdapter
from jarvis.memory import MemoryStore
from jarvis.memory.embedder import HashEmbedder


def _brain(tmp_path):
    mem = MemoryStore(tmp_path / "mem.db", embedder=HashEmbedder())
    return BrainLoop(MockAdapter(), mem, curious=False)


def test_benchmark_reports_stats(tmp_path):
    stats = run_benchmark(_brain(tmp_path), n=4)
    assert stats["n"] == 4
    for key in ("median_s", "p95_s", "min_s", "max_s", "meets_target"):
        assert key in stats
    # Mock adapter is instant, so it must comfortably meet the target.
    assert stats["meets_target"] is True


def test_benchmark_respects_n(tmp_path):
    assert run_benchmark(_brain(tmp_path), n=2)["n"] == 2
