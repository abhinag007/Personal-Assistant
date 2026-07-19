"""macOS control tool tests (§28) — command construction, safety gating (no real processes)."""
import os

from jarvis.connectors import desktop as d


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _spy():
    calls = []

    def runner(args, **kw):
        calls.append((args, kw))
        return _Result(0, "ok")
    return runner, calls


def test_open_app_builds_open_a():
    runner, calls = _spy()
    res = d.open_app("Google Chrome", runner=runner)
    assert res.ok
    assert calls[0][0] == ["open", "-a", "Google Chrome"]


def test_open_url_requires_http():
    assert d.open_url("chrome.com").ok is False
    runner, calls = _spy()
    assert d.open_url("https://x.com", runner=runner).ok is True


def test_browser_search_builds_google_url():
    runner, calls = _spy()
    d.browser_search("best laptops 2026", browser="Google Chrome", runner=runner)
    args = calls[0][0]
    assert args[:3] == ["open", "-a", "Google Chrome"]
    assert "google.com/search?q=best%20laptops%202026" in args[3]


def test_open_path_missing_file():
    assert d.open_path("~/definitely/not/here_12345.txt").ok is False


def test_run_command_disabled_by_default(monkeypatch):
    monkeypatch.delenv("JARVIS_ALLOW_SHELL", raising=False)
    res = d.run_command("ls")
    assert res.ok is False and "disabled" in res.error


def test_run_command_enabled_and_gated(monkeypatch):
    monkeypatch.setenv("JARVIS_ALLOW_SHELL", "1")
    runner, calls = _spy()
    # patch the runner to return output
    def runner2(cmd, **kw):
        return _Result(0, "file1\nfile2", "")
    res = d.run_command("ls", runner=runner2)
    assert res.ok and "file1" in res.output


def test_run_command_via_registry_is_approval_gated():
    # Through the registry, run_command is irreversible → requires approval (§11).
    from jarvis.core.approval import ApprovalEngine
    from jarvis.core.policy import ActionType
    from jarvis.tools import Tool, ToolRegistry

    os.environ["JARVIS_ALLOW_SHELL"] = "1"
    reg = ToolRegistry(approval=ApprovalEngine(approver=lambda r, k: False))  # deny
    reg.register(Tool("run_command", "shell", lambda command="": d.run_command(command),
                      ActionType.RUN_COMMAND))
    res = reg.execute("run_command", command="echo hi")
    assert res.ok is False and "not approved" in res.error
