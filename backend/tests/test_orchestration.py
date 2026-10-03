"""Tests for the durable job orchestration layer.

Organised from the inside out:

1. the pure state machine and event vocabulary (no I/O),
2. retry and heartbeat policy (no I/O),
3. the repository and manager against a real SQLite database,
4. claiming, worker execution and crash recovery.

The database-backed tests delete their job rows in a fixture because
:class:`JobManager` commits internally - a rollback-based fixture could not
undo them, and leftover rows would make priority and claiming order
non-deterministic.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session_factory
from app.models.enums import JobStatus, JobType
from app.models.processing_job import ProcessingJob
from app.services import event_types, job_state
from app.services.event_types import EventType
from app.services.heartbeat_monitor import HeartbeatMonitor
from app.services.job_manager import JobManager
from app.services.job_repository import JobNotFoundError, JobRepository
from app.services.queue_manager import QueueManager
from app.services.recovery_manager import RecoveryManager
from app.services.retry_manager import (
    REASON_CANCELLED,
    REASON_EXHAUSTED,
    REASON_NOT_FAILED,
    PermanentJobError,
    RetryManager,
)
from app.services.scheduler import Scheduler
from app.services.worker_pool import WorkerPool, worker_identity

UTC = timezone.utc


def ago(seconds: float) -> datetime:
    """A UTC timestamp ``seconds`` in the past."""
    return datetime.now(UTC) - timedelta(seconds=seconds)


@pytest.fixture
async def session() -> AsyncSession:
    """A committed session whose job rows are cleaned up afterwards."""
    factory = get_session_factory()
    async with factory() as db:
        yield db
    async with factory() as cleanup:
        await cleanup.execute(delete(ProcessingJob))
        await cleanup.commit()


@pytest.fixture
def captured_events() -> list[tuple[Any, dict[str, Any]]]:
    """A list every emitted event lands in, for order-sensitive assertions."""
    return []


@pytest.fixture
def manager(
    session: AsyncSession, captured_events: list[tuple[Any, dict[str, Any]]]
) -> JobManager:
    """A JobManager whose events are captured instead of published."""
    return JobManager(
        session,
        emit=lambda kind, ctx=None: captured_events.append((kind, ctx or {})),
    )


@pytest.fixture
def event_names(captured_events: list[tuple[Any, dict[str, Any]]]):
    """Names of the captured events, in emission order."""

    def _names() -> list[str]:
        return [str(kind) for kind, _ in captured_events]

    return _names


class TestJobStateMachine:
    def test_terminal_states_accept_nothing(self) -> None:
        for status in job_state.TERMINAL_STATUSES:
            assert job_state.allowed_targets(status) == frozenset()

    def test_completed_job_cannot_be_restarted(self) -> None:
        assert not job_state.can_transition(JobStatus.COMPLETED, JobStatus.RUNNING)
        assert not job_state.can_transition(JobStatus.COMPLETED, JobStatus.QUEUED)

    def test_cancelled_job_is_final(self) -> None:
        assert job_state.is_terminal(JobStatus.CANCELLED)
        assert not job_state.can_transition(JobStatus.CANCELLED, JobStatus.QUEUED)

    def test_failed_job_may_retry(self) -> None:
        assert job_state.can_transition(JobStatus.FAILED, JobStatus.RETRYING)
        assert job_state.can_transition(JobStatus.FAILED, JobStatus.QUEUED)

    def test_pause_resumes_through_the_queue(self) -> None:
        """A paused job is re-queued, never handed straight back to a worker."""
        assert job_state.can_transition(JobStatus.PAUSED, JobStatus.QUEUED)
        assert not job_state.can_transition(JobStatus.PAUSED, JobStatus.RUNNING)

    def test_running_job_can_be_quarantined_and_requeued(self) -> None:
        assert job_state.can_transition(JobStatus.RUNNING, JobStatus.RECOVERING)
        assert job_state.can_transition(JobStatus.RECOVERING, JobStatus.QUEUED)

    def test_ensure_transition_raises_with_both_states(self) -> None:
        with pytest.raises(job_state.InvalidJobTransition) as excinfo:
            job_state.ensure_transition(JobStatus.CANCELLED, JobStatus.RUNNING)
        assert excinfo.value.current is JobStatus.CANCELLED
        assert excinfo.value.target is JobStatus.RUNNING

    def test_self_transition_is_rejected(self) -> None:
        """A no-op move signals a caller bug and must not pass silently."""
        assert not job_state.can_transition(JobStatus.RUNNING, JobStatus.RUNNING)

    def test_failed_is_not_terminal_because_it_can_retry(self) -> None:
        assert not job_state.is_terminal(JobStatus.FAILED)

    def test_every_non_initial_status_is_reachable(self) -> None:
        """No status may be an orphan that nothing can transition into."""
        targets: set[JobStatus] = set()
        for allowed in job_state._TRANSITIONS.values():  # noqa: SLF001
            targets |= set(allowed)
        for status in JobStatus:
            if status is not JobStatus.PENDING:
                assert status in targets, status

    def test_active_statuses_agree_with_the_table(self) -> None:
        """A status is active exactly when something can follow it."""
        for status in JobStatus:
            reachable = bool(job_state.allowed_targets(status))
            if status is JobStatus.FAILED:
                # Failed jobs are operator-retryable but not worker-claimable.
                continue
            assert reachable == job_state.is_active(status), status


class TestEventTypes:
    def test_envelope_always_carries_id_type_and_timestamp(self) -> None:
        payload = event_types.new_envelope(EventType.JOB_CREATED, {"job_id": 7})
        assert set(payload) == {"id", "type", "occurred_at", "job_id"}
        assert payload["type"] == "JOB_CREATED"
        assert payload["job_id"] == 7

    def test_envelope_rejects_reserved_keys(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            event_types.new_envelope(EventType.JOB_CREATED, {"id": "mine"})

    def test_specification_event_names_all_exist(self) -> None:
        """The event names the requirements call out by name."""
        for name in (
            "JOB_CREATED",
            "JOB_STARTED",
            "SEARCH_STARTED",
            "PROVIDER_COMPLETED",
            "IMAGE_DOWNLOADED",
            "OCR_COMPLETED",
            "VERIFICATION_COMPLETED",
            "CONFIDENCE_ASSIGNED",
            "IMAGE_ACCEPTED",
            "IMAGE_REJECTED",
            "EXPORT_COMPLETED",
            "ERROR_OCCURRED",
        ):
            assert name in EventType.__members__, name

    def test_emit_publishes_to_the_jobs_channel(self) -> None:
        from app.services.events import get_event_bus, reset_event_bus

        reset_event_bus()
        queue = get_event_bus().subscribe("jobs")
        event_types.emit(EventType.JOB_STARTED, {"job_id": 3})
        assert queue.get_nowait()["job_id"] == 3
        reset_event_bus()

    def test_lifecycle_events_mirror_onto_the_dashboard(self) -> None:
        from app.services.events import get_event_bus, reset_event_bus

        reset_event_bus()
        dashboard = get_event_bus().subscribe("dashboard")
        event_types.emit(EventType.JOB_COMPLETED, {"job_id": 4})
        assert dashboard.get_nowait()["type"] == "JOB_COMPLETED"
        reset_event_bus()

    def test_publishing_never_raises_on_a_broken_bus(self) -> None:
        """A dead websocket fan-out must not fail the job that emitted it."""
        from app.services import events as events_module

        original = events_module.get_event_bus

        class Exploding:
            def publish(self, channel: str, payload: dict[str, Any]) -> int:
                raise RuntimeError("bus is down")

        events_module.get_event_bus = lambda: Exploding()  # type: ignore[assignment]
        try:
            payload = event_types.emit(EventType.ERROR_OCCURRED, {"job_id": 1})
            assert payload["type"] == "ERROR_OCCURRED"
        finally:
            events_module.get_event_bus = original  # type: ignore[assignment]


class _StubJob:
    """Minimal stand-in for a ProcessingJob, for the pure policy tests."""

    def __init__(
        self,
        *,
        id: int = 1,
        status: JobStatus = JobStatus.FAILED,
        attempts: int = 1,
        max_attempts: int = 3,
        cancel_requested: bool = False,
    ) -> None:
        self.id = id
        self.status = status
        self.attempts = attempts
        self.max_attempts = max_attempts
        self.cancel_requested = cancel_requested
        self.error: str | None = "boom"
        self.error_type: str | None = "Boom"
        self.finished_at: datetime | None = ago(1)


class TestRetryManager:
    def test_a_fresh_failure_is_retryable(self) -> None:
        decision = RetryManager().evaluate(_StubJob(attempts=1, max_attempts=3))
        assert decision.retry
        assert decision

    def test_exhausted_budget_is_permanent(self) -> None:
        decision = RetryManager().evaluate(_StubJob(attempts=3, max_attempts=3))
        assert not decision.retry
        assert decision.reason == REASON_EXHAUSTED

    def test_operator_cannot_bypass_the_attempt_budget(self) -> None:
        """This is the crash-loop guard: force must not grant free attempts."""
        job = _StubJob(attempts=3, max_attempts=3)
        assert not RetryManager().evaluate(job, force=True).retry
        with pytest.raises(PermanentJobError):
            RetryManager().ensure_retryable(job, force=True)

    def test_force_does_bypass_the_must_be_failed_check(self) -> None:
        job = _StubJob(status=JobStatus.RECOVERING, attempts=1, max_attempts=3)
        assert RetryManager().evaluate(job, force=True).retry

    def test_cancelled_jobs_are_never_retried(self) -> None:
        job = _StubJob(status=JobStatus.CANCELLED, attempts=1, max_attempts=5)
        assert RetryManager().evaluate(job, force=True).reason == REASON_CANCELLED

    def test_cancel_flag_alone_blocks_a_retry(self) -> None:
        job = _StubJob(cancel_requested=True, attempts=1, max_attempts=5)
        assert RetryManager().evaluate(job).reason == REASON_CANCELLED

    def test_a_running_job_is_not_retryable(self) -> None:
        job = _StubJob(status=JobStatus.RUNNING, attempts=1, max_attempts=3)
        assert RetryManager().evaluate(job).reason == REASON_NOT_FAILED

    def test_backoff_grows_and_is_capped(self) -> None:
        manager = RetryManager()
        assert manager.delay_for(1) < manager.delay_for(2) < manager.delay_for(3)
        assert manager.delay_for(50) <= 300.0

    def test_reset_clears_the_failure_record(self) -> None:
        job = _StubJob(attempts=3, max_attempts=3)
        RetryManager().reset(job)
        assert job.attempts == 0
        assert job.error is None
        assert job.finished_at is None
        assert RetryManager().evaluate(job, force=True).retry

    def test_attempts_remaining_never_goes_negative(self) -> None:
        assert RetryManager().attempts_remaining(_StubJob(attempts=9, max_attempts=3)) == 0


class TestHeartbeatMonitor:
    def test_a_fresh_heartbeat_is_not_stale(self) -> None:
        monitor = HeartbeatMonitor(stale_after_seconds=180)
        job = _StubJob()
        job.heartbeat_at = ago(5)
        job.started_at = ago(10)
        assert not monitor.is_stale(job)

    def test_a_silent_job_is_stale(self) -> None:
        monitor = HeartbeatMonitor(stale_after_seconds=60)
        job = _StubJob()
        job.heartbeat_at = ago(600)
        job.started_at = ago(700)
        assert monitor.is_stale(job)

    def test_started_at_is_used_when_no_beat_was_ever_recorded(self) -> None:
        """A worker that dies before its first beat is still detectable."""
        monitor = HeartbeatMonitor(stale_after_seconds=60)
        job = _StubJob()
        job.heartbeat_at = None
        job.started_at = ago(600)
        assert monitor.is_stale(job)

    async def test_scan_ignores_jobs_that_are_not_running(self) -> None:
        monitor = HeartbeatMonitor(stale_after_seconds=1)
        job = _StubJob(status=JobStatus.QUEUED)
        job.heartbeat_at = ago(999)
        assert await monitor.scan([job]) == []

    async def test_scan_reports_the_dead_job_with_evidence(self) -> None:
        monitor = HeartbeatMonitor(stale_after_seconds=1)
        job = _StubJob(status=JobStatus.RUNNING)
        job.heartbeat_at = ago(999)
        job.started_at = ago(1000)
        job.worker_id = "host:1:0"
        stale = await monitor.scan([job])
        assert [item.job_id for item in stale] == [job.id]
        assert stale[0].worker_id == "host:1:0"
        assert stale[0].age_seconds > 1

    def test_forget_stops_tracking(self) -> None:
        monitor = HeartbeatMonitor()
        monitor.record(5, worker_id="w")
        assert monitor.tracked() == 1
        monitor.forget(5)
        assert monitor.tracked() == 0

    async def test_naive_timestamps_do_not_raise(self) -> None:
        """SQLite hands back naive datetimes; the comparison must stay total."""
        monitor = HeartbeatMonitor(stale_after_seconds=1)
        job = _StubJob(status=JobStatus.RUNNING)
        job.heartbeat_at = datetime.now(UTC) - timedelta(seconds=999)
        assert monitor.is_stale(job)


class TestJobManagerLifecycle:
    async def test_create_defaults_to_pending(self, manager: JobManager) -> None:
        job = await manager.create(JobType.PROCESS_BATCH, total_items=5)
        assert job.status is JobStatus.PENDING
        assert job.total_items == 5
        assert job.queued_at is None

    async def test_create_can_queue_immediately(self, manager: JobManager) -> None:
        job = await manager.create(JobType.PROCESS_BATCH, queue_immediately=True)
        assert job.status is JobStatus.QUEUED
        assert job.queued_at is not None

    async def test_create_emits_the_created_event(
        self, manager: JobManager, event_names
    ) -> None:
        await manager.create(JobType.PROCESS_BATCH)
        assert event_names() == [str(EventType.JOB_CREATED)]

    async def test_queue_immediately_emits_both_events(
        self, manager: JobManager, event_names
    ) -> None:
        await manager.create(JobType.PROCESS_BATCH, queue_immediately=True)
        assert event_names() == [
            str(EventType.JOB_CREATED),
            str(EventType.JOB_QUEUED),
        ]

    async def test_start_moves_pending_into_the_queue(
        self, manager: JobManager
    ) -> None:
        job = await manager.create(JobType.PROCESS_BATCH)
        assert (await manager.start(job.id)).status is JobStatus.QUEUED

    async def test_starting_a_cancelled_job_is_rejected(
        self, manager: JobManager
    ) -> None:
        job = await manager.create(JobType.PROCESS_BATCH)
        await manager.cancel(job.id)
        with pytest.raises(job_state.InvalidJobTransition):
            await manager.start(job.id)

    async def test_pause_then_resume_preserves_progress(
        self, manager: JobManager, session: AsyncSession
    ) -> None:
        """Resume must continue the job, not restart it from zero."""
        job = await manager.create(JobType.PROCESS_BATCH, total_items=10)
        await manager.start(job.id)
        await JobRepository(session).update_counters(
            job.id, processed=4, succeeded=4
        )
        await session.commit()
        assert (await manager.pause(job.id)).status is JobStatus.PAUSED
        resumed = await manager.resume(job.id)
        assert resumed.status is JobStatus.QUEUED
        assert resumed.processed_items == 4
        assert resumed.progress == 40

    async def test_cancelling_a_queued_job_is_immediate(
        self, manager: JobManager
    ) -> None:
        job = await manager.create(JobType.PROCESS_BATCH)
        assert (await manager.cancel(job.id)).status is JobStatus.CANCELLED

    async def test_pause_request_on_a_running_job_is_cooperative(
        self, manager: JobManager, session: AsyncSession
    ) -> None:
        """A running job only records the request; the worker stops it."""
        job = await manager.create(JobType.PROCESS_BATCH)
        await manager.start(job.id)
        assert await JobRepository(session).claim_next("w0") is not None
        paused = await manager.pause(job.id)
        assert paused.status is JobStatus.RUNNING
        await session.refresh(paused)
        assert paused.pause_requested is True

    async def test_cancel_request_on_a_running_job_is_cooperative(
        self, manager: JobManager, session: AsyncSession
    ) -> None:
        job = await manager.create(JobType.PROCESS_BATCH)
        await manager.start(job.id)
        await JobRepository(session).claim_next("w0")
        cancelled = await manager.cancel(job.id)
        assert cancelled.status is JobStatus.RUNNING
        await session.refresh(cancelled)
        assert cancelled.cancel_requested is True

    async def test_resume_clears_outstanding_requests(
        self, manager: JobManager, session: AsyncSession
    ) -> None:
        job = await manager.create(JobType.PROCESS_BATCH)
        await manager.start(job.id)
        await JobRepository(session).claim_next("w0")
        await manager.pause(job.id)
        await manager.resume(job.id)
        await session.refresh(job)
        assert job.pause_requested is False
        assert job.cancel_requested is False

    async def test_operations_on_a_missing_job_raise(self, manager: JobManager) -> None:
        for call in (manager.start, manager.pause, manager.resume, manager.cancel):
            with pytest.raises(JobNotFoundError):
                await call(999_999)

    async def test_describe_is_json_ready(self, manager: JobManager) -> None:
        job = await manager.create(JobType.PROCESS_BATCH, total_items=3)
        payload = manager.describe(job)
        assert payload["status"] == "pending"
        assert payload["total_items"] == 3
        assert isinstance(payload["created_at"], str)

    async def test_counts_group_by_status(self, manager: JobManager) -> None:
        await manager.create(JobType.PROCESS_BATCH)
        await manager.create(JobType.PROCESS_BATCH, queue_immediately=True)
        counts = await manager.counts()
        assert counts["pending"] == 1
        assert counts["queued"] == 1


class TestQueueManager:
    async def test_claim_returns_none_on_an_empty_queue(
        self, session: AsyncSession
    ) -> None:
        assert await QueueManager(session).claim("w0") is None

    async def test_claim_prefers_priority_over_age(
        self, manager: JobManager, session: AsyncSession
    ) -> None:
        first = await manager.create(JobType.PROCESS_BATCH, priority=100)
        second = await manager.create(JobType.PROCESS_BATCH, priority=10)
        await manager.start(first.id)
        await manager.start(second.id)
        claimed = await QueueManager(session).claim("w0")
        assert claimed is not None
        assert claimed.id == second.id

    async def test_claim_breaks_priority_ties_by_queued_age(
        self, manager: JobManager, session: AsyncSession
    ) -> None:
        first = await manager.create(JobType.PROCESS_BATCH)
        second = await manager.create(JobType.PROCESS_BATCH)
        await manager.start(first.id)
        await manager.start(second.id)
        claimed = await QueueManager(session).claim("w0")
        assert claimed is not None
        assert claimed.id == first.id

    async def test_a_second_worker_cannot_claim_the_same_job(
        self, manager: JobManager, session: AsyncSession
    ) -> None:
        job = await manager.create(JobType.PROCESS_BATCH)
        await manager.start(job.id)
        assert await QueueManager(session).claim("w0") is not None
        assert await QueueManager(session).claim("w1") is None

    async def test_depth_counts_jobs_waiting_for_a_worker(
        self, manager: JobManager, session: AsyncSession
    ) -> None:
        queue = QueueManager(session)
        assert await queue.depth() == 0
        job = await manager.create(JobType.PROCESS_BATCH)
        await manager.start(job.id)
        assert await queue.depth() == 1

    async def test_complete_finishes_the_job(
        self, manager: JobManager, session: AsyncSession
    ) -> None:
        job = await manager.create(JobType.PROCESS_BATCH)
        await manager.start(job.id)
        queue = QueueManager(session)
        claimed = await queue.claim("w0")
        assert claimed is not None
        finished = await queue.complete(claimed, result={"done": True})
        assert finished.status is JobStatus.COMPLETED
        assert finished.result == {"done": True}
        assert finished.finished_at is not None

    async def test_fail_records_the_error(
        self, manager: JobManager, session: AsyncSession
    ) -> None:
        job = await manager.create(JobType.PROCESS_BATCH)
        await manager.start(job.id)
        queue = QueueManager(session)
        claimed = await queue.claim("w0")
        assert claimed is not None
        failed = await queue.fail(claimed, RuntimeError("network cut"))
        assert failed.status is JobStatus.FAILED
        assert failed.error == "network cut"
        assert failed.error_type == "RuntimeError"

    async def test_heartbeat_only_lands_on_running_jobs(
        self, manager: JobManager, session: AsyncSession
    ) -> None:
        job = await manager.create(JobType.PROCESS_BATCH)
        await manager.start(job.id)
        queue = QueueManager(session)
        assert await queue.heartbeat(job.id) is False
        assert await queue.claim("w0") is not None
        assert await queue.heartbeat(job.id) is True

    async def test_wait_for_work_returns_false_on_timeout(
        self, session: AsyncSession
    ) -> None:
        queue = QueueManager(session)
        assert await queue.wait_for_work(0.02) is False
        await queue.close()

    async def test_notify_wakes_a_waiter(self, session: AsyncSession) -> None:
        queue = QueueManager(session)
        waiter = asyncio.ensure_future(queue.wait_for_work(5.0))
        await asyncio.sleep(0)
        queue.notify()
        assert await waiter is True
        await queue.close()


class TestWorkerPool:
    async def test_pool_runs_a_queued_job_to_completion(
        self, manager: JobManager
    ) -> None:
        job = await manager.create(JobType.PROCESS_BATCH)
        await manager.start(job.id)

        seen: list[int] = []

        async def handler(claimed: ProcessingJob, queue: QueueManager) -> dict[str, Any]:
            seen.append(claimed.id)
            return {"materials": 1}

        pool = WorkerPool(handlers={JobType.PROCESS_BATCH: handler}, concurrency=1)
        finished = await pool.run_once()
        assert finished is not None
        assert finished.id == job.id
        assert seen == [job.id]
        assert pool.completed_jobs == 1
        reread = await manager.require(job.id)
        assert reread.status is JobStatus.COMPLETED
        assert reread.result == {"materials": 1}

    async def test_a_raising_handler_records_a_failure(
        self, manager: JobManager
    ) -> None:
        job = await manager.create(JobType.PROCESS_BATCH)
        await manager.start(job.id)

        async def boom(claimed: ProcessingJob, queue: QueueManager):
            raise ValueError("handler blew up")

        pool = WorkerPool(handlers={JobType.PROCESS_BATCH: boom})
        finished = await pool.run_once()
        assert finished is not None
        assert finished.status is JobStatus.FAILED
        assert pool.failed_jobs == 1
        assert (await manager.require(job.id)).error == "handler blew up"

    async def test_pool_ignores_job_types_without_a_handler(
        self, manager: JobManager
    ) -> None:
        job = await manager.create(JobType.EXPORT_BATCH)
        await manager.start(job.id)

        async def handler(claimed: ProcessingJob, queue: QueueManager):
            return None

        pool = WorkerPool(handlers={JobType.PROCESS_BATCH: handler})
        assert await pool.run_once() is None
        assert (await manager.require(job.id)).status is JobStatus.QUEUED

    def test_reregistering_a_type_is_rejected(self) -> None:
        async def handler(claimed: ProcessingJob, queue: QueueManager):
            return None

        pool = WorkerPool(handlers={JobType.PROCESS_BATCH: handler})
        with pytest.raises(ValueError, match="already registered"):
            pool.register(JobType.PROCESS_BATCH, handler)

    async def test_start_requires_a_handler(self) -> None:
        with pytest.raises(RuntimeError, match="at least one"):
            await WorkerPool(concurrency=1).start()

    async def test_background_workers_drain_the_queue(
        self, manager: JobManager
    ) -> None:
        jobs = [await manager.create(JobType.PROCESS_BATCH) for _ in range(3)]
        for job in jobs:
            await manager.start(job.id)

        async def handler(claimed: ProcessingJob, queue: QueueManager):
            return {"id": claimed.id}

        pool = WorkerPool(
            handlers={JobType.PROCESS_BATCH: handler},
            concurrency=2,
            poll_interval=0.02,
        )
        await pool.start()
        for _ in range(100):
            pending = [
                job
                for job in jobs
                if (await manager.require(job.id)).status is not JobStatus.COMPLETED
            ]
            if not pending:
                break
            await asyncio.sleep(0.05)
        await pool.stop()
        assert pool.completed_jobs == 3
        assert pool.active_workers == 0
        for job in jobs:
            assert (await manager.require(job.id)).status is JobStatus.COMPLETED

    def test_worker_identity_mentions_host_pid_and_slot(self) -> None:
        identity = worker_identity(2)
        assert identity.endswith(":2")
        assert len(identity.split(":")) >= 3


@pytest.fixture
def make_recovery(
    session: AsyncSession, captured_events: list[tuple[Any, dict[str, Any]]]
):
    """A RecoveryManager whose events land in the capture list."""

    def _make(**kwargs: Any) -> RecoveryManager:
        return RecoveryManager(
            session,
            emit=lambda kind, ctx=None: captured_events.append((kind, ctx or {})),
            **kwargs,
        )

    return _make


class TestRecoveryManager:
    async def _stranded_running(
        self, manager: JobManager, session: AsyncSession, **kwargs: Any
    ) -> ProcessingJob:
        """A job whose worker died mid-run: claimed, aged, never finished."""
        job = await manager.create(JobType.PROCESS_BATCH, **kwargs)
        await manager.start(job.id)
        session.expunge_all()
        claimed = await JobRepository(session).claim_next("dead:1:0")
        assert claimed is not None
        claimed.heartbeat_at = ago(999)
        claimed.started_at = ago(1000)
        await session.commit()
        session.expunge_all()
        return job

    async def test_recover_all_requeues_a_stranded_running_job(
        self, manager: JobManager, session: AsyncSession, event_names, make_recovery
    ) -> None:
        job = await self._stranded_running(manager, session)
        outcome = await make_recovery().recover_all()
        assert outcome.retried == [job.id]
        assert (await manager.require(job.id)).status is JobStatus.QUEUED
        names = event_names()
        assert str(EventType.JOB_RECOVERING) in names
        assert str(EventType.JOB_RECOVERED) in names

    async def test_recovery_preserves_the_processed_counter(
        self, manager: JobManager, session: AsyncSession, make_recovery
    ) -> None:
        job = await manager.create(JobType.PROCESS_BATCH, total_items=10)
        await manager.start(job.id)
        await JobRepository(session).update_counters(
            job.id, processed=6, succeeded=5, failed=1
        )
        await JobRepository(session).claim_next("dead:1:0")
        claimed = await JobRepository(session).get(job.id)
        assert claimed is not None
        claimed.heartbeat_at = ago(999)
        await session.commit()
        await make_recovery().recover_all()
        reread = await manager.require(job.id)
        assert reread.status is JobStatus.QUEUED
        assert reread.processed_items == 6
        assert reread.succeeded_items == 5
        assert reread.failed_items == 1

    async def test_recovery_leaves_paused_jobs_paused(
        self, manager: JobManager, session: AsyncSession, make_recovery
    ) -> None:
        """Recovery must never un-pause work a human deliberately stopped."""
        job = await manager.create(JobType.PROCESS_BATCH)
        await manager.start(job.id)
        await manager.pause(job.id)
        outcome = await make_recovery().recover_all()
        assert outcome.left_paused == [job.id]
        assert (await manager.require(job.id)).status is JobStatus.PAUSED

    async def test_recovery_fails_a_job_whose_budget_is_gone(
        self, manager: JobManager, session: AsyncSession, make_recovery
    ) -> None:
        job = await self._stranded_running(manager, session)
        reread = await manager.require(job.id)
        reread.attempts = reread.max_attempts
        await session.commit()
        outcome = await make_recovery().recover_all()
        assert outcome.failed == [job.id]
        assert (await manager.require(job.id)).status is JobStatus.FAILED

    async def test_untouched_jobs_are_reported_as_such(
        self, manager: JobManager, session: AsyncSession, make_recovery
    ) -> None:
        pending = await manager.create(JobType.PROCESS_BATCH)
        queued = await manager.create(JobType.PROCESS_BATCH)
        await manager.start(queued.id)
        outcome = await make_recovery().recover_all()
        assert set(outcome.untouched) == {pending.id, queued.id}
        assert outcome.recovered_count == 0

    async def test_recover_stale_only_touches_expired_beats(
        self, manager: JobManager, session: AsyncSession, make_recovery
    ) -> None:
        old = await self._stranded_running(manager, session)
        fresh = await manager.create(JobType.PROCESS_BATCH)
        await manager.start(fresh.id)
        await JobRepository(session).claim_next("live:1:1")
        outcome = await make_recovery(
            monitor=HeartbeatMonitor(stale_after_seconds=120)
        ).recover_stale()
        assert outcome.retried == [old.id]
        assert (await manager.require(fresh.id)).status is JobStatus.RUNNING
        assert (await manager.require(old.id)).status is JobStatus.QUEUED

    async def test_a_full_crash_restart_recovers_a_mixed_queue(
        self, manager: JobManager, session: AsyncSession, make_recovery
    ) -> None:
        """The start-up scenario: every recoverable job plus a stayed-failed one.

        The genuinely ``FAILED`` job is deliberately *not* retried: it needs
        an operator's decision, so the sweep reports it as untouched.
        """
        running = await self._stranded_running(manager, session)

        retrying = await manager.create(
            JobType.PROCESS_BATCH, batch_id="recovery-retrying"
        )
        await manager.start(retrying.id)
        session.expunge_all()
        repo = JobRepository(session)
        repair = await repo.get(retrying.id)
        assert repair is not None
        assert repair.status is JobStatus.QUEUED
        claimed = await repo.claim_next("dead:2:0", batch_id=repair.batch_id)
        assert claimed is not None
        assert claimed.id == retrying.id
        await repo.transition(claimed, JobStatus.FAILED, error="x")
        await repo.transition(claimed, JobStatus.RETRYING, reason="retry")
        await session.commit()

        failed = await manager.create(
            JobType.PROCESS_BATCH, batch_id="recovery-failed"
        )
        await manager.start(failed.id)
        session.expunge_all()
        claimed_failed = await repo.claim_next(
            "dead:3:0", statuses=[JobStatus.QUEUED], batch_id=failed.batch_id
        )
        assert claimed_failed is not None
        assert claimed_failed.id == failed.id
        await repo.transition(claimed_failed, JobStatus.FAILED, error="x")
        await session.commit()

        outcome = await make_recovery().recover_all()
        assert set(outcome.retried) == {running.id, retrying.id}
        assert set(outcome.untouched) == {failed.id}
        assert (await manager.require(failed.id)).status is JobStatus.FAILED
        for job_id in (running.id, retrying.id):
            assert (await manager.require(job_id)).status is JobStatus.QUEUED


class TestSchedulerLifecycle:
    async def test_start_runs_recovery_then_pool(self, manager: JobManager) -> None:
        stranded = await TestRecoveryManager()._stranded_running(  # noqa: SLF001
            manager, manager._session  # noqa: SLF001
        )

        seen: list[int] = []

        async def handler(claimed: ProcessingJob, queue: QueueManager) -> None:
            seen.append(claimed.id)

        scheduler = Scheduler(sweep_interval=60.0)
        scheduler.register(JobType.PROCESS_BATCH, handler)
        outcome = await scheduler.start()
        try:
            assert outcome is not None
            assert stranded.id in outcome.retried
            for _ in range(100):
                if (await manager.require(stranded.id)).status is JobStatus.COMPLETED:
                    break
                await asyncio.sleep(0.05)
        finally:
            await scheduler.stop()
        assert seen == [stranded.id]

    async def test_start_is_idempotent(self) -> None:
        async def handler(claimed: ProcessingJob, queue: QueueManager) -> None:
            return None

        scheduler = Scheduler(sweep_interval=60.0)
        scheduler.register(JobType.PROCESS_BATCH, handler)
        await scheduler.start(recover=False)
        try:
            assert await scheduler.start(recover=False) is scheduler.last_recovery
            assert scheduler.pool.active_workers == scheduler.pool.concurrency
        finally:
            await scheduler.stop()

    async def test_stop_without_start_is_safe(self) -> None:
        await Scheduler().stop()

    async def test_sweep_once_recovers_a_silent_job(
        self, manager: JobManager, session: AsyncSession
    ) -> None:
        job = await TestRecoveryManager()._stranded_running(  # noqa: SLF001
            manager, session
        )
        scheduler = Scheduler(
            monitor=HeartbeatMonitor(stale_after_seconds=5),
            sweep_interval=60.0,
        )
        outcome = await scheduler.sweep_once()
        assert outcome.retried == [job.id]

    async def test_status_reports_the_subsystem(self) -> None:
        scheduler = Scheduler(sweep_interval=45.0)
        status = await scheduler.status()
        assert status["running"] is False
        assert status["sweep_interval_seconds"] == 45.0
        assert status["last_recovery"] is None
        assert "completed_jobs" in status

    async def test_scheduler_factory_uses_current_settings(self) -> None:
        from app.services.scheduler import scheduler as make_scheduler

        assert isinstance(make_scheduler(), Scheduler)







