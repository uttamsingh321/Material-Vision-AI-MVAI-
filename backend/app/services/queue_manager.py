"""Durable job queue backed by the ``processing_jobs`` table.

This is the "Queue Manager" from the specification, and it is intentionally
*not* an ``asyncio.Queue``.  The reasoning matters:

* A job must survive a process crash.  Anything held only in memory does not.
* Two processes (or two workers) must never run the same job.  That needs a
  conditional write in the database, not a lock in one process.
* A restart must find the work.  A query finds it; a drained queue cannot.

The in-process wake-up signal (:class:`asyncio.Event`) is only an optimisation
that turns "poll every second" into "wake immediately, plus a periodic safety
poll".  Correctness never depends on it - a missed notification costs latency,
not work.

Event-loop ownership
--------------------
The wake-up event is created **lazily on first use inside the running loop**,
and :meth:`QueueManager.close` clears it.  A process-wide singleton that built
its primitives in an import-time loop was the root cause of the cross-test
deadlock this module replaces, so the object is explicitly single-loop and
single-use rather than pretending to be a global.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import get_logger
from app.models.enums import JobStatus, JobType
from app.models.processing_job import ProcessingJob
from app.services import event_types
from app.services.job_repository import JobRepository

logger = get_logger(__name__)

#: Statuses that count as "waiting to be claimed".
WAITING_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RETRYING, JobStatus.RECOVERING}
)


class QueueManager:
    """Claims jobs for workers, using the database as the queue."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: JobRepository | None = None,
    ) -> None:
        self._session = session
        self._jobs = repository or JobRepository(session)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def bind(self) -> asyncio.Event:
        """Attach to the running loop and return the wake-up event.

        Idempotent per loop.  Rebinding to a *different* loop replaces the
        event, which is what lets a test create a fresh manager per event loop
        without leaking a bound primitive from the previous one.
        """
        loop = asyncio.get_running_loop()
        if self._loop is not loop or self._wake is None:
            self._loop = loop
            self._wake = asyncio.Event()
        return self._wake

    async def close(self) -> None:
        """Release loop-bound state; safe to call more than once."""
        self._wake = None
        self._loop = None

    def notify(self) -> None:
        """Signal that new work may be available.

        Never blocks, and never raises if the loop has gone away, so it is safe
        to call from a synchronous request handler.
        """
        if self._wake is not None:
            try:
                self._wake.set()
            except RuntimeError:  # pragma: no cover - loop already closed
                self._wake = None

    async def wait_for_work(self, timeout: float) -> bool:
        """Sleep until notified or ``timeout`` elapses.

        Returns ``True`` when a notification arrived, ``False`` on timeout.  The
        timeout is what makes this safe even if a notification is lost.
        """
        wake = self.bind()
        try:
            await asyncio.wait_for(wake.wait(), timeout=timeout)
        except TimeoutError:
            return False
        if wake.is_set():
            # Clear only if still set: a notification that arrived while we
            # were handling a job must not be discarded as if it never came.
            wake.clear()
        return True

    # ------------------------------------------------------------------
    # Work
    # ------------------------------------------------------------------
    async def claim(
        self,
        worker_id: str,
        *,
        job_types: Sequence[JobType] | None = None,
        batch_id: str | None = None,
        now: datetime | None = None,
    ) -> ProcessingJob | None:
        """Claim the next runnable job, or ``None`` when the queue is empty."""
        job = await self._jobs.claim_next(
            worker_id, job_types=job_types, batch_id=batch_id, now=now
        )
        if job is not None:
            event_types.emit(
                event_types.EventType.JOB_STARTED,
                {
                    "job_id": job.id,
                    "job_type": str(job.job_type),
                    "status": str(job.status),
                    "worker_id": worker_id,
                    "attempts": job.attempts,
                },
            )
        return job

    async def depth(self) -> int:
        """How many jobs are waiting to be claimed."""
        return len(await self._jobs.list_by_status(sorted(WAITING_STATUSES)))

    async def heartbeat(self, job_id: int, *, now: datetime | None = None) -> bool:
        """Refresh a claimed job's liveness stamp."""
        return await self._jobs.heartbeat(job_id, now=now)

    async def complete(
        self,
        job: ProcessingJob,
        *,
        result: dict[str, object] | None = None,
        now: datetime | None = None,
    ) -> ProcessingJob:
        """Mark a claimed job finished successfully."""
        await self._jobs.transition(
            job, JobStatus.COMPLETED, result=result, now=now, reason="completed"
        )
        await self._session.commit()
        event_types.emit(
            event_types.EventType.JOB_COMPLETED,
            {
                "job_id": job.id,
                "job_type": str(job.job_type),
                "status": str(job.status),
                "progress": job.progress,
            },
        )
        return job

    async def fail(
        self,
        job: ProcessingJob,
        error: BaseException | str,
        *,
        error_type: str | None = None,
        now: datetime | None = None,
    ) -> ProcessingJob:
        """Record a terminal failure on a claimed job.

        This records the *observation*; whether the job may be retried is a
        separate decision owned by
        :class:`~app.services.retry_manager.RetryManager`, so a policy change
        never requires editing this method.
        """
        message = str(error)
        kind = (
            error_type
            or (type(error).__name__ if isinstance(error, BaseException) else "JobError")
        )
        await self._jobs.transition(
            job,
            JobStatus.FAILED,
            error=message,
            error_type=kind,
            now=now,
            reason="handler_failed",
        )
        await self._session.commit()
        event_types.emit(
            event_types.EventType.JOB_FAILED,
            {
                "job_id": job.id,
                "job_type": str(job.job_type),
                "status": str(job.status),
                "error": message,
                "error_type": kind,
            },
        )
        return job


__all__ = ["QueueManager", "WAITING_STATUSES"]

