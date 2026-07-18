"""Git rollback tests (§17) — init, auto-commit, revert."""
import shutil

import pytest

from jarvis.core.git_tracker import GitTracker

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def test_init_creates_repo(tmp_path):
    gt = GitTracker(str(tmp_path / "sandbox"))
    gt.init()
    assert gt.is_repo()


def test_auto_commit_records_changes(tmp_path):
    sandbox = tmp_path / "sandbox"
    gt = GitTracker(str(sandbox))
    gt.init()
    (sandbox / "note.txt").write_text("hello")
    assert gt.auto_commit("add note") is True
    commits = gt.last_commits()
    assert any("add note" in c for c in commits)


def test_revert_undoes_last_change(tmp_path):
    sandbox = tmp_path / "sandbox"
    gt = GitTracker(str(sandbox))
    gt.init()
    f = sandbox / "note.txt"
    f.write_text("v1")
    gt.auto_commit("v1")
    f.write_text("v2 BAD")
    gt.auto_commit("v2")
    assert gt.revert_last() is True
    # After reverting the v2 commit, content returns to v1.
    assert f.read_text() == "v1"
