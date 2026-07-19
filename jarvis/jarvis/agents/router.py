"""Mode router (§2A.1) — choose M1 / M2 / M3 for a request.

Cheap heuristics first (most turns are M1 chat, which keeps voice instant); escalate to a
single agent (M2) for a clear tool-shaped task, and to the multi-agent supervisor (M3) only
for genuinely decomposable, multi-step goals — because M3 costs latency and tokens.
"""
from __future__ import annotations

import re

from .state import Mode

# Verbs / shapes that imply an actionable task (→ at least M2).
_ACTION_CUES = re.compile(
    r"\b(remind|schedule|book|email|send|draft|find|search|look up|research|"
    r"summari[sz]e|plan|organi[sz]e|create|make|write|build|check|update|delete|"
    r"add|set up|calculate|compute|"
    r"open|launch|start|run|close|play|show|go to|navigate|browse to)\b",
    re.IGNORECASE,
)

# Cues that a goal is multi-part / decomposable (→ M3).
_MULTI_CUES = re.compile(
    r"\band then\b|\bafter that\b|,\s*then\b|\bboth\b|\bmultiple\b|\beach of\b|\bcompare\b|"
    # "research/find/gather ... and (summarise|write|analyse|list|...)"  → a research+produce goal
    r"\b(research|find|gather|look up|analy[sz]e|investigate|explore)\b.+\band\b.+"
    r"\b(summari[sz]e|write|build|create|plan|analy[sz]e|list|recommend|report|compare|draft)\b",
    re.IGNORECASE,
)


def route_mode(request: str) -> Mode:
    text = (request or "").strip()
    if not text:
        return Mode.M1_DIRECT
    if _MULTI_CUES.search(text):
        return Mode.M3_MULTI
    if _ACTION_CUES.search(text):
        return Mode.M2_AGENT
    # Long, complex asks lean toward an agent even without explicit verbs.
    if len(text.split()) > 40:
        return Mode.M2_AGENT
    return Mode.M1_DIRECT
