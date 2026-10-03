"""Crash recovery: reconcile jobs the previous process left behind.

On start-up the platform must answer one question: *what was in flight when
we died?*  This module answers it, and it is the reason the whole design puts
job state in the database rather than in memory.

The sweep is deliberately conservative.  For every job found active it applies
exactly one of four outcomes:

``QUEUED`` / ``PENDING``
    Nothing was running.  Leave it for a worker.
``RECOVERING`` -> ``RETRYING`` -> ``QUEUED``
    A worker was mid-flight.  Quarantine, then re-queue so the pipeline
    resumes from its ``processed_items`` counter instead of starting over.
``PAUSED``
    The operator paused it before the crash.  Respect that - an automatic
    recovery must never un-pause work a human deliberately stopped.
``FAILED``
    Its retry budget is gone.  Stop, loudly, rather than looping forever.

Every decision is emitted as a structured event, so an operator watching the
dashboard sees *why* a job restarted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import get_logger
from app.models.enums import JOB_ACTIVE_STATUSES, JobStatus
from app.models.processing_job import ProcessingJob
from app.services import event_types
from app.services.heartbeat_monitor import HeartbeatMonitor
from app.services.job_repository import JobRepository
from app.services.retry_manager import RetryManager, retry_manager

logger = get_logger(__name__)


@dataclass(slots=True)
class RecoveryOutcome:
    """What the sweep did, job by job, for the startup log and the tests."""

    requeued: list[int] = field(default_factory=list)
    retried: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    left_paused: list[int] = field(default_factory=list)
    untouched: list[int] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)

    @property
    def recovered_count(self) -> int:
        """Total jobs the sweep actively moved."""
        return (
            len(self.requeued)
            + len(self.retried)
            + len(self.failed)
            + len(self.left_paused)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "requeued": list(self.requeued),
            "retried": list(self.retried),
            "failed": list(self.failed),
            "left_paused": list(self.left_paused),
            "untouched": list(self.untouched),
            "recovered_count": self.recovered_count,
            "errors": [list(pair) for pair in self.errors],
        }


class RecoveryManager:
    """Reconciles job rows left active by a previous process."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: JobRepository | None = None,
        monitor: HeartbeatMonitor | None = None,
        retry_policy: RetryManager | None = None,
        emit: Any | None = None,
    ) -> None:
        self._session = session
        self._jobs = repository or JobRepository(session)
        self._monitor = monitor or HeartbeatMonitor()
        self._retry = retry_policy or retry_manager()
        self._emit = emit or (lambda kind, ctx=None: event_types.emit(kind, ctx))

    async def recover_all(
        self,
        *,
        now: datetime | None = None,
        statuses: Sequence[JobStatus] | None = None,
    ) -> RecoveryOutcome:
        """Sweep every active job and return what happened to each.

        Jobs with no possible in-flight state (``FAILED`` that never entered
        recovery) are checked individually: they are no-ops, so batching the
        bulk query tight keeps the sweep fast while the explicit
        ``FAILED``-inclusion keeps the semantics honest.
        """
        moment = now or datetime.now(timezone.utc)
        wanted = set(statuses) if statuses else set(JOB_ACTIVE_STATUSES)
        wanted |= {JobStatus.FAILED}
        self._session.expire_all()
        candidates = await self._jobs.list_by_status(sorted(wanted))
        outcome = RecoveryOutcome()
        for job in candidates:
            try:
                await self._recover_one(job, outcome, now=moment)
            except Exception as exc:  # noqa: BLE001 - one bad row must not stop the sweep
                await self._session.rollback()
                outcome.errors.append((job.id, str(exc)))
                logger.error("job.recovery_failed", job_id=job.id, error=str(exc))
        await self._session.commit()
        logger.info("job.recovery_sweep", **outcome.as_dict())
        return outcome

    async def recover_stale(self, *, now: datetime | None = None) -> RecoveryOutcome:
        """Re-queue only the running jobs whose heartbeat has expired.

        This is the *periodic* path, as opposed to :meth:`recover_all` which is
        the *start-up* path.  A stale job is one whose worker vanished mid-run
        while the rest of the system stayed up.
        """
        moment = now or datetime.now(timezone.utc)
        stale_jobs = await self._jobs.list_stale(
            stale_after_seconds=self._monitor.stale_after_seconds, now=moment
        )
        confirmed = await self._monitor.scan(stale_jobs, now=moment)
        confirmed_ids = {item.job_id for item in confirmed}
        outcome = RecoveryOutcome()
        for job in stale_jobs:
            if job.id not in confirmed_ids:
                outcome.untouched.append(job.id)
                continue
            try:
                await self._recover_one(job, outcome, now=moment, stale=True)
            except Exception as exc:  # noqa: BLE001
                await self._session.rollback()
                outcome.errors.append((job.id, str(exc)))
                logger.error("job.stale_recovery_failed", job_id=job.id, error=str(exc))
        await self._session.commit()
        return outcome

    async def _recover_one(
        self,
        job: ProcessingJob,
        outcome: RecoveryOutcome,
        *,
        now: datetime,
        stale: bool = False,
    ) -> None:
        """Apply the single correct outcome for ``job``."""
        await self._session.refresh(job)
        if job.status is JobStatus.PAUSED:
            # A human stopped this on purpose; never override that implicitly.
            outcome.left_paused.append(job.id)
            return

        if job.status is JobStatus.RUNNING:
            await self._jobs.transition(
                job, JobStatus.RECOVERING, now=now, reason="startup_recovery"
            )
            self._publish(event_types.EventType.JOB_RECOVERING, job)
            # Keep the in-memory value in step; the repository's transition
            # wrote through the ORM object but an expire-on-commit session may
            # hand back a detached instance.
            job.status = JobStatus.RECOVERING
            self._monitor.forget(job.id)

        if job.status in {JobStatus.RECOVERING, JobStatus.RETRYING}:
            if self._retry.attempts_remaining(job) <= 0:
                await self._jobs.transition(
                    job,
                    JobStatus.FAILED,
                    now=now,
                    error="retry budget exhausted after process restart",
                    error_type="RecoveryExhausted",
                    reason="recovery_budget_exhausted",
                )
                outcome.failed.append(job.id)
                self._publish(event_types.EventType.JOB_FAILED, job)
                return
            if job.status is not JobStatus.RETRYING:
                # Jobs arriving from RUNNING were quarantined as RECOVERING;
                # mark them as an explicit retry first so the audit trail (and
                # the UI) can distinguish "recovered" from "requeued".
                await self._jobs.transition(
                    job, JobStatus.RETRYING, now=now, reason="recovery_retry"
                )
            await self._jobs.transition(
                job, JobStatus.QUEUED, now=now, reason="recovery_requeue"
            )
            outcome.retried.append(job.id)
            self._publish(
                event_types.EventType.JOB_RECOVERED,
                job,
                extra={"stale": stale, "attempts": job.attempts},
            )
            return

        outcome.untouched.append(job.id)

    def _publish(
        self, event: event_types.EventType, job: ProcessingJob, **extra: Any
    ) -> None:
        """Emit a recovery event; never let observability break the sweep."""
        context: dict[str, Any] = {
            "job_id": job.id,
            "job_type": str(job.job_type),
            "status": str(job.status),
            "attempts": job.attempts,
        }
        context.update(extra)
        try:
            self._emit(event, context)
        except Exception as exc:  # noqa: BLE001
            logger.warning("job.recovery_event_failed", event=str(event), error=str(exc))


__all__ = ["RecoveryManager", "RecoveryOutcome"]


