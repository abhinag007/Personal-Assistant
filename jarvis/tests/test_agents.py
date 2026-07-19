"""Agent framework tests (§2A, §7): ReAct loop, router, orchestrator."""
from jarvis.agents import Agent, Orchestrator, route_mode
from jarvis.agents.state import AgentState, Mode
from jarvis.core.policy import ActionType
from jarvis.llm.adapter import ChatResponse, Message, ModelAdapter
from jarvis.tools import Tool, ToolRegistry, ToolResult


class ScriptedAdapter(ModelAdapter):
    """Returns a queued list of responses, one per chat() call."""
    name = "scripted"

    def __init__(self, script):
        self._script = list(script)

    def chat(self, messages, tools=None):
        text = self._script.pop(0) if self._script else '{"final": "done"}'
        return ChatResponse(text=text, model=self.name)

    def stream(self, messages):
        yield self.chat(messages).text

    def embed(self, texts):
        return [[0.0] for _ in texts]


# ---- router --------------------------------------------------------------

def test_router_direct_for_chat():
    assert route_mode("hello how are you") is Mode.M1_DIRECT


def test_router_agent_for_action():
    assert route_mode("remind me to call mom at 5") is Mode.M2_AGENT


def test_router_multi_for_compound():
    assert route_mode("research the top 3 laptops and then write me a summary") is Mode.M3_MULTI


def test_router_multi_for_research_and_summarise():
    # "research ... and summarise" is a compound research+produce goal → M3.
    assert route_mode("research the 3 newest AI coding tools in 2026 and summarise them") is Mode.M3_MULTI
    assert route_mode("find the best budget phones and compare them") is Mode.M3_MULTI


def test_router_single_for_plain_search():
    # A bare search/lookup is still a single agent (M2), not M3.
    assert route_mode("search the web for the weather") is Mode.M2_AGENT


def test_router_gmail_inbox_uses_agent():
    assert route_mode("read my latest Gmail inbox items") is Mode.M2_AGENT
    assert route_mode("check my inbox") is Mode.M2_AGENT


# ---- agent (ReAct) -------------------------------------------------------

def test_agent_uses_tool_then_finishes():
    reg = ToolRegistry()
    reg.register(Tool("add", "adds a and b", lambda a=0, b=0: ToolResult.success(a + b),
                      ActionType.NETWORK_FETCH))
    adapter = ScriptedAdapter([
        '{"tool": "add", "args": {"a": 2, "b": 3}}',
        '{"final": "The answer is 5."}',
    ])
    agent = Agent(adapter, reg, ["add"])
    res = agent.run("add 2 and 3")
    assert res.ok
    assert "5" in res.output
    assert res.steps == 2
    assert any("add" in t for t in res.trace)


def test_agent_budget_exhaustion_is_clean_exit():
    reg = ToolRegistry()
    reg.register(Tool("noop", "does nothing", lambda **k: ToolResult.success("ok"),
                      ActionType.NETWORK_FETCH))
    # Always calls the tool, never finishes → must hit the budget and stop.
    adapter = ScriptedAdapter(['{"tool": "noop", "args": {}}'] * 20)
    agent = Agent(adapter, reg, ["noop"], max_steps=3)
    res = agent.run("loop forever")
    assert res.ok is False
    assert "budget" in res.error
    assert res.steps == 3


def test_agent_treats_nonjson_as_final():
    reg = ToolRegistry()
    adapter = ScriptedAdapter(["Just a plain answer."])
    res = Agent(adapter, reg, []).run("say something")
    assert res.ok and res.output == "Just a plain answer."


def test_parse_action_tolerates_model_formats():
    from jarvis.agents.agent import _parse_action
    tools = ["browser_search", "open_app"]
    # our protocol
    assert _parse_action('{"tool": "open_app", "args": {"name": "Chrome"}}', tools)[:2] == ("tool", "open_app")
    # OpenAI function style
    assert _parse_action('{"name": "open_app", "arguments": {"name": "Chrome"}}', tools)[:2] == ("tool", "open_app")
    # tool name AS the key (what gpt-4o emitted)
    kind, name, args = _parse_action('{"browser_search": {"query": "keyboards"}}', tools)
    assert kind == "tool" and name == "browser_search" and args == {"query": "keyboards"}
    # unknown single-key dict is NOT a tool → treated as final
    assert _parse_action('{"something": 1}', tools)[0] == "final"


def test_router_open_commands_are_actions():
    assert route_mode("open Google Chrome") is Mode.M2_AGENT
    assert route_mode("open my notes.txt on the Desktop") is Mode.M2_AGENT
    assert route_mode("launch VS Code") is Mode.M2_AGENT


# ---- orchestrator (M3) ---------------------------------------------------

def test_orchestrator_decomposes_and_merges(tmp_path):
    reg = ToolRegistry()
    script = [
        '["research options", "write summary"]',  # decompose
        '{"final": "researched"}',                 # sub-agent 1
        "YES good",                                 # critic 1
        '{"final": "summary written"}',            # sub-agent 2
        "YES good",                                 # critic 2
        "Final merged answer.",                     # merge
    ]
    orch = Orchestrator(ScriptedAdapter(script), reg, checkpoint_dir=tmp_path)
    state = orch.run("research laptops and write a summary")
    assert state.status == "done"
    assert len(state.plan) == 2
    assert len(state.sub_results) == 2
    assert all(r["accepted"] for r in state.sub_results)
    assert state.result


def test_orchestrator_checkpoints_state(tmp_path):
    orch = Orchestrator(ScriptedAdapter([]), ToolRegistry(), checkpoint_dir=tmp_path)
    state = orch.run("do a thing")
    # A checkpoint file must exist and reload cleanly.
    files = list(tmp_path.glob("*.json"))
    assert files
    reloaded = AgentState.load(files[0])
    assert reloaded.goal == "do a thing"
