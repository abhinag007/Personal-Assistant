"""Curiosity (§8) — Jarvis asks to learn what it doesn't know, reliably.

Small models won't obey a soft "be curious" instruction, so curiosity is owned by CODE,
not left to the model: after each reply the brain appends ONE question about the next thing
it doesn't know. Each topic is asked at most once (tracked with an `_asked:<field>` flag), so
it's curious, not naggy. When you answer, fact-extraction (facts.py) fills the field and it
moves on to the next unknown.
"""
from __future__ import annotations

from typing import Optional

# (profile_key, warm question) — ordered by priority. `name` is also learned via identity.py.
DESIRED_FIELDS: list[tuple[str, str]] = [
    ("name", "By the way — what should I call you?"),
    ("about", "What do you do, and what are you working on these days?"),
    ("interests", "What are you into outside of work?"),
    ("help_style", "How do you like me to help — quick and to the point, or more detail?"),
    ("goals", "What's a bigger goal you're working toward that I could help with?"),
]

_ASK_FLAG = "_asked:"


def missing_topics(profile: dict) -> list[str]:
    """Descriptions of fields Jarvis hasn't learned yet (value not set)."""
    return [q for key, q in DESIRED_FIELDS if not profile.get(key)]


def next_curiosity(profile: dict) -> Optional[tuple[str, str]]:
    """The next (field, question) Jarvis should ask: unknown AND not asked before."""
    for key, question in DESIRED_FIELDS:
        if profile.get(key):
            continue  # already known
        if profile.get(_ASK_FLAG + key):
            continue  # already asked once; respect that they didn't answer
        return key, question
    return None


def asked_flag(field: str) -> str:
    return _ASK_FLAG + field


def persona_curiosity_note(profile: dict) -> str:
    """A short tone note for the system prompt (the actual question is appended in code)."""
    if next_curiosity(profile) is None:
        return ""
    return (
        "\n\nYou are warm and genuinely curious about the user — you like getting to know them. "
        "Keep replies friendly and personal, not like a help desk."
    )
