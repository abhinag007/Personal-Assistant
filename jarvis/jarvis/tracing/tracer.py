"""Tracer (§2A.5) — one thin interface over the whole pipeline's spans.

Every AI-touching step opens a span (STT, memory recall, model call, TTS, tool calls).
Backends are swappable behind this interface so the dev-phase LangSmith → local-phase
Langfuse switch is a config change, not a rewrite:

  * NoOpTracer   — does nothing (default; zero overhead).
  * LocalTracer  — writes spans as JSONL to disk (offline, private; useful now and in
                   the local phase before wiring Langfuse).
  * LangSmith    — added when the LangSmith SDK is configured (dev phase).

Spans nest (a multi-agent run becomes one nested trace tree), and each carries a
correlation id that ties it to the audit log (§16) and decision journal (§26).
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


class Span:
    def __init__(self, name: str, tracer: "Tracer", parent_id: Optional[str], **fields):
        self.name = name
        self.id = uuid.uuid4().hex
        self.parent_id = parent_id
        self.fields = dict(fields)
        self.start = time.perf_counter()
        self._tracer = tracer

    def set(self, key: str, value) -> None:
        self.fields[key] = value

    def _finish(self, error: Optional[str] = None) -> None:
        self.fields["duration_s"] = round(time.perf_counter() - self.start, 4)
        if error:
            self.fields["error"] = error
        self._tracer._emit(self)


class Tracer:
    """Base tracer = no-op. Subclasses override `_write`."""

    def __init__(self):
        self._stack: list[str] = []

    @classmethod
    def noop(cls) -> "Tracer":
        return _NOOP

    @contextmanager
    def span(self, name: str, **fields) -> Iterator[Span]:
        parent = self._stack[-1] if self._stack else None
        s = Span(name, self, parent, **fields)
        self._stack.append(s.id)
        try:
            yield s
            s._finish()
        except Exception as exc:  # record the error on the span, then re-raise
            s._finish(error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            if self._stack and self._stack[-1] == s.id:
                self._stack.pop()

    def _emit(self, span: Span) -> None:
        self._write({
            "id": span.id,
            "parent_id": span.parent_id,
            "name": span.name,
            **span.fields,
        })

    def _write(self, record: dict) -> None:
        pass  # no-op base


class _NoOpTracer(Tracer):
    pass


_NOOP = _NoOpTracer()


class LocalTracer(Tracer):
    """Writes spans to a local JSONL file — private, offline, inspectable."""

    def __init__(self, path: str | Path):
        super().__init__()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, record: dict) -> None:
        record["ts"] = time.time()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(ln) for ln in self.path.read_text().splitlines() if ln.strip()]
