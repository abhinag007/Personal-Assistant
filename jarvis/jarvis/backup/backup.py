"""Encrypted memory backup + restore (§42).

Jarvis's intelligence lives in local files (memory DB, skills, tools, journal). This makes
encrypted snapshots so a disk failure doesn't erase everything and so Jarvis is portable to
a new machine. Backups are encrypted with a key you hold; nothing is stored in plaintext.

Phase 1 backs up the memory directory. Later phases extend the same mechanism to skills,
tools, and the decision journal.
"""
from __future__ import annotations

import io
import tarfile
import time
from pathlib import Path

from cryptography.fernet import Fernet

from ..vault.vault import FileKeyProvider, KeyProvider, KeyringKeyProvider


class MemoryBackup:
    def __init__(self, key_provider: KeyProvider | None = None):
        # Reuses the vault's key strategy: keychain by default, file for headless/tests.
        self._key_provider = key_provider or KeyringKeyProvider(
            service="jarvis-backup", username="backup-key"
        )
        self._fernet = Fernet(self._key_provider.get_or_create_key())

    def backup(self, source_dir: str | Path, dest_dir: str | Path) -> Path:
        """Create an encrypted snapshot of `source_dir`; returns the backup file path."""
        source_dir = Path(source_dir)
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        # 1. Tar the source into memory.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            if source_dir.exists():
                tar.add(source_dir, arcname=source_dir.name)
        plaintext = buf.getvalue()

        # 2. Encrypt and write.
        blob = self._fernet.encrypt(plaintext)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = dest_dir / f"jarvis-memory-{stamp}.enc"
        out.write_bytes(blob)
        return out

    def restore(self, backup_file: str | Path, target_dir: str | Path) -> Path:
        """Decrypt and extract a backup into `target_dir`. Returns target_dir."""
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        blob = Path(backup_file).read_bytes()
        plaintext = self._fernet.decrypt(blob)  # raises on wrong key / tampering
        buf = io.BytesIO(plaintext)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            # filter="data" (Python 3.12+) blocks unsafe members (absolute paths, ..).
            try:
                tar.extractall(target_dir, filter="data")
            except TypeError:  # older Python without the filter kwarg
                tar.extractall(target_dir)
        return target_dir
