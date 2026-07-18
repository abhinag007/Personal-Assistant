"""Backup (§42) + tracing (§2A.5) tests."""
from jarvis.backup import MemoryBackup
from jarvis.tracing.tracer import LocalTracer, Tracer
from jarvis.vault.vault import FileKeyProvider


# ---- backup --------------------------------------------------------------

def test_backup_and_restore_roundtrip(tmp_path):
    # Create a fake memory dir.
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "jarvis.db").write_text("pretend db contents")

    kp = FileKeyProvider(tmp_path / "backup.key")
    backup = MemoryBackup(key_provider=kp)
    archive = backup.backup(mem, tmp_path / "backups")
    assert archive.exists()

    # Encrypted archive must not contain the plaintext.
    assert b"pretend db contents" not in archive.read_bytes()

    # Restore into a fresh location.
    restored_root = tmp_path / "restored"
    backup.restore(archive, restored_root)
    assert (restored_root / "memory" / "jarvis.db").read_text() == "pretend db contents"


def test_backup_wrong_key_cannot_restore(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "f.txt").write_text("secret")
    archive = MemoryBackup(key_provider=FileKeyProvider(tmp_path / "k1.key")).backup(
        mem, tmp_path / "b"
    )
    import pytest
    with pytest.raises(Exception):
        MemoryBackup(key_provider=FileKeyProvider(tmp_path / "k2.key")).restore(
            archive, tmp_path / "out"
        )


# ---- tracing -------------------------------------------------------------

def test_noop_tracer_does_nothing():
    t = Tracer.noop()
    with t.span("x") as s:
        s.set("k", 1)
    # No exception, nothing to assert beyond it not crashing.


def test_local_tracer_records_spans_and_nesting(tmp_path):
    t = LocalTracer(tmp_path / "traces.jsonl")
    with t.span("outer") as outer:
        with t.span("inner") as inner:
            inner.set("detail", "x")
    records = t.read_all()
    names = [r["name"] for r in records]
    # inner finishes first (nested), then outer.
    assert names == ["inner", "outer"]
    inner_rec = records[0]
    outer_rec = records[1]
    assert inner_rec["parent_id"] == outer_rec["id"]
    assert "duration_s" in outer_rec


def test_tracer_records_error(tmp_path):
    t = LocalTracer(tmp_path / "traces.jsonl")
    import pytest
    with pytest.raises(ValueError):
        with t.span("boom"):
            raise ValueError("kaboom")
    rec = t.read_all()[0]
    assert "error" in rec and "kaboom" in rec["error"]
