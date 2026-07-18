"""Git-backed rollback for the sandbox (§17).

The sandbox is a local git repository. After every change the assistant makes, we
auto-commit with a descriptive message, so any change can be reverted. This is what
lets sandbox writes count as "reversible" in the approval engine (§11).

Uses plain `git` via subprocess to avoid extra dependencies.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitTracker:
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=False,
        )

    def is_repo(self) -> bool:
        return (self.repo_path / ".git").exists()

    def init(self) -> None:
        """Initialize the sandbox as a git repo (idempotent)."""
        self.repo_path.mkdir(parents=True, exist_ok=True)
        if not self.is_repo():
            self._git("init")
            # Local identity so commits work without global git config.
            self._git("config", "user.name", "Jarvis")
            self._git("config", "user.email", "jarvis@localhost")
            # An initial empty commit so there's always a root to revert to.
            self._git("commit", "--allow-empty", "-m", "chore: initialize sandbox")

    def auto_commit(self, message: str) -> bool:
        """Stage everything and commit. Returns True if a commit was made."""
        if not self.is_repo():
            self.init()
        self._git("add", "-A")
        # Nothing staged? git commit returns non-zero; treat as "no change".
        result = self._git("commit", "-m", message)
        return result.returncode == 0

    def last_commits(self, n: int = 5) -> list[str]:
        result = self._git("log", f"-{n}", "--oneline")
        if result.returncode != 0:
            return []
        return [ln for ln in result.stdout.splitlines() if ln.strip()]

    def revert_last(self) -> bool:
        """Undo the most recent commit's changes (safety net). Returns success."""
        result = self._git("revert", "--no-edit", "HEAD")
        return result.returncode == 0
