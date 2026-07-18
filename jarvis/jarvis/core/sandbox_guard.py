"""Sandbox guard — the single choke-point for all file I/O (§17).

Every file operation the assistant performs MUST go through this module. It is the
one place that decides whether a path may be read or written. The model never gets a
raw file handle; it only ever asks the guard.

Rules:
  * Reads: allowed anywhere the OS permits (the assistant can look at the whole PC).
  * Writes/deletes: allowed ONLY inside the sandbox root. Anything else is denied and
    must be escalated to the approval engine by the caller.
  * The immutable core directory is NEVER writable, even if it sits inside the sandbox.

Security properties enforced here:
  * Symlink escapes are blocked (paths are fully resolved before the containment check).
  * "../" traversal is blocked (resolution + containment check).
  * Absolute paths outside the sandbox are blocked.
"""
from __future__ import annotations

import os
from pathlib import Path


class SandboxViolation(Exception):
    """Raised when an operation would write outside the sandbox or into the core."""


class SandboxGuard:
    def __init__(self, sandbox_root: str | os.PathLike, core_root: str | os.PathLike | None = None):
        # Resolve to a real, absolute, symlink-free path once, at construction.
        self.sandbox_root = Path(sandbox_root).resolve()
        if not self.sandbox_root.exists():
            self.sandbox_root.mkdir(parents=True, exist_ok=True)
        # The core dir is never writable. By default it's this package's own core/.
        self.core_root = (
            Path(core_root).resolve() if core_root is not None
            else Path(__file__).resolve().parent
        )

    # ---- internal helpers ------------------------------------------------

    def _resolve(self, path: str | os.PathLike) -> Path:
        """Resolve a path to an absolute, symlink-free form.

        We resolve the *parent* for not-yet-existing files (so creating a new file
        inside the sandbox works) while still following symlinks on the parent chain
        to prevent a symlinked parent from escaping the sandbox.
        """
        p = Path(path)
        if not p.is_absolute():
            p = self.sandbox_root / p
        # strict=False so we can resolve paths for files that don't exist yet;
        # this still canonicalizes '..' and follows existing symlinks in the chain.
        return p.resolve()

    @staticmethod
    def _is_within(child: Path, parent: Path) -> bool:
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False

    def _assert_writable(self, path: str | os.PathLike) -> Path:
        resolved = self._resolve(path)
        # 1. Never allow writes into the immutable core.
        if resolved == self.core_root or self._is_within(resolved, self.core_root):
            raise SandboxViolation(
                f"Refused: {resolved} is inside the immutable core (§23). "
                "Core changes require explicit, out-of-band human approval."
            )
        # 2. Only allow writes inside the sandbox root.
        if not self._is_within(resolved, self.sandbox_root):
            raise SandboxViolation(
                f"Refused: {resolved} is outside the sandbox root {self.sandbox_root}. "
                "Writing outside the sandbox requires human approval (§11)."
            )
        return resolved

    # ---- public API ------------------------------------------------------

    def is_writable(self, path: str | os.PathLike) -> bool:
        """Non-raising check: may the assistant write here?"""
        try:
            self._assert_writable(path)
            return True
        except SandboxViolation:
            return False

    def read_text(self, path: str | os.PathLike, encoding: str = "utf-8") -> str:
        """Reads are allowed anywhere the OS permits."""
        return self._resolve(path).read_text(encoding=encoding)

    def read_bytes(self, path: str | os.PathLike) -> bytes:
        return self._resolve(path).read_bytes()

    def write_text(self, path: str | os.PathLike, data: str, encoding: str = "utf-8") -> Path:
        target = self._assert_writable(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding=encoding)
        return target

    def write_bytes(self, path: str | os.PathLike, data: bytes) -> Path:
        target = self._assert_writable(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def delete(self, path: str | os.PathLike) -> None:
        target = self._assert_writable(path)
        if target.is_dir():
            raise SandboxViolation("Directory deletion is not permitted via the guard in Phase 0.")
        if target.exists():
            target.unlink()

    def makedirs(self, path: str | os.PathLike) -> Path:
        target = self._assert_writable(path)
        target.mkdir(parents=True, exist_ok=True)
        return target
