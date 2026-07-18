"""Addressing classifier (§3, §19) — "is the user talking TO Jarvis, or to someone else?"

Once the wake word arms a session, Jarvis keeps listening without needing "Hey Jarvis"
again. But not everything it hears is meant for it — you might turn and talk to a person,
answer your phone, or think out loud. This decides whether a transcribed utterance is
addressed to Jarvis, so it replies only when spoken to and otherwise just listens.

It uses the model for a fast yes/no judgment (with recent context). Graceful: on any
failure it defaults to "yes" (respond) within an active session, since the user just
recently woke it and is likely still talking to it.
"""
from __future__ import annotations

from typing import Optional

from ..llm.adapter import Message, ModelAdapter

_SYSTEM = (
    "You decide whether the user is speaking TO a voice assistant named Jarvis, or to "
    "someone else. The user already said the wake word and is in an active session, so "
    "DEFAULT strongly to YES.\n\n"
    "Answer NO only if the utterance is CLEARLY directed at another person or a phone call "
    "(e.g. addresses someone by name, obvious side-conversation, 'I'll call you back'), or is "
    "meaningless filler/muttering. If it is a question, request, command, or a statement an "
    "assistant could respond to, answer YES.\n\n"
    "Examples:\n"
    "\"what's the weather\" -> YES\n"
    "\"do you know what I like to drink\" -> YES\n"
    "\"remind me at 5\" -> YES\n"
    "\"tell me a joke\" -> YES\n"
    "\"hold on, I'll call you back\" -> NO\n"
    "\"yeah mom, I'm coming\" -> NO\n"
    "\"uh, um, hmm\" -> NO\n\n"
    "Answer with exactly one word: YES or NO."
)

# Quick heuristics that don't need the model.
_DIRECT_CUES = ("jarvis", "hey jarvis")


def is_addressed(
    adapter: ModelAdapter,
    utterance: str,
    *,
    recent_context: str = "",
    use_model: bool = True,
) -> bool:
    """Return True if the utterance is meant for Jarvis."""
    text = (utterance or "").strip()
    if not text:
        return False

    # Fast path: explicit name is a strong "yes".
    low = text.lower()
    if any(cue in low for cue in _DIRECT_CUES):
        return True

    if not use_model:
        return True  # in-session default without a model: respond

    try:
        prompt = text if not recent_context else f"Recent:\n{recent_context}\n\nLatest: {text}"
        resp = adapter.chat([Message("system", _SYSTEM), Message("user", prompt)])
        answer = (resp.text or "").strip().lower()
        if answer.startswith("no"):
            return False
        if answer.startswith("yes"):
            return True
        # Ambiguous model output → default to responding within an active session.
        return True
    except Exception:
        return True  # never drop a real command because the classifier hiccuped
