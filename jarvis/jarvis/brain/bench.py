"""TTFW benchmark (§18) — measure time-to-first-word as a first-class metric.

Runs a set of prompts through the brain and reports the latency distribution of the first
streamed token. This is the number the latency-optimization pass targets (< 1.5 s).
"""
from __future__ import annotations

import statistics
from typing import Optional

from .loop import BrainLoop

_PROMPTS = [
    "hello",
    "what's the time",
    "tell me something interesting",
    "how are you today",
    "what did I tell you about myself",
    "remind me to call mom",
    "what's the weather like",
    "give me a quick idea",
]


def run_benchmark(brain: BrainLoop, n: int = 8, prompts: Optional[list[str]] = None) -> dict:
    """Run n turns, return TTFW stats (seconds). Does not speak; discards output."""
    prompts = (prompts or _PROMPTS)[:n]
    ttfws: list[float] = []
    for p in prompts:
        brain.handle_turn(p, speak=lambda _c: None)
        if brain.last_ttfw is not None:
            ttfws.append(brain.last_ttfw)
    if not ttfws:
        return {"n": 0}
    ttfws.sort()
    return {
        "n": len(ttfws),
        "median_s": round(statistics.median(ttfws), 3),
        "p95_s": round(ttfws[min(len(ttfws) - 1, int(0.95 * len(ttfws)))], 3),
        "min_s": round(ttfws[0], 3),
        "max_s": round(ttfws[-1], 3),
        "target_s": 1.5,
        "meets_target": statistics.median(ttfws) < 1.5,
    }
