"""RED-TEAM: the sandbox guard must block every escape attempt (§17).

This is the most important test file in Phase 0. If any of these fail, the whole
safety model is compromised. It actively tries to break out of the sandbox.
"""
import os
from pathlib import Path

import pytest

from jarvis.core.sandbox_guard import SandboxGuard, SandboxViolation


@pytest.fixture
def guard(tmp_path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    return SandboxGuard(sandbox), sandbox


# ---- allowed operations --------------------------------------------------

def test_write_inside_sandbox_allowed(guard):
    g, sandbox = guard
    g.write_text("notes/todo.txt", "hello")
    assert (sandbox / "notes" / "todo.txt").read_text() == "hello"


def test_read_anywhere_allowed(guard, tmp_path):
    g, _ = guard
    outside = tmp_path / "outside.txt"
    outside.write_text("readable")
    # Reads are permitted anywhere the OS allows.
    assert g.read_text(outside) == "readable"


# ---- RED-TEAM: escapes that must be blocked ------------------------------

def test_absolute_path_outside_blocked(guard):
    g, _ = guard
    with pytest.raises(SandboxViolation):
        g.write_text("/tmp/escape.txt", "nope")


def test_dotdot_traversal_blocked(guard):
    g, sandbox = guard
    with pytest.raises(SandboxViolation):
        g.write_text("../escape.txt", "nope")


def test_deep_dotdot_traversal_blocked(guard):
    g, _ = guard
    with pytest.raises(SandboxViolation):
        g.write_text("a/b/../../../../../etc/passwd", "nope")


def test_symlink_escape_blocked(guard, tmp_path):
    """A symlink inside the sandbox pointing outside must not allow writes through it."""
    g, sandbox = guard
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()
    link = sandbox / "backdoor"
    try:
        os.symlink(secret_dir, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    with pytest.raises(SandboxViolation):
        g.write_text("backdoor/pwned.txt", "nope")
    assert not (secret_dir / "pwned.txt").exists()


def test_core_is_never_writable(tmp_path):
    """Even if the core lives inside the sandbox, it must be unwritable (§23)."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    core = sandbox / "core"
    core.mkdir()
    g = SandboxGuard(sandbox, core_root=core)
    with pytest.raises(SandboxViolation):
        g.write_text("core/kill_switch.py", "malicious override")


def test_is_writable_predicate(guard):
    g, _ = guard
    assert g.is_writable("ok.txt") is True
    assert g.is_writable("/etc/hosts") is False
    assert g.is_writable("../nope.txt") is False


def test_delete_outside_blocked(guard, tmp_path):
    g, _ = guard
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    with pytest.raises(SandboxViolation):
        g.delete(victim)
    assert victim.exists()
