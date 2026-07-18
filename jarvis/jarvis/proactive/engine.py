"""ProactiveEngine (§25, §30, §40).

`poll(now)` gathers any pending announcements and decides what to do with them:
  * present  → return the list so the voice loop can SPEAK them (and open a reply window);
  * away     → send them to your phone via the notifier, return nothing to speak;
  * quiet hours → stay silent (no speech, no push).

Events, all de-duplicated so nothing repeats:
  * reminders that just came due (§38) — marked done when announced;
  * blocked tasks waiting on you (§30) — announced once each;
  * background jobs that finished (§9);
  * an optional once-a-day briefing at a set hour (§40).
"""
from __future__ import annotations

import time
from typing import Optional


class ProactiveEngine:
    def __init__(
        self,
        *,
        calendar=None,
        handoff=None,
        queue=None,
        notifier=None,
        presence=None,
        quiet_hours: str = "",          # e.g. "22:00-07:00"
        briefing_hour: Optional[int] = None,
        adapter=None,                   # model → phrase updates conversationally (§34)
        user_name: Optional[str] = None,
        log=print,
    ):
        self.calendar = calendar
        self.handoff = handoff
        self.queue = queue
        self.notifier = notifier
        self.presence = presence
        self.quiet_hours = quiet_hours
        self.briefing_hour = briefing_hour
        self.adapter = adapter
        self.user_name = user_name
        self.log = log
        self._announced_handoffs: set = set()
        self._seen_jobs: set = set()
        self._last_briefing_day = None

    # ---- quiet hours -----------------------------------------------------

    def in_quiet_hours(self, now: float) -> bool:
        if not self.quiet_hours or "-" not in self.quiet_hours:
            return False
        try:
            start, end = self.quiet_hours.split("-")
            sh, sm = map(int, start.split(":"))
            eh, em = map(int, end.split(":"))
        except ValueError:
            return False
        lt = time.localtime(now)
        cur = lt.tm_hour * 60 + lt.tm_min
        s, e = sh * 60 + sm, eh * 60 + em
        if s <= e:
            return s <= cur < e
        return cur >= s or cur < e  # spans midnight

    # ---- event collection ------------------------------------------------

    def _collect(self, now: float) -> list[str]:
        out: list[str] = []

        if self.calendar is not None:
            for r in self.calendar.due_now(now=now):
                out.append(f"Reminder: {r.text}.")
                self.calendar.mark_done(r.id)

        if self.handoff is not None:
            for t in self.handoff.waiting():
                if t.id not in self._announced_handoffs:
                    self._announced_handoffs.add(t.id)
                    out.append(f"I need your help with something: {t.reason}.")

        if self.queue is not None:
            try:
                from ..tasks import JobStatus
                for j in self.queue.list(JobStatus.DONE):
                    if j.id not in self._seen_jobs:
                        self._seen_jobs.add(j.id)
                        out.append(f"Finished a task: {j.result or j.kind}.")
            except Exception:
                pass

        if self.briefing_hour is not None and self.calendar is not None:
            lt = time.localtime(now)
            day = (lt.tm_year, lt.tm_yday)
            if lt.tm_hour >= self.briefing_hour and self._last_briefing_day != day:
                self._last_briefing_day = day
                from ..connectors import build_briefing
                out.append(build_briefing(calendar=self.calendar, handoff=self.handoff, now=now))

        return out

    # ---- conversational phrasing (§34) -----------------------------------

    def _phrase(self, events: list[str]) -> list[str]:
        """Turn raw event lines into ONE warm, natural spoken message in Jarvis's voice."""
        if not self.adapter or not events:
            return events
        name = self.user_name or "there"
        joined = "; ".join(events)
        prompt = (
            f"You are Jarvis, {name}'s witty, warm personal assistant, speaking OUT LOUD and "
            f"unprompted (they didn't ask — you're bringing it up). Turn these updates into one "
            f"short, natural spoken sentence to {name}, like a friend giving a heads-up — not a "
            f"robot reading a list. Address them by name naturally. Be brief.\nUpdates: {joined}"
        )
        try:
            from ..llm.adapter import Message
            resp = self.adapter.chat([
                Message("system", "You speak proactively, warmly, briefly, like a real person."),
                Message("user", prompt),
            ])
            text = (resp.text or "").strip()
            return [text] if text else events
        except Exception:
            return events

    # ---- poll ------------------------------------------------------------

    def poll(self, now: Optional[float] = None) -> list[str]:
        """Return announcements to SPEAK (present). Routes to phone when away; [] if quiet."""
        now = now if now is not None else time.time()
        if self.in_quiet_hours(now):
            # Still consume events so they don't all fire at once when quiet hours end,
            # but stay silent. (Reminders remain visible via `tasks`/`brief`.)
            self._collect(now)
            return []

        events = self._collect(now)
        if not events:
            return []

        messages = self._phrase(events)  # conversational, in Jarvis's voice

        present = self.presence.is_present() if self.presence is not None else True
        if present:
            return messages

        # Away → send to phone, nothing to speak.
        if self.notifier is not None:
            for m in messages:
                self.notifier.send(m)
            self.log(f"[proactive] you're away — sent {len(messages)} update(s) to your phone.")
        return []
