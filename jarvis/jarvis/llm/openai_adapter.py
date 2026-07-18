"""OpenAIAdapter — the development-phase brain (§1).

The `openai` package is imported lazily inside methods so that merely importing this
module (e.g. during tests, or on a machine without the key) does not require the
dependency or a network connection.
"""
from __future__ import annotations

from typing import Iterator, Optional

from .adapter import ChatResponse, Message, ModelAdapter, ToolCall


class OpenAIAdapter(ModelAdapter):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        embed_model: str = "text-embedding-3-small",
    ):
        self._api_key = api_key
        self._model = model
        self._embed_model = embed_model
        self.name = f"openai:{model}"
        self.__client = None

    def _client(self):
        if self.__client is None:
            from openai import OpenAI  # lazy import

            self.__client = OpenAI(api_key=self._api_key)
        return self.__client

    @staticmethod
    def _to_openai(messages: list[Message]) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in messages]

    def chat(self, messages: list[Message], tools: Optional[list[dict]] = None) -> ChatResponse:
        kwargs = {"model": self._model, "messages": self._to_openai(messages)}
        if tools:
            kwargs["tools"] = tools
        resp = self._client().chat.completions.create(**kwargs)
        choice = resp.choices[0]
        tool_calls = []
        if getattr(choice.message, "tool_calls", None):
            import json

            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except (ValueError, TypeError):
                    args = {}
                tool_calls.append(ToolCall(name=tc.function.name, arguments=args, call_id=tc.id))
        usage = getattr(resp, "usage", None)
        return ChatResponse(
            text=choice.message.content or "",
            tool_calls=tool_calls,
            model=self._model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    def stream(self, messages: list[Message]) -> Iterator[str]:
        stream = self._client().chat.completions.create(
            model=self._model,
            messages=self._to_openai(messages),
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._client().embeddings.create(model=self._embed_model, input=texts)
        return [d.embedding for d in resp.data]
