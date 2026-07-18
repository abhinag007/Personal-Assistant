"""First-run setup wizard (§41).

Phase 0 scope: choose the sandbox path, initialize it as a git repo, store a first
secret in the vault, and explain the kill switch. Later phases add voice enrollment,
phone linking, and preferences to this same flow.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..audit import AuditLog
from ..config import Config, DEFAULT_CONFIG_DIR
from ..core.git_tracker import GitTracker
from ..core.policy import KILL_PHRASE
from ..vault import Vault, KeyringKeyProvider


def run_onboarding(config_dir: str | os.PathLike | None = None, *, input_fn=input, print_fn=print) -> Config:
    """Interactive first-run setup. `input_fn`/`print_fn` are injectable for testing."""
    cfg_dir = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    cfg_dir.mkdir(parents=True, exist_ok=True)

    print_fn("\n=== JARVIS — First-Run Setup (Phase 0) ===\n")

    # 1. Sandbox path
    default_sandbox = str(Path.home() / "jarvis-sandbox")
    answer = input_fn(f"Where should Jarvis's sandbox live? [{default_sandbox}]: ").strip()
    sandbox_path = answer or default_sandbox

    tracker = GitTracker(sandbox_path)
    tracker.init()
    print_fn(f"  ✓ Sandbox ready and git-tracked at: {sandbox_path}")

    # 2. First secret (e.g. OpenAI key) in the vault
    vault = Vault(cfg_dir / "vault.enc", key_provider=KeyringKeyProvider())
    name = input_fn("Name of a secret to store now (e.g. 'openai_api_key', blank to skip): ").strip()
    if name:
        value = input_fn(f"  Value for '{name}': ").strip()
        if value:
            vault.set_secret(name, value)
            print_fn(f"  ✓ Stored '{name}' in the encrypted vault (value never shown again).")

    # 3. Kill switch explainer
    print_fn("\n  IMPORTANT — your emergency stop:")
    print_fn(f'    Say or type "{KILL_PHRASE.title()}" at any time to shut everything down instantly.')
    print_fn("    This cannot be disabled by Jarvis.\n")

    # 4. Save config + audit
    cfg = Config.load(cfg_dir)
    cfg.sandbox_path = sandbox_path
    cfg.onboarded = True
    cfg.save(cfg_dir)

    audit = AuditLog(cfg_dir / "logs" / "audit.jsonl")
    audit.record("onboarding", "Completed first-run setup", risk="reversible",
                 reason="User ran the onboarding wizard.")

    print_fn("=== Setup complete. ===\n")
    return cfg
