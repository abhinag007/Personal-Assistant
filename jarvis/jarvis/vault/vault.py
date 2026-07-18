"""Encrypted secrets & credential vault (§14).

Secrets (API keys, bot tokens, site logins) are encrypted at rest with a symmetric key.
The master key itself is NOT stored next to the data — it lives in the OS keychain
(macOS Keychain via `keyring`). Callers request a secret by name; the plaintext exists
only transiently in memory and is never written to disk or placed in a model prompt.

Key providers are pluggable:
  * KeyringKeyProvider (default) — master key in the OS keychain. Use on the real machine.
  * FileKeyProvider — master key in a 0600 file. For headless/CI/testing ONLY (less secure).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken


class KeyProvider(Protocol):
    def get_or_create_key(self) -> bytes: ...


class KeyringKeyProvider:
    """Stores the Fernet master key in the OS keychain (macOS Keychain, etc.)."""

    def __init__(self, service: str = "jarvis-vault", username: str = "master-key"):
        self.service = service
        self.username = username

    def get_or_create_key(self) -> bytes:
        import keyring  # imported lazily so tests don't require a keychain backend

        existing = keyring.get_password(self.service, self.username)
        if existing:
            return existing.encode("ascii")
        key = Fernet.generate_key()
        keyring.set_password(self.service, self.username, key.decode("ascii"))
        return key


class FileKeyProvider:
    """Stores the master key in a local file with 0600 perms. Testing/headless only."""

    def __init__(self, key_path: str | os.PathLike):
        self.key_path = Path(key_path)

    def get_or_create_key(self) -> bytes:
        if self.key_path.exists():
            return self.key_path.read_bytes()
        key = Fernet.generate_key()
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.write_bytes(key)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key


class Vault:
    """A tiny encrypted key-value store for secrets."""

    def __init__(self, store_path: str | os.PathLike, key_provider: KeyProvider | None = None):
        self.store_path = Path(store_path)
        self._key_provider = key_provider or KeyringKeyProvider()
        self._fernet = Fernet(self._key_provider.get_or_create_key())

    def _load(self) -> dict[str, str]:
        if not self.store_path.exists():
            return {}
        blob = self.store_path.read_bytes()
        if not blob:
            return {}
        try:
            plaintext = self._fernet.decrypt(blob)
        except InvalidToken as exc:  # wrong key / tampered file
            raise RuntimeError(
                "Vault decryption failed — wrong master key or the vault file was tampered with."
            ) from exc
        return json.loads(plaintext.decode("utf-8"))

    def _save(self, data: dict[str, str]) -> None:
        plaintext = json.dumps(data).encode("utf-8")
        blob = self._fernet.encrypt(plaintext)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_bytes(blob)
        try:
            os.chmod(self.store_path, 0o600)
        except OSError:
            pass

    # ---- public API ------------------------------------------------------

    def set_secret(self, name: str, value: str) -> None:
        data = self._load()
        data[name] = value
        self._save(data)

    def get_secret(self, name: str) -> str | None:
        return self._load().get(name)

    def delete_secret(self, name: str) -> bool:
        data = self._load()
        if name in data:
            del data[name]
            self._save(data)
            return True
        return False

    def list_names(self) -> list[str]:
        """Return secret NAMES only — never values."""
        return sorted(self._load().keys())
