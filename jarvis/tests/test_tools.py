"""Tool registry + approval-gated execution tests (§11, §2A.6)."""
from jarvis.core.approval import ApprovalEngine
from jarvis.core.policy import ActionType
from jarvis.journal import DecisionJournal
from jarvis.tools import Tool, ToolRegistry, ToolResult


def _echo(**kw):
    return ToolResult.success(kw.get("text", ""))


def test_register_and_execute_reversible():
    reg = ToolRegistry(approval=ApprovalEngine(approver=lambda r, k: False))
    reg.register(Tool("echo", "echoes", _echo, ActionType.NETWORK_FETCH))
    res = reg.execute("echo", text="hi")
    assert res.ok and res.output == "hi"  # reversible → runs without asking


def test_irreversible_tool_blocked_without_approval():
    reg = ToolRegistry(approval=ApprovalEngine(approver=lambda r, k: False))
    reg.register(Tool("send", "sends", _echo, ActionType.SEND_MESSAGE))
    res = reg.execute("send", text="hello")
    assert res.ok is False
    assert "not approved" in res.error


def test_irreversible_tool_runs_when_approved():
    reg = ToolRegistry(approval=ApprovalEngine(approver=lambda r, k: True))
    reg.register(Tool("send", "sends", _echo, ActionType.SEND_MESSAGE))
    res = reg.execute("send", text="hello")
    assert res.ok and res.output == "hello"


def test_unknown_tool():
    reg = ToolRegistry()
    assert reg.execute("nope").ok is False


def test_exception_is_graceful():
    reg = ToolRegistry()

    def boom(**kw):
        raise ValueError("kaboom")

    reg.register(Tool("boom", "explodes", boom, ActionType.NETWORK_FETCH))
    res = reg.execute("boom")
    assert res.ok is False and "kaboom" in res.error


def test_execution_is_journaled(tmp_path):
    j = DecisionJournal(tmp_path / "journal.jsonl")
    reg = ToolRegistry(approval=ApprovalEngine(approver=lambda r, k: True), journal=j)
    reg.register(Tool("send", "sends", _echo, ActionType.SEND_MESSAGE))
    reg.execute("send", text="x")
    entries = j.read_all()
    assert any(e["action"] == "send" for e in entries)


def test_catalog_and_decorator():
    reg = ToolRegistry()

    @reg.tool("adder", "adds", ActionType.NETWORK_FETCH)
    def _add(a=0, b=0):
        return ToolResult.success(a + b)

    assert "adder" in reg.names()
    assert reg.execute("adder", a=2, b=3).output == 5
    assert reg.catalog()[0]["name"] == "adder"
