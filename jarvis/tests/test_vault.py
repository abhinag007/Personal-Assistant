"""Vault tests (§14) — encryption round-trip, secrecy, tamper detection."""
import pytest

from jarvis.vault import Vault, FileKeyProvider


@pytest.fixture
def vault(tmp_path):
    # Use the file-based key provider so the test runs headless (no OS keychain).
    kp = FileKeyProvider(tmp_path / "master.key")
    return Vault(tmp_path / "vault.enc", key_provider=kp), tmp_path


def test_set_and_get_roundtrip(vault):
    v, _ = vault
    v.set_secret("openai_api_key", "sk-secret-123")
    assert v.get_secret("openai_api_key") == "sk-secret-123"


def test_stored_file_is_encrypted(vault):
    v, tmp_path = vault
    v.set_secret("token", "super-secret-value")
    blob = (tmp_path / "vault.enc").read_bytes()
    # The plaintext must not appear anywhere in the encrypted file.
    assert b"super-secret-value" not in blob


def test_list_names_never_leaks_values(vault):
    v, _ = vault
    v.set_secret("a", "value-a")
    v.set_secret("b", "value-b")
    names = v.list_names()
    assert names == ["a", "b"]
    assert "value-a" not in names and "value-b" not in names


def test_delete_secret(vault):
    v, _ = vault
    v.set_secret("temp", "x")
    assert v.delete_secret("temp") is True
    assert v.get_secret("temp") is None
    assert v.delete_secret("temp") is False


def test_wrong_key_fails_to_decrypt(tmp_path):
    kp1 = FileKeyProvider(tmp_path / "k1.key")
    Vault(tmp_path / "vault.enc", key_provider=kp1).set_secret("s", "v")
    # A different key must not be able to read the vault.
    kp2 = FileKeyProvider(tmp_path / "k2.key")
    with pytest.raises(RuntimeError):
        Vault(tmp_path / "vault.enc", key_provider=kp2).get_secret("s")


def test_persistence_across_instances(tmp_path):
    kp = FileKeyProvider(tmp_path / "master.key")
    Vault(tmp_path / "vault.enc", key_provider=kp).set_secret("k", "v")
    # A fresh Vault with the same key must read it back.
    kp2 = FileKeyProvider(tmp_path / "master.key")
    assert Vault(tmp_path / "vault.enc", key_provider=kp2).get_secret("k") == "v"
