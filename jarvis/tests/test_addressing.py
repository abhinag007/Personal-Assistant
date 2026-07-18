"""Addressing classifier tests (§3) — reply only when spoken to."""
from jarvis.llm.adapter import ChatResponse, Message, ModelAdapter
from jarvis.voice.addressing import is_addressed


class YesNoAdapter(ModelAdapter):
    name = "yesno"

    def __init__(self, answer: str):
        self._answer = answer

    def chat(self, messages, tools=None):
        return ChatResponse(text=self._answer, model=self.name)

    def stream(self, messages):
        yield self._answer

    def embed(self, texts):
        return [[0.0] for _ in texts]


def test_explicit_name_is_always_addressed():
    # Even a "NO" model is overridden by the explicit name cue.
    assert is_addressed(YesNoAdapter("NO"), "Jarvis what's the time") is True


def test_model_yes():
    assert is_addressed(YesNoAdapter("YES"), "what's the weather") is True


def test_model_no_means_not_addressed():
    assert is_addressed(YesNoAdapter("NO"), "yeah I'll call you back in five") is False


def test_empty_is_not_addressed():
    assert is_addressed(YesNoAdapter("YES"), "   ") is False


def test_ambiguous_defaults_to_addressed():
    assert is_addressed(YesNoAdapter("maybe?"), "hmm okay") is True


def test_use_model_false_defaults_addressed():
    assert is_addressed(YesNoAdapter("NO"), "some text", use_model=False) is True


def test_classifier_failure_defaults_addressed():
    class Boom(ModelAdapter):
        name = "boom"
        def chat(self, messages, tools=None):
            raise RuntimeError("model down")
        def stream(self, messages):
            yield ""
        def embed(self, texts):
            return [[0.0] for _ in texts]

    assert is_addressed(Boom(), "do something") is True
