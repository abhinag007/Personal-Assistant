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


def _configure_brain(cfg, vault, *, input_fn, print_fn, secret_input_fn):
    """Choose the active OpenAI-compatible brain and store the matching provider token."""
    current = "GLM/Z.ai" if cfg.base_url else "OpenAI"
    print_fn("\nBrain:")
    print_fn(f"  Current: {current} | model: {cfg.model} | endpoint: {cfg.base_url or 'OpenAI default'}")
    print_fn("  1) OpenAI")
    print_fn("  2) GLM/Z.ai (OpenAI-compatible)")
    print_fn("  3) Custom OpenAI-compatible endpoint")
    choice = input_fn("  Brain provider [1]: ").strip().lower() or "1"

    common = dict(input_fn=input_fn, print_fn=print_fn, secret_input_fn=secret_input_fn)
    if choice in ("1", "openai", "o"):
        cfg.base_url = ""
        cfg.api_key_secret = "openai_api_key"
        model = input_fn(f"  OpenAI model [{cfg.model or 'gpt-4o-mini'}]: ").strip()
        cfg.model = model or cfg.model or "gpt-4o-mini"
        _manage_secret(vault, "openai_api_key", "OpenAI API key", **common)
        return

    if choice in ("2", "glm", "zai", "z.ai", "z"):
        was_compatible_endpoint = bool(cfg.base_url)
        default_endpoint = cfg.base_url or "https://api.z.ai/api/paas/v4"
        endpoint = input_fn(f"  GLM endpoint [{default_endpoint}]: ").strip()
        cfg.base_url = endpoint or default_endpoint
        default_model = cfg.model if was_compatible_endpoint else "glm-5.2"
        model = input_fn(f"  GLM model [{default_model}]: ").strip()
        cfg.model = model or default_model
        cfg.api_key_secret = "glm_api_key"
        _manage_secret(vault, "glm_api_key", "GLM/Z.ai API key", **common)
        return

    default_endpoint = cfg.base_url or "http://localhost:8000/v1"
    endpoint = input_fn(f"  Endpoint URL [{default_endpoint}]: ").strip()
    cfg.base_url = endpoint or default_endpoint
    model = input_fn(f"  Model [{cfg.model}]: ").strip()
    cfg.model = model or cfg.model
    secret_name = input_fn("  Vault secret name for this provider [custom_api_key]: ").strip()
    cfg.api_key_secret = secret_name or "custom_api_key"
    _manage_secret(vault, cfg.api_key_secret, "custom provider API key", **common)


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

    _configure_brain(cfg, vault, **common)

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
