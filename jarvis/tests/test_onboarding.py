"""Onboarding tests (§41) — keep-or-change secrets on re-run; Telegram fields."""
from jarvis.onboarding.wizard import _manage_secret
from jarvis.vault import Vault, FileKeyProvider


def _vault(tmp_path):
    return Vault(tmp_path / "vault.enc", key_provider=FileKeyProvider(tmp_path / "k"))


def test_new_secret_is_stored(tmp_path):
    v = _vault(tmp_path)
    prints = []
    _manage_secret(v, "openai_api_key", "OpenAI API key",
                   input_fn=lambda p: "", print_fn=prints.append,
                   secret_input_fn=lambda p: "sk-123")
    assert v.get_secret("openai_api_key") == "sk-123"


def test_existing_secret_kept_by_default(tmp_path):
    v = _vault(tmp_path)
    v.set_secret("openai_api_key", "old-key")
    # User presses Enter → keep.
    _manage_secret(v, "openai_api_key", "OpenAI API key",
                   input_fn=lambda p: "", print_fn=lambda *_: None,
                   secret_input_fn=lambda p: "SHOULD-NOT-BE-USED")
    assert v.get_secret("openai_api_key") == "old-key"


def test_existing_secret_changed_when_declined(tmp_path):
    v = _vault(tmp_path)
    v.set_secret("telegram_bot_token", "old-token")
    # User says 'n' to keep, then enters a new value.
    answers = iter(["n"])
    _manage_secret(v, "telegram_bot_token", "Telegram bot token",
                   input_fn=lambda p: next(answers, ""), print_fn=lambda *_: None,
                   secret_input_fn=lambda p: "new-token")
    assert v.get_secret("telegram_bot_token") == "new-token"


def test_blank_new_secret_is_skipped(tmp_path):
    v = _vault(tmp_path)
    _manage_secret(v, "telegram_chat_id", "Telegram chat id", secret=False,
                   input_fn=lambda p: "", print_fn=lambda *_: None,
                   secret_input_fn=lambda p: "")
    assert v.get_secret("telegram_chat_id") is None
