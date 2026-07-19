"""Onboarding tests (§41) — keep-or-change secrets on re-run; Telegram fields."""
from jarvis.config import Config
from jarvis.onboarding.wizard import _configure_brain, _manage_secret, _print_setup_summary
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


def test_configure_brain_openai_stores_openai_key(tmp_path):
    v = _vault(tmp_path)
    cfg = Config()
    answers = iter(["1", "gpt-4o"])
    _configure_brain(cfg, v,
                     input_fn=lambda p: next(answers, ""),
                     print_fn=lambda *_: None,
                     secret_input_fn=lambda p: "sk-openai")
    assert cfg.base_url == ""
    assert cfg.model == "gpt-4o"
    assert cfg.api_key_secret == "openai_api_key"
    assert v.get_secret("openai_api_key") == "sk-openai"


def test_configure_brain_glm_stores_glm_key_and_endpoint(tmp_path):
    v = _vault(tmp_path)
    cfg = Config()
    answers = iter(["2", "", "glm-5.2"])
    _configure_brain(cfg, v,
                     input_fn=lambda p: next(answers, ""),
                     print_fn=lambda *_: None,
                     secret_input_fn=lambda p: "sk-glm")
    assert cfg.base_url == "https://api.z.ai/api/paas/v4"
    assert cfg.model == "glm-5.2"
    assert cfg.api_key_secret == "glm_api_key"
    assert v.get_secret("glm_api_key") == "sk-glm"


def test_setup_summary_reports_provider_without_secret_value(tmp_path):
    v = _vault(tmp_path)
    v.set_secret("glm_api_key", "sk-secret-value")
    v.set_secret("telegram_bot_token", "bot-token")
    v.set_secret("telegram_chat_id", "123")
    cfg = Config(base_url="https://api.z.ai/api/paas/v4", model="glm-5.2",
                 api_key_secret="glm_api_key")
    prints = []
    _print_setup_summary(cfg, v, print_fn=prints.append)
    text = "\n".join(prints)
    assert "GLM/Z.ai" in text
    assert "glm_api_key (set)" in text
    assert "ready for outbound + inbound" in text
    assert "sk-secret-value" not in text
