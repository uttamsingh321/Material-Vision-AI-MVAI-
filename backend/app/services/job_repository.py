"""Persistence for background jobs - the repository layer.

Every SQL statement touching ``processing_jobs`` lives here.  Services above it
(:class:`~app.services.job_manager.ProcessingJobManager`,
:class:`~app.services.queue_manager.QueueManager`, the recovery sweep) deal in
ORM objects and :class:`~app.models.enums.JobStatus` values and never write a
query, which is what keeps the lifecycle rules in
:mod:`app.services.job_state` enforceable.

Why the database is the queue
-----------------------------
The model docstring already commits to this: *the database, not the in-process
queue, is the source of truth*.  That single decision is what makes a crashed
worker survivable - a job whose worker vanished is still a row, and the next
startup sweep can find it.  An ``asyncio.Queue`` would lose it.

Claiming is therefore **optimistic**: read the best candidate id, then update
it conditionally (``WHERE id = :id AND status IN (...)``) and check the row
count.  Two workers racing for the same row means exactly one sees
``rowcount == 1``; the loser simply tries the next candidate.  This is
portable - SQLite has no ``SKIP LOCKED``, and correctness does not depend on
one being available.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import get_logger
from app.models.enums import JOB_ACTIVE_STATUSES, JobStatus, JobType
from app.models.processing_job import ProcessingJob
from app.services import job_state
from app.services.progress import percent

logger = get_logger(__name__)

#: How many times :meth:`JobRepository.claim_next` retries after losing a race.
CLAIM_RETRIES = 3


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_status(value: JobStatus | str) -> JobStatus:
    """Accept a member or its persisted string value."""
    return value if isinstance(value, JobStatus) else JobStatus(value)


class JobNotFoundError(LookupError):
    """No job exists with the requested id."""

    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        super().__init__(f"processing job {job_id} does not exist")


class JobRepository:
    """CRUD and the few conditional updates the orchestration layer needs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def get(self, job_id: int, *, for_update: bool = False) -> ProcessingJob | None:
        """Fetch one job, or ``None``.

        Reads are *authoritative*: ``populate_existing`` overwrites the
        identity-map copy with the committed database state, so a manager that
        previously touched this row in its session still sees what a worker in
        another session just wrote.  All call sites read clean rows - nothing
        here is ever called with unflushed changes pending - so no dirty
        state can be discarded by the re-read.

        ``for_update`` is a no-op on SQLite and a row lock on databases that
        support it; it is passed by callers that are about to mutate.
        """
        stmt: Select[Any] = (
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .execution_options(populate_existing=True)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return await self._session.scalar(stmt)

    async def require(self, job_id: int, *, for_update: bool = False) -> ProcessingJob:
        """Fetch one job or raise :class:`JobNotFoundError`."""
        job = await self.get(job_id, for_update=for_update)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    async def list_by_status(
        self,
        statuses: Sequence[JobStatus],
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ProcessingJob]:
        """Newest-first page of jobs in any of ``statuses``.

        An empty filter matches nothing: it is the caller's way of asking for
        "no statuses at all", and silently ignoring it would be a surprise.
        """
        if not statuses:
            return []
        stmt = (
            select(ProcessingJob)
            .where(ProcessingJob.status.in_(list(statuses)))
            .order_by(ProcessingJob.created_at.desc(), ProcessingJob.id.desc())
            .execution_options(populate_existing=False)
            .offset(offset)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await self._session.scalars(stmt)).all()
        # Every candidate is re-fetched by primary key: the sweep must see the
        # latest committed state even when the caller session wrote to these
        # rows earlier (a recovered worker died mid-write, the test set up a
        # claim, ...).  ``populate_existing`` on the bulk select is not
        # enough, because the ORM identity map can already hold an object whose
        # status predates the raw UPDATE that actually moved the row.
        return [await self.require(row.id) for row in rows]

    async def count_by_status(self) -> dict[str, int]:
        """``{status: count}`` for every status present - powers the dashboard."""
        stmt = select(ProcessingJob.status, func.count()).group_by(ProcessingJob.status)
        return {str(status): int(count) for status, count in (await self._session.execute(stmt)).all()}

    async def list_stale(
        self, *, stale_after_seconds: int, now: datetime | None = None
    ) -> list[ProcessingJob]:
        """Running jobs whose heartbeat predates the staleness cutoff.

        A job that has never heartbeated is judged from its ``started_at``, so
        a worker that died between claiming and its first beat is still caught.
        """
        cutoff = (now or _utcnow()) - timedelta(seconds=stale_after_seconds)
        running = JobStatus.RUNNING
        return list(
            (
                await self._session.scalars(
                    select(ProcessingJob).where(
                        ProcessingJob.status == running,
                        func.coalesce(
                            ProcessingJob.heartbeat_at, ProcessingJob.started_at
                        )
                        < cutoff,
                    )
                )
            ).all()
        )

    async def list_recoverable(self) -> list[ProcessingJob]:
        """Active jobs a start-up sweep must reconcile.

        ``PENDING`` and ``QUEUED`` are included because a sweep that only
        looked at ``RUNNING`` would leave a job stranded in ``RETRYING``
        forever if the process died between the two writes.
        """
        return await self.list_by_status(sorted(JOB_ACTIVE_STATUSES))

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    async def create(
        self,
        job_type: JobType | str,
        *,
        batch_id: str | None = None,
        batch_name: str | None = None,
        material_id: int | None = None,
        parent_job_id: int | None = None,
        payload: dict[str, Any] | None = None,
        total_items: int = 0,
        priority: int = 100,
        max_attempts: int = 3,
        created_by_id: int | None = None,
        status: JobStatus = JobStatus.PENDING,
        now: datetime | None = None,
    ) -> ProcessingJob:
        """Insert a new job row and flush it so ``job.id`` is populated.

        The row starts ``PENDING``: created is not the same as queued, and an
        operator should be able to create a job and start it later.
        """
        moment = now or _utcnow()
        job = ProcessingJob(
            job_type=job_type if isinstance(job_type, JobType) else JobType(job_type),
            status=_as_status(status),
            batch_id=batch_id,
            batch_name=batch_name,
            material_id=material_id,
            parent_job_id=parent_job_id,
            payload=payload or {},
            total_items=total_items,
            priority=priority,
            max_attempts=max_attempts,
            created_by_id=created_by_id,
            queued_at=moment if status == JobStatus.QUEUED else None,
        )
        self._session.add(job)
        await self._session.flush()
        logger.info(
            "job.created",
            job_id=job.id,
            job_type=str(job.job_type),
            status=str(job.status),
        )
        return job

    async def transition(
        self,
        job: ProcessingJob,
        target: JobStatus | str,
        *,
        now: datetime | None = None,
        error: str | None = None,
        error_type: str | None = None,
        result: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> ProcessingJob:
        """Move ``job`` to ``target``, enforcing the lifecycle table.

        Timestamps are set as a consequence of the *target*, not of the caller:
        entering ``RUNNING`` stamps ``started_at`` and clears the control
        flags, entering a finished state stamps ``finished_at``, and returning
        to ``QUEUED`` refreshes ``queued_at``.  That removes a whole class of
        "the caller forgot to update the timestamp" bug.

        Raises:
            InvalidJobTransition: when the move is not permitted.
        """
        moment = now or _utcnow()
        goal = _as_status(target)
        job_state.ensure_transition(job.status, goal)

        previous = job.status
        job.status = goal
        if goal is JobStatus.RUNNING:
            if job.started_at is None:
                job.started_at = moment
            job.heartbeat_at = moment
            # A fresh run starts from a clean slate: the previous run's
            # cooperative-cancel/pause requests have already been honoured.
            job.cancel_requested = False
            job.pause_requested = False
        elif goal is JobStatus.QUEUED:
            job.queued_at = moment
            job.worker_id = None
        elif job_state.is_terminal(goal):
            job.finished_at = moment
            job.worker_id = None
            job.heartbeat_at = moment

        if error is not None or goal is JobStatus.FAILED:
            job.error = error or job.error
            job.error_type = error_type or job.error_type
        if result is not None:
            job.result = result

        await self._session.flush()
        logger.info(
            "job.transitioned",
            job_id=job.id,
            previous=str(previous),
            target=str(goal),
            reason=reason,
        )
        return job

    # ------------------------------------------------------------------
    # Claiming and progress
    # ------------------------------------------------------------------
    async def claim_next(
        self,
        worker_id: str,
        *,
        now: datetime | None = None,
        statuses: Sequence[JobStatus] | None = None,
        job_types: Sequence[JobType] | None = None,
        batch_id: str | None = None,
    ) -> ProcessingJob | None:
        """Atomically claim the highest-priority runnable job for ``worker_id``.

        Ordering is *priority first, then age*: a low ``priority`` number wins,
        and among equals the oldest ``queued_at`` goes first so nothing starves.

        The conditional ``UPDATE ... WHERE status IN (...)`` is the lock.  If a
        competing worker won the race, ``rowcount`` is 0 and we try the next
        candidate; after :data:`CLAIM_RETRIES` losses we give up and return
        ``None`` rather than spin.
        """
        moment = now or _utcnow()
        claimable = list(statuses) if statuses else sorted(job_state.CLAIMABLE_STATUSES)

        for _ in range(CLAIM_RETRIES):
            candidate = await self._next_candidate(
                statuses=claimable, job_types=job_types, batch_id=batch_id
            )
            if candidate is None:
                return None
            stmt = (
                update(ProcessingJob)
                .where(
                    ProcessingJob.id == candidate,
                    ProcessingJob.status.in_(claimable),
                )
                .values(
                    status=JobStatus.RUNNING,
                    worker_id=worker_id,
                    started_at=func.coalesce(ProcessingJob.started_at, moment),
                    heartbeat_at=moment,
                    cancel_requested=False,
                    pause_requested=False,
                    attempts=ProcessingJob.attempts + 1,
                )
                .execution_options(synchronize_session="fetch")
            )
            result = await self._session.execute(stmt)
            if result.rowcount:
                await self._session.commit()
                job = await self.require(candidate)
                # The conditional UPDATE above bypassed the ORM, so the row
                # already in the identity map still carries its pre-claim
                # status.  A plain SELECT would hand that stale object back,
                # and the worker would believe it never received the job.
                # ``refresh`` re-reads the committed state.
                await self._session.refresh(job)
                return job
        logger.debug("job.claim_contended", worker_id=worker_id)
        return None

    async def _next_candidate(
        self,
        *,
        statuses: Sequence[JobStatus],
        job_types: Sequence[JobType] | None,
        batch_id: str | None,
    ) -> int | None:
        """Id of the best runnable job, without claiming it.

        ``populate_existing`` keeps the selection fresh even when this session
        previously touched the row: otherwise a test (or a worker sharing a
        long-lived session) could keep seeing a status it wrote itself, and
        claim the wrong job.
        """
        stmt: Select[Any] = (
            select(ProcessingJob.id)
            .where(ProcessingJob.status.in_(list(statuses)))
            .execution_options(populate_existing=True)
        )
        if job_types:
            stmt = stmt.where(ProcessingJob.job_type.in_(list(job_types)))
        if batch_id is not None:
            stmt = stmt.where(ProcessingJob.batch_id == batch_id)
        stmt = stmt.order_by(
            ProcessingJob.priority.asc(),
            ProcessingJob.queued_at.asc(),
            ProcessingJob.id.asc(),
        ).limit(1)
        return await self._session.scalar(stmt)

    async def heartbeat(self, job_id: int, *, now: datetime | None = None) -> bool:
        """Refresh the liveness stamp; ``False`` when the job is gone.

        Only ``RUNNING`` jobs are stamped.  A late beat from a worker whose job
        was already cancelled or recovered must not resurrect the timestamp and
        hide the job from the stale sweep.
        """
        result = await self._session.execute(
            update(ProcessingJob)
            .where(
                ProcessingJob.id == job_id,
                ProcessingJob.status == JobStatus.RUNNING,
            )
            .values(heartbeat_at=now or _utcnow())
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)

    async def update_counters(
        self,
        job_id: int,
        *,
        processed: int | None = None,
        succeeded: int | None = None,
        failed: int | None = None,
        skipped: int | None = None,
        total: int | None = None,
        progress: int | None = None,
    ) -> None:
        """Apply counter values and recompute ``progress`` from them.

        Counters arrive as absolute values and are clamped at this boundary, so
        a buggy or duplicated callback cannot drive progress above 100 or
        below 0.  ``progress`` may be passed explicitly only when the caller
        knows better than the ratio (an export job, say, which counts files
        rather than materials).
        """
        current = await self.get(job_id)
        if current is None:
            raise JobNotFoundError(job_id)
        for column, value in (
            ("processed_items", processed),
            ("succeeded_items", succeeded),
            ("failed_items", failed),
            ("skipped_items", skipped),
        ):
            if value is not None:
                setattr(current, column, max(int(value), 0))
        if total is not None:
            current.total_items = max(int(total), 0)
        current.progress = (
            progress
            if progress is not None
            else percent(current.processed_items, current.total_items)
        )
        await self._session.flush()

    async def request_flag(
        self, job_id: int, *, cancel: bool = False, pause: bool = False
    ) -> bool:
        """Set the cooperative ``cancel_requested`` / ``pause_requested`` flags.

        Cooperative rather than preemptive: a worker only stops between
        materials, so no half-written workbook or half-cached image can result.
        """
        values: dict[str, Any] = {}
        if cancel:
            values["cancel_requested"] = True
        if pause:
            values["pause_requested"] = True
        if not values:
            return False
        result = await self._session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)

    async def clear_flags(self, job_id: int) -> None:
        """Drop any outstanding pause/cancel request."""
        await self._session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(pause_requested=False, cancel_requested=False)
            .execution_options(synchronize_session=False)
        )


__all__ = [
    "CLAIM_RETRIES",
    "JobNotFoundError",
    "JobRepository",
]


