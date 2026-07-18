"""Kill switch tests (§23) — phrase detection is robust; trigger runs cleanup then exits."""
import pytest

from jarvis.core.kill_switch import KillSwitch, is_kill_phrase


@pytest.mark.parametrize("text", [
    "Jarvis end yourself",
    "jarvis end yourself",
    "JARVIS, END YOURSELF!",
    "  jarvis   end   yourself  ",
    "ok jarvis end yourself now please",
    "Jarvis and yourself",           # common STT mishearing of "end yourself"
    "jarvis and yourself, please stop",
    "jarvis kill yourself",
    "jarvis shut yourself down",
])
def test_kill_phrase_detected(text):
    assert is_kill_phrase(text) is True


@pytest.mark.parametrize("text", [
    "",
    "jarvis what's the weather",
    "end the meeting yourself",       # no 'jarvis'
    "jarvis end the call",            # 'jarvis' but no shutdown variant
    "what about you and yourself later",  # variant but no 'jarvis'
])
def test_non_kill_phrase_ignored(text):
    assert is_kill_phrase(text) is False


def test_check_runs_cleanup_and_exits():
    cleaned = {"done": False}

    def cleanup():
        cleaned["done"] = True

    # terminate_process_group=False so we don't SIGTERM the test runner's group.
    ks = KillSwitch(on_shutdown=cleanup, terminate_process_group=False)
    # trigger() calls sys.exit(); capture it.
    with pytest.raises(SystemExit):
        ks.check("Jarvis, end yourself")
    assert cleaned["done"] is True


def test_non_kill_text_does_not_exit():
    ks = KillSwitch(terminate_process_group=False)
    # Should simply return False, not raise SystemExit.
    assert ks.check("hello jarvis") is False
