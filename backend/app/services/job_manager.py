"""The public orchestration surface for background jobs.

This is what the API routers, the worker pool and the recovery sweep all call.
It owns *intent* ("pause this job", "retry that one"); it does not own
mechanics, which live in :class:`~app.services.job_repository.JobRepository`
(persistence), :mod:`app.services.job_state` (what moves are legal) and
:mod:`app.services.event_types` (what observers see).

Two design points worth stating up front
----------------------------------------
**Pause and cancel are requests, not commands.**  A worker may be halfway
through downloading a multi-megabyte image; killing it there would leave a
truncated file in the cache.  So :meth:`pause` and :meth:`cancel` set
cooperative flags that the worker honours *between materials*.  When the job is
not currently running (queued or paused) the transition is applied immediately,
because nothing is in flight.

**Scope over globals.**  Every instance takes an explicit
:class:`~sqlalchemy.ext.asyncio.AsyncSession` and publishes through an
injected callable.  There is no module-level singleton holding an event loop,
which is what previously made these objects unusable across more than one test.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.config.logging import get_logger
from app.models.enums import JobStatus, JobType
from app.models.processing_job import ProcessingJob
from app.services import event_types, job_state
from app.services.job_repository import JobRepository
from app.services.retry_manager import RetryManager, retry_manager

logger = get_logger(__name__)

#: Signature of the event sink; injected so tests capture without a bus.
EventSink = Callable[[Any, dict[str, Any] | None], Any]


class JobManager:
    """Create, control and inspect background jobs."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: JobRepository | None = None,
        retry_policy: RetryManager | None = None,
        emit: EventSink | None = None,
    ) -> None:
        self._session = session
        self._jobs = repository or JobRepository(session)
        self._retry = retry_policy or retry_manager()
        self._emit: EventSink = emit or (lambda kind, ctx=None: event_types.emit(kind, ctx))

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    async def create(
        self,
        job_type: JobType | str = JobType.PROCESS_BATCH,
        *,
        batch_id: str | None = None,
        batch_name: str | None = None,
        material_id: int | None = None,
        parent_job_id: int | None = None,
        payload: dict[str, Any] | None = None,
        total_items: int = 0,
        priority: int = 100,
        created_by_id: int | None = None,
        queue_immediately: bool = False,
    ) -> ProcessingJob:
        """Create a job row and announce it.

        ``queue_immediately`` exists for the upload endpoint, which wants the
        job visible in the queue the moment the response returns.  Everything
        else creates ``PENDING`` and waits for an explicit start, so an
        operator can prepare a job and launch it deliberately.
        """
        settings = get_settings()
        status = JobStatus.QUEUED if queue_immediately else JobStatus.PENDING
        job = await self._jobs.create(
            job_type,
            batch_id=batch_id,
            batch_name=batch_name,
            material_id=material_id,
            parent_job_id=parent_job_id,
            payload=payload,
            total_items=total_items,
            priority=priority,
            max_attempts=settings.job_max_attempts,
            created_by_id=created_by_id,
            status=status,
        )
        await self._session.commit()
        self._publish(
            event_types.EventType.JOB_CREATED,
            job,
            extra={"total_items": job.total_items, "batch_id": job.batch_id},
        )
        if queue_immediately:
            self._publish(event_types.EventType.JOB_QUEUED, job)
        return job

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------
    async def start(self, job_id: int) -> ProcessingJob:
        """Make a job runnable: ``PENDING`` -> ``QUEUED``."""
        job = await self._jobs.require(job_id, for_update=True)
        if job.status is not JobStatus.QUEUED:
            await self._jobs.transition(job, JobStatus.QUEUED, reason="start")
        await self._session.commit()
        self._publish(event_types.EventType.JOB_QUEUED, job)
        return job

    async def pause(self, job_id: int) -> ProcessingJob:
        """Ask a job to stop at the next material boundary."""
        job = await self._jobs.require(job_id, for_update=True)
        if job.status is JobStatus.RUNNING:
            # In flight: request only.  The worker performs the transition.
            await self._jobs.request_flag(job_id, pause=True)
            await self._session.commit()
            self._publish(
                event_types.EventType.JOB_STATUS_CHANGED,
                job,
                extra={"requested": "pause", "applied": False},
            )
            return job
        await self._jobs.transition(job, JobStatus.PAUSED, reason="pause")
        await self._jobs.clear_flags(job_id)
        await self._session.commit()
        self._publish(event_types.EventType.JOB_PAUSED, job)
        return job

    async def resume(self, job_id: int) -> ProcessingJob:
        """Return a paused (or failed) job to the queue.

        The row keeps its ``processed_items`` counter, so the pipeline resumes
        where it stopped instead of redoing finished materials.
        """
        job = await self._jobs.require(job_id, for_update=True)
        if job.status is JobStatus.FAILED:
            self._retry.ensure_retryable(job, force=True)
        await self._jobs.transition(job, JobStatus.QUEUED, reason="resume")
        await self._jobs.clear_flags(job_id)
        await self._session.commit()
        self._publish(
            event_types.EventType.JOB_RESUMED,
            job,
            extra={"processed_items": job.processed_items},
        )
        return job

    async def cancel(self, job_id: int) -> ProcessingJob:
        """Stop a job permanently, cooperatively when it is running."""
        job = await self._jobs.require(job_id, for_update=True)
        if job.status is JobStatus.RUNNING:
            await self._jobs.request_flag(job_id, cancel=True)
            await self._session.commit()
            self._publish(
                event_types.EventType.JOB_STATUS_CHANGED,
                job,
                extra={"requested": "cancel", "applied": False},
            )
            return job
        await self._jobs.transition(job, JobStatus.CANCELLED, reason="cancel")
        await self._jobs.clear_flags(job_id)
        await self._session.commit()
        self._publish(event_types.EventType.JOB_CANCELLED, job)
        return job

    async def retry(self, job_id: int, *, reset_attempts: bool = False) -> ProcessingJob:
        """Re-queue a failed or stalled job.

        Raises:
            PermanentJobError: when the attempt budget is spent and
                ``reset_attempts`` was not requested.
        """
        job = await self._jobs.require(job_id, for_update=True)
        if reset_attempts:
            self._retry.reset(job)
        self._retry.ensure_retryable(job, force=True)
        if job.status is JobStatus.FAILED:
            await self._jobs.transition(job, JobStatus.RETRYING, reason="operator_retry")
        await self._jobs.transition(job, JobStatus.QUEUED, reason="operator_retry")
        await self._jobs.clear_flags(job_id)
        await self._session.commit()
        self._publish(event_types.EventType.JOB_RETRIED, job)
        self._publish(event_types.EventType.JOB_QUEUED, job)
        return job

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def get(self, job_id: int) -> ProcessingJob | None:
        """Fetch one job, or ``None`` when it does not exist."""
        return await self._jobs.get(job_id)

    async def require(self, job_id: int) -> ProcessingJob:
        """Fetch one job or raise :class:`JobNotFoundError`."""
        return await self._jobs.require(job_id)

    async def list_jobs(
        self,
        *,
        statuses: Sequence[JobStatus] | None = None,
        batch_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProcessingJob]:
        """Newest-first page of jobs, optionally filtered."""
        if statuses:
            jobs = await self._jobs.list_by_status(
                statuses, limit=limit, offset=offset
            )
        else:
            jobs = await self._jobs.list_by_status(
                list(JobStatus), limit=limit, offset=offset
            )
        if batch_id is not None:
            jobs = [job for job in jobs if job.batch_id == batch_id]
        return jobs

    async def counts(self) -> dict[str, int]:
        """``{status: count}`` across all jobs - the dashboard's status tiles."""
        return await self._jobs.count_by_status()

    def describe(self, job: ProcessingJob) -> dict[str, Any]:
        """JSON-ready view of a job for the API and websocket payloads.

        Absolute paths are never present here - only the job's own numeric
        identity and counters - so the mapping is safe to publish.
        """
        return {
            "id": job.id,
            "job_type": str(job.job_type),
            "status": str(job.status),
            "batch_id": job.batch_id,
            "material_id": job.material_id,
            "progress": job.progress,
            "total_items": job.total_items,
            "processed_items": job.processed_items,
            "succeeded_items": job.succeeded_items,
            "failed_items": job.failed_items,
            "skipped_items": job.skipped_items,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
            "worker_id": job.worker_id,
            "error": job.error,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "queued_at": job.queued_at.isoformat() if job.queued_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "heartbeat_at": (
                job.heartbeat_at.isoformat() if job.heartbeat_at else None
            ),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _publish(
        self,
        event: event_types.EventType,
        job: ProcessingJob,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Emit one lifecycle event for ``job``.

        Failures are swallowed: a websocket fan-out fault must never roll back
        a state change that has already been committed to the database.
        """
        context: dict[str, Any] = {
            "job_id": job.id,
            "job_type": str(job.job_type),
            "status": str(job.status),
            "progress": job.progress,
            "batch_id": job.batch_id,
        }
        context.update(extra or {})
        try:
            self._emit(event, context)
        except Exception as exc:  # noqa: BLE001 - observability must not block work
            logger.warning("job.event_publish_failed", event=str(event), error=str(exc))


def job_manager(session: AsyncSession, **kwargs: Any) -> JobManager:
    """A :class:`JobManager` bound to ``session``."""
    return JobManager(session, **kwargs)


__all__ = ["EventSink", "JobManager", "job_manager"]


