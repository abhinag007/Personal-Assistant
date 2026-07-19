"""Tools — Jarvis's safe hands (§11, §2A.6).

A Tool is a named callable with a typed ActionType. The ToolRegistry holds them and
executes them through the Phase 0 approval engine, so an irreversible tool (send, buy,
delete-outside-sandbox) is gated on human approval before it runs.
"""
from .base import Tool, ToolRegistry, ToolResult  # noqa: F401
from .web import WebSearch, web_fetch, html_to_text, make_tavily_backend  # noqa: F401
