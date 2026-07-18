"""Audit log tests (§16) — append-only, readable, carries correlation ids."""
from jarvis.audit import AuditLog


def test_records_append(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("write_sandbox", "wrote a.txt", risk="reversible")
    log.record("send_message", "sent email", outcome="approved", risk="irreversible")
    entries = log.read_all()
    assert len(entries) == 2
    assert entries[0]["action"] == "write_sandbox"
    assert entries[1]["outcome"] == "approved"


def test_correlation_id_returned_and_stored(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    cid = log.record("read_file", "read config")
    assert cid
    assert log.read_all()[0]["correlation_id"] == cid


def test_is_append_only_across_instances(tmp_path):
    path = tmp_path / "audit.jsonl"
    AuditLog(path).record("a", "first")
    # A new instance must append, not overwrite.
    AuditLog(path).record("b", "second")
    entries = AuditLog(path).read_all()
    assert [e["action"] for e in entries] == ["a", "b"]


def test_entries_have_timestamp(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("x", "y")
    assert "ts" in log.read_all()[0]
