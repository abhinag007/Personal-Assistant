"""First-run setup wizard (§41).

Phase 0/2 scope: choose the sandbox path, git-init it, manage secrets (OpenAI key, Telegram
bot token + chat id), and explain the kill switch. On re-run it doesn't blindly re-ask —
for each stored secret it shows it's set and lets you keep or change it. Secret values are
entered with hidden input so they never echo on screen.
"""
from __future__ import annotations

import getpass
import os
from pathlib import Path

from ..audit import AuditLog
from ..config import Config, DEFAULT_CONFIG_DIR
from ..core.git_tracker import GitTracker
from ..core.policy import KILL_PHRASE
from ..vault import Vault, KeyringKeyProvider


def _manage_secret(vault, name, label, *, input_fn, print_fn, secret_input_fn, secret=True):
    """Keep-or-change flow for one secret. Returns True if a value is present after."""
    existing = None
    try:
        existing = vault.get_secret(name)
    except Exception:
        existing = None

    if existing:
        keep = input_fn(f"  {label} is already stored. Keep it? (Y/n): ").strip().lower()
        if keep in ("", "y", "yes"):
            print_fn(f"  ✓ Keeping existing {label}.")
            return True
        prompt = f"  New {label}: "
    else:
        prompt = f"  {label} (blank to skip): "

    value = (secret_input_fn(prompt) if secret else input_fn(prompt)).strip()
    if value:
        vault.set_secret(name, value)
        print_fn(f"  ✓ Stored {label}.")
        return True
    print_fn(f"  – Skipped {label}.")
    return bool(existing)


def run_onboarding(config_dir=None, *, input_fn=input, print_fn=print, secret_input_fn=None):
    """Interactive setup. input_fn/print_fn/secret_input_fn are injectable for testing."""
    secret_input_fn = secret_input_fn or getpass.getpass
    cfg_dir = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    cfg_dir.mkdir(parents=True, exist_ok=True)

    cfg = Config.load(cfg_dir)
    first_time = not cfg.onboarded
    print_fn("\n=== JARVIS — Setup ===" + ("" if first_time else " (re-run: change only what you want)") + "\n")

    # 1. Sandbox path (defaults to the existing one on re-run)
    default_sandbox = cfg.sandbox_path or str(Path.home() / "jarvis-sandbox")
    answer = input_fn(f"Sandbox location [{default_sandbox}]: ").strip()
    sandbox_path = answer or default_sandbox
    GitTracker(sandbox_path).init()
    print_fn(f"  ✓ Sandbox ready and git-tracked at: {sandbox_path}")

    # 2. Secrets — keep-or-change on re-run
    vault = Vault(cfg_dir / "vault.enc", key_provider=KeyringKeyProvider())
    common = dict(input_fn=input_fn, print_fn=print_fn, secret_input_fn=secret_input_fn)

    print_fn("\nBrain (OpenAI):")
    _manage_secret(vault, "openai_api_key", "OpenAI API key", **common)

    print_fn("\nWeb search (optional) — Tavily gives agents better research (free 1k/mo).")
    print_fn("  Get a key at tavily.com. Without it, free DuckDuckGo is used.")
    _manage_secret(vault, "tavily_api_key", "Tavily API key", **common)

    print_fn("\nTelegram (optional) — phone notifications when you're away:")
    print_fn("  Get a token from @BotFather; get your chat id from @userinfobot.")
    _manage_secret(vault, "telegram_bot_token", "Telegram bot token", **common)
    # Chat id isn't sensitive → visible input.
    _manage_secret(vault, "telegram_chat_id", "Telegram chat id", secret=False, **common)

    # 3. Kill switch explainer
    print_fn("\n  IMPORTANT — your emergency stop:")
    print_fn(f'    Say or type "{KILL_PHRASE.title()}" any time to shut everything down instantly.')
    print_fn("    This cannot be disabled by Jarvis.\n")

    # 4. Save config + audit
    cfg.sandbox_path = sandbox_path
    cfg.onboarded = True
    cfg.save(cfg_dir)
    AuditLog(cfg_dir / "logs" / "audit.jsonl").record(
        "onboarding", "Completed setup", risk="reversible", reason="User ran the setup wizard.")

    print_fn("=== Setup complete. ===\n")
    return cfg
