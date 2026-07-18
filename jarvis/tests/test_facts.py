"""Fact-extraction tests (§8) — parse JSON facts; ignore junk; wire into a fake adapter."""
from jarvis.brain.facts import _parse, extract_facts
from jarvis.llm.adapter import ChatResponse, Message, ModelAdapter


class FakeJSONAdapter(ModelAdapter):
    """Returns a canned JSON blob, to test extraction without a real model."""
    name = "fake"

    def __init__(self, payload: str):
        self._payload = payload

    def chat(self, messages, tools=None):
        return ChatResponse(text=self._payload, model=self.name)

    def stream(self, messages):
        yield self._payload

    def embed(self, texts):
        return [[0.0] for _ in texts]


def test_parse_extracts_known_fields():
    out = _parse('{"about": "backend developer", "interests": "chess"}')
    assert out == {"about": "backend developer", "interests": "chess"}


def test_parse_ignores_unknown_and_empty():
    out = _parse('{"about": "dev", "random": "x", "goals": ""}')
    assert out == {"about": "dev"}


def test_parse_handles_non_json():
    assert _parse("[mock reply] I heard: hello") == {}
    assert _parse("") == {}


def test_parse_extracts_json_embedded_in_prose():
    out = _parse('Sure! Here you go: {"goals": "ship Jarvis"} hope that helps')
    assert out == {"goals": "ship Jarvis"}


def test_extract_facts_end_to_end():
    adapter = FakeJSONAdapter('{"about": "backend dev building Jarvis"}')
    facts = extract_facts(adapter, "I am a backend dev building Jarvis right now")
    assert facts["about"] == "backend dev building Jarvis"


def test_extract_skips_tiny_messages():
    adapter = FakeJSONAdapter('{"about": "x"}')
    assert extract_facts(adapter, "hi") == {}  # too short to bother
