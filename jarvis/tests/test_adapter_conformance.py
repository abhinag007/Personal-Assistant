"""Adapter conformance suite (§1).

The contract EVERY ModelAdapter must satisfy, so the brain can be swapped (OpenAI ↔ local
↔ Claude ↔ mock) without changing anything downstream. Run against MockAdapter here; the
same suite can be pointed at a live adapter when a key is available.
"""
import math

import pytest

from jarvis.llm import MockAdapter
from jarvis.llm.adapter import ChatResponse, Message, ModelAdapter


# Adapters to run the contract against. (Live OpenAI/Claude added when keys are present.)
ADAPTERS = [MockAdapter()]


@pytest.fixture(params=ADAPTERS, ids=lambda a: a.name)
def adapter(request):
    return request.param


def test_is_model_adapter(adapter):
    assert isinstance(adapter, ModelAdapter)
    assert isinstance(adapter.name, str) and adapter.name


def test_chat_contract(adapter):
    resp = adapter.chat([Message("system", "be brief"), Message("user", "hello world")])
    assert isinstance(resp, ChatResponse)
    assert isinstance(resp.text, str)
    assert isinstance(resp.tool_calls, list)
    assert resp.completion_tokens >= 0 and resp.prompt_tokens >= 0


def test_stream_contract(adapter):
    chunks = list(adapter.stream([Message("user", "count to three")]))
    assert chunks, "stream must yield at least one chunk"
    assert all(isinstance(c, str) for c in chunks)
    assert "".join(chunks).strip()


def test_embed_contract(adapter):
    vecs = adapter.embed(["alpha", "beta"])
    assert len(vecs) == 2
    assert all(isinstance(v, list) and v for v in vecs)
    # equal dimensionality
    assert len(vecs[0]) == len(vecs[1])
    assert all(isinstance(x, float) for x in vecs[0])


def test_embed_deterministic_for_same_text(adapter):
    a = adapter.embed(["same text"])[0]
    b = adapter.embed(["same text"])[0]
    assert a == b


def test_system_user_helper(adapter):
    msgs = ModelAdapter.system_user("sys", "usr")
    assert [m.role for m in msgs] == ["system", "user"]
