"""Worker (§9) — executes queued jobs, keeps working when one is blocked (§30).

A worker pulls jobs and runs a registered handler per job kind. If a handler reports it's
blocked on a human, the job is parked (BLOCKED) and the worker moves on to other jobs —
never stalling everything. Handlers return (status, result).
"""
from __future__ import annotations

from typing import Callable, Optional

from .queue import Job, JobStatus, TaskQueue

# A handler takes a Job and returns (JobStatus, result_text).
Handler = Callable[[Job], tuple]


class Worker:
    def __init__(self, queue: TaskQueue):
        self.queue = queue
        self._handlers: dict[str, Handler] = {}

    def handler(self, kind: str):
        def deco(fn: Handler):
            self._handlers[kind] = fn
            return fn
        return deco

    def register(self, kind: str, fn: Handler) -> None:
        self._handlers[kind] = fn

    def run_one(self) -> Optional[Job]:
        """Claim and run a single job. Returns the job (with final status) or None if idle."""
        job = self.queue.claim_next()
        if job is None:
            return None
        handler = self._handlers.get(job.kind)
        if handler is None:
            self.queue.update(job.id, JobStatus.FAILED, f"no handler for kind '{job.kind}'")
            return self.queue.get(job.id)
        try:
            status, result = handler(job)
        except Exception as e:  # graceful failure (§21)
            status, result = JobStatus.FAILED, f"{type(e).__name__}: {e}"
        self.queue.update(job.id, status, result)
        return self.queue.get(job.id)

    def drain(self, max_jobs: int = 100) -> int:
        """Run queued jobs until the queue is empty (or a cap). Returns count processed.

        BLOCKED jobs are skipped (they're waiting on you), so one blocker never stalls
        the rest.
        """
        processed = 0
        for _ in range(max_jobs):
            job = self.run_one()
            if job is None:
                break
            processed += 1
        return processed
