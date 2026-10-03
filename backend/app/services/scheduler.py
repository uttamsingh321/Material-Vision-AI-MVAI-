"""The background scheduler: start-up recovery plus a periodic stale sweep.

This is the object the application lifespan owns.  It exists so that
"boot the background system" is one call with one shutdown path, instead of a
sequence that callers can half-perform.

On :meth:`Scheduler.start` it does two things, in order:

1. **Recover first.**  Jobs left ``RUNNING`` by a dead process are re-queued
   *before* any worker starts claiming, so a recovered job cannot be picked up
   by a worker that is still reading its pre-recovery state.
2. **Then start workers and the sweeper.**  The sweeper is a single periodic
   task that re-queues stalled jobs whose worker vanished while the process
   itself stayed up.

Every background task is created in the caller's running loop and cancelled in
:meth:`stop`; the scheduler holds no module-level state, so two schedulers can
coexist in one test session without interfering.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.config.logging import get_logger
from app.database.session import get_session_factory
from app.models.enums import JobType
from app.services.heartbeat_monitor import HeartbeatMonitor
from app.services.recovery_manager import RecoveryManager, RecoveryOutcome
from app.services.worker_pool import JobHandler, WorkerPool

logger = get_logger(__name__)

#: Default gap between stale sweeps.  Well above the heartbeat interval so a
#: healthy worker is never mistaken for a dead one, and well below the
#: staleness threshold so a dead worker is noticed promptly.
DEFAULT_SWEEP_INTERVAL_SECONDS = 30.0


class Scheduler:
    """Owns the lifecycle of the background-processing subsystem."""

    def __init__(
        self,
        *,
        pool: WorkerPool | None = None,
        monitor: HeartbeatMonitor | None = None,
        session_factory: Callable[[], Any] | None = None,
        sweep_interval: float | None = None,
    ) -> None:
        settings = get_settings()
        self._pool = pool or WorkerPool()
        self._monitor = monitor or HeartbeatMonitor()
        self._session_factory: Callable[[], Any] = (
            session_factory or (lambda: get_session_factory()())
        )
        self._sweep_interval = float(
            sweep_interval
            if sweep_interval is not None
            else max(settings.job_heartbeat_interval_seconds * 2, DEFAULT_SWEEP_INTERVAL_SECONDS)
        )
        self._sweeper: asyncio.Task[None] | None = None
        self._running = False
        self._stopping = asyncio.Event()
        #: Result of the most recent start-up recovery sweep.
        self.last_recovery: RecoveryOutcome | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def register(self, job_type: JobType | str, handler: JobHandler) -> None:
        """Bind a job handler onto the underlying pool."""
        self._pool.register(job_type, handler)

    @property
    def pool(self) -> WorkerPool:
        """The worker pool this scheduler runs."""
        return self._pool

    @property
    def running(self) -> bool:
        """``True`` between :meth:`start` and :meth:`stop`."""
        return self._running

    @property
    def sweep_interval(self) -> float:
        """Configured gap between stale sweeps, in seconds."""
        return self._sweep_interval

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self, *, recover: bool = True) -> RecoveryOutcome | None:
        """Recover, then start the pool and the sweeper.

        Returns the recovery outcome (or ``None`` when ``recover=False``) so a
        caller - or a test - can assert exactly what was re-queued.
        """
        if self._running:
            return self.last_recovery
        self._stopping = asyncio.Event()
        outcome: RecoveryOutcome | None = None
        if recover:
            outcome = await self.recover()
            self.last_recovery = outcome
        self._running = True
        await self._pool.start()
        self._sweeper = asyncio.create_task(
            self._sweep_loop(), name="mvai-stale-sweeper"
        )
        logger.info(
            "scheduler.started",
            concurrency=self._pool.concurrency,
            sweep_interval=self._sweep_interval,
        )
        return outcome

    async def stop(self, *, grace_seconds: float = 5.0) -> None:
        """Stop the sweeper and drain the pool.  Idempotent."""
        if not self._running:
            return
        self._running = False
        self._stopping.set()
        if self._sweeper is not None:
            self._sweeper.cancel()
            await asyncio.gather(self._sweeper, return_exceptions=True)
            self._sweeper = None
        await self._pool.stop(grace_seconds=grace_seconds)
        logger.info("scheduler.stopped")

    async def recover(self) -> RecoveryOutcome:
        """Run the start-up recovery sweep in its own session."""
        session = self._session_factory()
        try:
            manager = RecoveryManager(session, monitor=self._monitor)
            return await manager.recover_all()
        finally:
            await session.close()

    # ------------------------------------------------------------------
    # Periodic maintenance
    # ------------------------------------------------------------------
    async def sweep_once(self) -> RecoveryOutcome:
        """Re-queue stalled jobs in a fresh session.

        Exposed so tests (and an operator-triggered maintenance command) can run
        exactly one sweep without waiting for the timer.
        """
        session = self._session_factory()
        try:
            manager = RecoveryManager(session, monitor=self._monitor)
            return await manager.recover_stale()
        finally:
            await session.close()

    async def _sweep_loop(self) -> None:
        """Run :meth:`sweep_once` on a fixed interval until stopped.

        Each tick opens its own session and closes it, and every sweep is
        individually guarded: a database blip during one tick must not cancel
        the task and silently disable recovery for the rest of the process's
        life.
        """
        while self._running:
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=self._sweep_interval
                )
                return  # stop() was called
            except TimeoutError:
                pass
            try:
                outcome = await self.sweep_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep sweeping
                logger.error("scheduler.sweep_failed", error=str(exc))
                continue
            if outcome.recovered_count:
                logger.warning("scheduler.stale_jobs_recovered", **outcome.as_dict())

    async def status(self) -> dict[str, Any]:
        """Snapshot of the background subsystem for the health endpoint."""
        return {
            "running": self._running,
            "concurrency": self._pool.concurrency,
            "active_workers": self._pool.active_workers,
            "completed_jobs": self._pool.completed_jobs,
            "failed_jobs": self._pool.failed_jobs,
            "sweep_interval_seconds": self._sweep_interval,
            "stale_after_seconds": self._monitor.stale_after_seconds,
            "last_recovery": self.last_recovery.as_dict() if self.last_recovery else None,
        }


def scheduler(**kwargs: Any) -> Scheduler:
    """A scheduler configured from current settings."""
    return Scheduler(**kwargs)


__all__ = ["DEFAULT_SWEEP_INTERVAL_SECONDS", "Scheduler", "scheduler"]

