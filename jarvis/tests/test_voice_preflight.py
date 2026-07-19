from jarvis.config import Config
from jarvis.main import (
    _apply_voice_options,
    _save_voice_options,
    _saved_voice_options,
    _voice_preflight,
)


def test_voice_preflight_accepts_defaults():
    env = {
        "JARVIS_BRAIN_PROVIDER": "glm",
        "JARVIS_MODEL": "glm-5.2",
        "JARVIS_STT_MODEL": "small.en",
        "JARVIS_WAKE_MODE": "model",
        "JARVIS_ADDRESSING": "0",
        "JARVIS_ADDRESSING_MODEL": "gpt-4o-mini",
        "JARVIS_REQUIRE_OWNER": "0",
        "JARVIS_SPEAKER_THRESHOLD": "0.15",
        "JARVIS_VOICE_DEBUG": "0",
        "JARVIS_CONSOLIDATION_HOUR": "3",
        "JARVIS_BRIEF_HOUR": "8",
        "JARVIS_ALLOW_SHELL": "1",
    }
    opts = _voice_preflight(
        input_fn=lambda prompt: "",
        print_fn=lambda *_: None,
        environ=env,
    )
    assert opts["brain_provider"] == "glm"
    assert opts["brain_model"] == "glm-5.2"
    assert opts["stt_model"] == "small.en"
    assert opts["wake_mode"] == "model"
    assert opts["addressing"] is False
    assert opts["require_owner"] is False
    assert opts["voice_debug"] is False
    assert opts["allow_shell"] is True
    assert opts["briefing_hour"] == "8"


def test_voice_preflight_parses_user_answers():
    answers = iter([
        "gml", "glm-5.2",
        "large-v3", "stt", "t", "gpt-4o", "no", "0.2", "no", "4", "", "yes", "5",
    ])
    opts = _voice_preflight(
        input_fn=lambda prompt: next(answers),
        print_fn=lambda *_: None,
        environ={},
    )
    assert opts["brain_provider"] == "glm"
    assert opts["brain_model"] == "glm-5.2"
    assert opts["stt_model"] == "large-v3"
    assert opts["addressing"] is True
    assert opts["require_owner"] is False
    assert opts["voice_debug"] is False
    assert opts["consolidation_hour"] == "4"
    assert opts["briefing_hour"] == ""
    assert opts["allow_shell"] is True
    assert opts["telegram_poll_seconds"] == "5"


def test_voice_preflight_reprompts_invalid_boolean_answer():
    answers = iter([
        "openai", "gpt-4o-mini",
        "small.en", "stt",
        "maybe", "yes",
        "gpt-4o",
        "n",
        "0.25",
        "bad", "false",
        "2", "", "no", "5",
    ])
    messages = []
    opts = _voice_preflight(
        input_fn=lambda prompt: next(answers),
        print_fn=messages.append,
        environ={},
    )
    assert opts["addressing"] is True
    assert opts["require_owner"] is False
    assert opts["voice_debug"] is False
    assert opts["allow_shell"] is False
    assert any("Please answer yes/no" in m for m in messages)


def test_apply_voice_options_sets_environment():
    env = {"JARVIS_BRIEF_HOUR": "8"}
    _apply_voice_options({
        "brain_provider": "glm",
        "brain_model": "glm-5.2",
        "stt_model": "medium.en",
        "wake_mode": "stt",
        "addressing": True,
        "addressing_model": "gpt-4o",
        "require_owner": True,
        "speaker_threshold": "0.25",
        "voice_debug": False,
        "consolidation_hour": "2",
        "briefing_hour": "",
        "allow_shell": False,
        "telegram_poll_seconds": "5",
    }, environ=env)
    assert env["JARVIS_BRAIN_PROVIDER"] == "glm"
    assert env["JARVIS_MODEL"] == "glm-5.2"
    assert env["JARVIS_BASE_URL"] == "https://api.z.ai/api/paas/v4"
    assert env["JARVIS_API_KEY_SECRET"] == "glm_api_key"
    assert env["JARVIS_STT_MODEL"] == "medium.en"
    assert env["JARVIS_ADDRESSING"] == "1"
    assert env["JARVIS_REQUIRE_OWNER"] == "1"
    assert env["JARVIS_VOICE_DEBUG"] == "0"
    assert env["JARVIS_CONSOLIDATION_HOUR"] == "2"
    assert env["JARVIS_ALLOW_SHELL"] == "0"
    assert env["JARVIS_TELEGRAM_POLL_SECONDS"] == "5"
    assert "JARVIS_BRIEF_HOUR" not in env


def test_voice_options_are_saved_in_config_and_used_as_preflight_defaults(tmp_path):
    cfg = Config(onboarded=True)
    saved = {
        "brain_provider": "openai",
        "brain_model": "gpt-4o-mini",
        "stt_model": "large-v3",
        "wake_mode": "model",
        "addressing": False,
        "addressing_model": "gpt-4o-mini",
        "require_owner": False,
        "speaker_threshold": "0.18",
        "voice_debug": False,
        "consolidation_hour": "4",
        "briefing_hour": "9",
        "allow_shell": True,
        "telegram_poll_seconds": "5",
    }
    _save_voice_options(cfg, tmp_path, saved)

    reloaded = Config.load(tmp_path)
    assert _saved_voice_options(reloaded) == saved
    options = _voice_preflight(
        input_fn=lambda _prompt: "",
        print_fn=lambda *_: None,
        environ={},
        saved_options=_saved_voice_options(reloaded),
    )
    assert options == saved
