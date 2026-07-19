"""Identity extraction (§8) — learn facts about the user from what they say.

Phase 1 focuses on the user's NAME, learned from natural statements like "my name is X".
It also tracks a preferred address ("refer to me as sir") separately, so honorifics do not
overwrite the user's real name. This is the seed of the profile: Jarvis knows your identity
because you told it, not because it was hardcoded. Phase 2 generalizes this into full fact
extraction.

Conservative on purpose: it only captures a name from explicit self-identification
patterns, and rejects common words so "I'm tired" never becomes a name.
"""
from __future__ import annotations

import re
from typing import Optional

# Words that must never be mistaken for a name after "I'm / I am".
_NOT_NAMES = {
    "a", "an", "the", "not", "so", "very", "really", "just", "here", "back", "done",
    "tired", "happy", "sad", "good", "fine", "okay", "ok", "great", "busy", "sorry",
    "hungry", "sleepy", "sick", "bored", "ready", "sure", "curious", "confused",
    "working", "going", "trying", "thinking", "feeling", "looking", "learning",
}

_NAME_CHARS = r"[A-Za-z][A-Za-z' -]{1,60}"

_HONORIFICS = {"sir", "ma'am", "madam", "boss", "bro", "buddy", "friend"}

_PATTERNS = [
    re.compile(r"\bmy name is not\s+\w+[, ]+(?:it'?s|it is)\s+(" + _NAME_CHARS + r")", re.IGNORECASE),
    re.compile(r"\bmy name is\s+(" + _NAME_CHARS + r")", re.IGNORECASE),
    re.compile(r"\bcall me\s+(" + _NAME_CHARS + r")", re.IGNORECASE),
    re.compile(r"\byou can call me\s+(" + _NAME_CHARS + r")", re.IGNORECASE),
]

_ADDRESS_PATTERNS = [
    re.compile(r"\b(?:refer to|address)\s+me\s+as\s+(" + _NAME_CHARS + r")", re.IGNORECASE),
    re.compile(r"\b(?:call me|you can call me)\s+(" + _NAME_CHARS + r")", re.IGNORECASE),
]

_TRAILING = re.compile(
    r"\b(?:please|thanks|thank you|from now on|instead|and|but|because|when|if|so|as|not|it'?s|it is)\b.*$",
    re.IGNORECASE,
)


def _clean_candidate(candidate: str) -> str:
    candidate = _TRAILING.sub("", candidate).strip(" .,!?:;\"'`-")
    parts = [p for p in candidate.split() if p]
    return " ".join(p[:1].upper() + p[1:] for p in parts)


def extract_preferred_address(text: str) -> Optional[str]:
    """Return how the user wants to be addressed, without changing their real name."""
    if not text:
        return None
    for pat in _ADDRESS_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        candidate = _clean_candidate(m.group(1))
        if not candidate:
            continue
        if candidate.lower() in _HONORIFICS or pat.pattern.startswith("\\b(?:refer"):
            return candidate
    return None


_WEAK_PATTERNS = [
    re.compile(r"\bi am\s+([A-Za-z][A-Za-z'-]{1,30})\b", re.IGNORECASE),
    re.compile(r"\bi'?m\s+([A-Za-z][A-Za-z'-]{1,30})\b", re.IGNORECASE),
    re.compile(r"\bthis is\s+([A-Za-z][A-Za-z'-]{1,30})\b", re.IGNORECASE),
]


def extract_name(text: str) -> Optional[str]:
    """Return a learned name from an explicit self-identification, else None."""
    if not text:
        return None
    for pat in _PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        candidate = _clean_candidate(m.group(1))
        if not candidate:
            continue
        if candidate.lower() in _NOT_NAMES or candidate.lower() in _HONORIFICS:
            continue
        return candidate
    for pat in _WEAK_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        candidate = _clean_candidate(m.group(1))
        if candidate and candidate.lower() not in _NOT_NAMES:
            return candidate
    return None
