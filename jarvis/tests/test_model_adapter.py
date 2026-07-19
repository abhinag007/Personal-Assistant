"""Model adapter tests (§1) — the conformance behaviors any adapter must satisfy."""
import pytest

from jarvis.llm import MockAdapter, build_adapter
from jarvis.llm.adapter import Message


@pytest.fixture
def adapter():
    return MockAdapter()


def test_chat_returns_response(adapter):
    resp = adapter.chat([Message("system", "be nice"), Message("user", "hello there")])
    assert "hello there" in resp.text
    assert resp.model == "mock"
    assert resp.completion_tokens > 0


def test_stream_yields_chunks(adapter):
    chunks = list(adapter.stream([Message("user", "one two three")]))
    assert len(chunks) > 1
    assert "one" in "".join(chunks)


def test_embed_is_deterministic_and_normalized(adapter):
    a1 = adapter.embed(["hello world"])[0]
    a2 = adapter.embed(["hello world"])[0]
    assert a1 == a2  # deterministic
    # roughly unit length
    import math
    assert abs(math.sqrt(sum(x * x for x in a1)) - 1.0) < 1e-6


def test_similar_text_more_similar_than_different(adapter):
    from jarvis.memory.embedder import cosine
    v_hello = adapter.embed(["the cat sat on the mat"])[0]
    v_hello2 = adapter.embed(["the cat sat on the mat today"])[0]
    v_other = adapter.embed(["quantum financial derivatives"])[0]
    assert cosine(v_hello, v_hello2) > cosine(v_hello, v_other)


def test_router_defaults_to_mock():
    a = build_adapter("mock")
    assert a.name == "mock"


def test_router_openai_requires_key():
    with pytest.raises(ValueError):
        build_adapter("openai", api_key=None)


def test_router_openai_accepts_compatible_base_url():
    a = build_adapter("openai", api_key="test", model="glm-4.6",
                      base_url="https://api.z.ai/api/paas/v4")
    assert "glm-4.6@api.z.ai" in a.name


def test_router_rejects_unknown_provider():
    with pytest.raises(ValueError):
        build_adapter("banana")
