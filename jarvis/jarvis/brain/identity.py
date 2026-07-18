"""Identity extraction (§8) — learn facts about the user from what they say.

Phase 1 focuses on the user's NAME, learned from natural statements like "my name is X"
or "call me X". This is the seed of the profile: Jarvis knows your name because you told
it, not because it was hardcoded. Phase 2 generalizes this into full fact extraction.

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

_PATTERNS = [
    re.compile(r"\bmy name is\s+([A-Za-z][A-Za-z'-]{1,30})", re.IGNORECASE),
    re.compile(r"\bcall me\s+([A-Za-z][A-Za-z'-]{1,30})", re.IGNORECASE),
    re.compile(r"\byou can call me\s+([A-Za-z][A-Za-z'-]{1,30})", re.IGNORECASE),
    re.compile(r"\bi am\s+([A-Za-z][A-Za-z'-]{1,30})\b", re.IGNORECASE),
    re.compile(r"\bi'?m\s+([A-Za-z][A-Za-z'-]{1,30})\b", re.IGNORECASE),
    re.compile(r"\bthis is\s+([A-Za-z][A-Za-z'-]{1,30})\b", re.IGNORECASE),
]

# The strong patterns (explicit) accept any name; the weak ones (I'm/I am/this is)
# must clear the stoplist to avoid false positives.
_STRONG = 3  # first 3 patterns are explicit "name is / call me"


def extract_name(text: str) -> Optional[str]:
    """Return a learned name from an explicit self-identification, else None."""
    if not text:
        return None
    for i, pat in enumerate(_PATTERNS):
        m = pat.search(text)
        if not m:
            continue
        candidate = m.group(1).strip(" '-")
        if not candidate:
            continue
        if i >= _STRONG and candidate.lower() in _NOT_NAMES:
            continue  # weak pattern + common word → not a name
        return candidate[:1].upper() + candidate[1:]
    return None
