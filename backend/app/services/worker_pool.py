"""A pool of asyncio workers that drain the durable job queue.

Each worker is an independent coroutine with its own database session and its
own identity (``host:pid:slot``).  They compete for jobs through the
conditional claim in :class:`~app.services.job_repository.JobRepository`, so
adding capacity needs no coordination and removing it is just a cancel.

Failure isolation is the point of a pool.  A handler that raises must not take
its siblings down, so every iteration is wrapped: the exception is recorded on
the job, the worker's session is rolled back, and the loop continues.

Cancellation semantics
----------------------
``stop()`` asks the workers to finish the job in hand and then exit, with a
bounded grace period.  A hard cancel mid-job would leave a half-written export
behind, so :meth:`stop` escalates only if a worker overruns ``grace_seconds``.
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Awaitable, Callable
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.config.logging import get_logger
from app.database.session import get_session_factory
from app.models.enums import JobType
from app.models.processing_job import ProcessingJob
from app.services.queue_manager import QueueManager

logger = get_logger(__name__)

#: A handler receives the claimed job and the worker's own session, and returns
#: a JSON-ready result mapping (or ``None``).
JobHandler = Callable[[ProcessingJob, Any], Awaitable[dict[str, Any] | None]]


def worker_identity(slot: int) -> str:
    """Stable, human-readable worker id: ``host:pid:slot``.

    Written into ``processing_jobs.worker_id`` so an operator can trace a stuck
    job back to the exact worker that claimed it.
    """
    return f"{socket.gethostname()}:{os.getpid()}:{slot}"


class WorkerPool:
    """Runs registered job handlers concurrently against the durable queue."""

    def __init__(
        self,
        *,
        handlers: dict[JobType, JobHandler] | None = None,
        concurrency: int | None = None,
        poll_interval: float | None = None,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        settings = get_settings()
        self.concurrency = max(int(concurrency or settings.worker_concurrency), 1)
        self.poll_interval = float(
            poll_interval if poll_interval is not None else settings.worker_poll_interval_seconds
        )
        self._handlers: dict[JobType, JobHandler] = dict(handlers or {})
        self._session_factory = session_factory or (lambda: get_session_factory()())
        self._tasks: list[asyncio.Task[None]] = []
        self._queues: list[QueueManager] = []
        self._running = False
        self._stopping = asyncio.Event()
        #: Jobs finished by this pool, for tests and the health endpoint.
        self.completed_jobs = 0
        self.failed_jobs = 0

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def register(self, job_type: JobType | str, handler: JobHandler) -> None:
        """Bind a handler to a job type.

        Raises:
            ValueError: when re-registering a type, which would silently
                change the meaning of jobs already queued.
        """
        key = job_type if isinstance(job_type, JobType) else JobType(job_type)
        if key in self._handlers:
            raise ValueError(f"a handler is already registered for {key}")
        self._handlers[key] = handler

    def handles(self, job_type: JobType) -> bool:
        """``True`` when this pool can run ``job_type``."""
        return job_type in self._handlers

    @property
    def running(self) -> bool:
        """``True`` between :meth:`start` and :meth:`stop`."""
        return self._running

    @property
    def active_workers(self) -> int:
        """How many worker tasks are currently alive."""
        return sum(1 for task in self._tasks if not task.done())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Spawn ``concurrency`` workers.

        Idempotent: calling it twice is a no-op, so an application lifespan
        hook and a test can both call it without doubling the workers.
        """
        if self._running:
            return
        if not self._handlers:
            raise RuntimeError("WorkerPool.start() requires at least one registered handler")
        self._stopping = asyncio.Event()
        self._running = True
        self._tasks = [
            asyncio.create_task(self._worker_loop(slot), name=f"mvai-worker-{slot}")
            for slot in range(self.concurrency)
        ]
        logger.info("worker_pool.started", concurrency=self.concurrency)

    async def stop(self, *, grace_seconds: float = 5.0) -> None:
        """Ask every worker to finish and exit, escalating if it overruns."""
        if not self._running:
            return
        self._running = False
        self._stopping.set()
        for queue in self._queues:
            queue.notify()
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=grace_seconds,
                )
            except TimeoutError:
                logger.warning("worker_pool.grace_expired", grace_seconds=grace_seconds)
                for task in self._tasks:
                    task.cancel()
                await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        for queue in self._queues:
            await queue.close()
        self._queues.clear()
        logger.info("worker_pool.stopped", completed=self.completed_jobs, failed=self.failed_jobs)

    # ------------------------------------------------------------------
    # The worker loop
    # ------------------------------------------------------------------
    async def _worker_loop(self, slot: int) -> None:
        """Claim and run jobs until the pool is stopped.

        Each iteration uses a **fresh session** and closes it before sleeping.
        Holding one session open for the pool's lifetime would pin a
        connection for the whole process and would let a rollback from one
        failed job discard another worker's writes.
        """
        worker_id = worker_identity(slot)
        session = self._session_factory()
        queue = QueueManager(session)
        self._queues.append(queue)
        logger.debug("worker.started", worker_id=worker_id)
        try:
            while self._running:
                job: ProcessingJob | None = None
                try:
                    job = await self._run_one(worker_id, queue)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - never kill the worker
                    logger.error("worker.iteration_failed", worker_id=worker_id, error=str(exc))
                    await self._safe_rollback(session)
                if job is None and not await queue.wait_for_work(self.poll_interval):
                    continue
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            logger.debug("worker.cancelled", worker_id=worker_id)
        finally:
            await session.close()
            if queue in self._queues:
                self._queues.remove(queue)
            logger.debug("worker.stopped", worker_id=worker_id)

    async def _run_one(self, worker_id: str, queue: QueueManager) -> ProcessingJob | None:
        """Claim one job, run it, and record the outcome.

        Returns the job that was handled, or ``None`` when the queue was empty.
        Any exception raised by the handler is converted into a recorded
        failure rather than propagated, so one bad batch does not stall the
        queue behind it.
        """
        job = await queue.claim(
            worker_id, job_types=sorted(self._handlers), now=None
        )
        if job is None:
            return None
        handler = self._handlers.get(job.job_type)
        if handler is None:  # pragma: no cover - claim filtered these out
            await queue.fail(job, f"no handler registered for {job.job_type}")
            self.failed_jobs += 1
            return job
        try:
            result = await handler(job, queue)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - isolate the failure
            logger.error(
                "worker.job_failed",
                worker_id=worker_id,
                job_id=job.id,
                job_type=str(job.job_type),
                error=str(exc),
            )
            await queue.fail(job, exc)
            self.failed_jobs += 1
            return job
        await queue.complete(job, result=result)
        self.completed_jobs += 1
        return job

    @staticmethod
    async def _safe_rollback(session: Any) -> None:
        """Roll back a session, tolerating one that is already closed."""
        try:
            await session.rollback()
        except Exception as exc:  # noqa: BLE001 - pragma: no cover
            logger.debug("worker.rollback_failed", error=str(exc))

    async def run_once(self) -> ProcessingJob | None:
        """Drain at most one job in the caller's loop.

        Exists so a test - or a maintenance command - can step the pool
        deterministically instead of racing background tasks.
        """
        session = self._session_factory()
        try:
            return await self._run_one("worker-inline", QueueManager(session))
        finally:
            await session.close()


__all__ = ["JobHandler", "WorkerPool", "worker_identity"]

