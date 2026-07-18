"""Fact extraction (§8) — turn what the user says into clean, durable profile facts.

After a turn, this asks the model to pull any durable facts about the user out of their
message and return them as JSON. Those facts are filed into the memory profile so Jarvis
*knows* them (not just fuzzily recalls a sentence), and so curiosity stops asking about
things it has learned.

Graceful by design: if the model returns non-JSON (e.g. the offline MockAdapter) or errors,
extraction simply yields no facts. The regex name-extractor (identity.py) remains the
reliable baseline regardless.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from ..llm.adapter import Message, ModelAdapter

# Fields fact-extraction may fill (name is handled separately by identity.py).
EXTRACTABLE = ["about", "interests", "help_style", "goals"]

_SYSTEM = (
    "You extract durable facts about the user from their message. "
    "Return ONLY a compact JSON object (no prose) mapping any of these keys to a short value, "
    "and OMIT keys the message doesn't clearly state:\n"
    '  "about"       -> their job / what they are working on\n'
    '  "interests"   -> hobbies or things they care about\n'
    '  "help_style"  -> how they want to be helped (tone, detail, proactivity)\n'
    '  "goals"       -> a bigger goal they mention\n'
    "If the message states no durable facts, return {}. Keep values under 12 words."
)


def _parse(text: str) -> dict:
    """Extract the first JSON object from `text` and keep only known, non-empty string fields."""
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k in EXTRACTABLE:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()[:120]
    return out


def extract_facts(adapter: ModelAdapter, text: str, *, min_words: int = 3) -> dict:
    """Ask the model for durable facts in the user's message. Returns {} on any failure."""
    if not text or len(text.split()) < min_words:
        return {}
    try:
        resp = adapter.chat([Message("system", _SYSTEM), Message("user", text)])
        return _parse(resp.text)
    except Exception:
        return {}
