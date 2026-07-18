"""Daily briefing (§40) — "here's where things stand".

Assembles today's reminders (§38), tasks waiting on you (§30), and anything the background
brain prepared, into a short brief delivered by voice or phone.
"""
from __future__ import annotations

import time
from typing import Optional


def _fmt_time(epoch: float) -> str:
    return time.strftime("%a %H:%M", time.localtime(epoch))


def build_briefing(
    *,
    calendar=None,        # CalendarStore
    handoff=None,         # HandoffManager
    staging=None,         # StagingStore
    now: Optional[float] = None,
    horizon_hours: float = 24.0,
) -> str:
    now = now if now is not None else time.time()
    lines: list[str] = ["Here's your brief:"]

    # Upcoming reminders / calendar
    if calendar is not None:
        upcoming = calendar.upcoming(within_seconds=horizon_hours * 3600, now=now)
        if upcoming:
            lines.append(f"\nNext {len(upcoming)} on your calendar:")
            lines += [f"  • {_fmt_time(r.due)} — {r.text}" for r in upcoming]
        else:
            lines.append("\nNothing on your calendar in the next day.")

    # Waiting on you
    if handoff is not None:
        waiting = handoff.waiting()
        if waiting:
            lines.append(f"\nWaiting on you ({len(waiting)}):")
            lines += [f"  • {t.reason}" for t in waiting]

    # Speculative work prepared for you
    if staging is not None:
        staged = staging.list()
        if staged:
            lines.append(f"\nI prepared {len(staged)} thing(s) for you to review:")
            lines += [f"  • {s.kind}: {s.title}" for s in staged]

    if len(lines) == 1:
        return "You're all clear — nothing on the calendar, nothing waiting."
    return "\n".join(lines)
