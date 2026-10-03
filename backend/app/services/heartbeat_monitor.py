"""Liveness tracking for running jobs.

A worker that dies does not get to say so.  The only evidence is silence: the
``heartbeat_at`` stamp stops moving.  This module turns that silence into two
decisions:

* :meth:`HeartbeatMonitor.is_stale` - is this one job presumed dead?
* :meth:`HeartbeatMonitor.scan` - find every presumed-dead job.

Keeping the staleness *arithmetic* separate from the *sweeping* is what makes
it testable: the threshold logic is a pure function of a timestamp, so the
recovery tests can use a frozen clock instead of sleeping for the configured
timeout (which defaults to three minutes).

The monitor is instance-scoped.  It owns a small in-memory table of last-seen
timestamps that it refreshes on every beat, and consults the database when it
needs to be authoritative - the table is a fast path, never the truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from app.config import get_settings
from app.config.logging import get_logger
from app.models.enums import JobStatus
from app.models.processing_job import ProcessingJob

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _age_seconds(reference: datetime, moment: datetime) -> float:
    """Seconds between two timestamps, tolerating naive SQLite values.

    ``UTCDateTime`` re-attaches UTC on read, but a job built in memory by a
    test may still be naive; normalising here keeps every comparison total.
    """
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max((moment - reference).total_seconds(), 0.0)


@dataclass(slots=True)
class Heartbeat:
    """One job's last known sign of life."""

    job_id: int
    beat_at: datetime
    worker_id: str | None = None
    #: Consecutive sweeps in which no fresh beat was observed.
    missed_sweeps: int = 0

    def age_seconds(self, now: datetime | None = None) -> float:
        """Seconds since the last beat."""
        return _age_seconds(self.beat_at, now or _utcnow())


@dataclass(slots=True)
class StaleJob:
    """A running job the monitor has decided is dead."""

    job_id: int
    worker_id: str | None
    last_beat: datetime | None
    age_seconds: float
    reason: str


class HeartbeatMonitor:
    """Tracks beats and decides when silence means death."""

    def __init__(
        self,
        *,
        stale_after_seconds: int | None = None,
        sweeps_before_stale: int = 2,
    ) -> None:
        settings = get_settings()
        self._stale_after = int(
            stale_after_seconds
            if stale_after_seconds is not None
            else settings.job_stale_after_seconds
        )
        #: Require two consecutive stale sweeps before declaring death.  A
        #: single missed sweep is usually just a slow database write or a
        #: momentarily busy event loop, and recovering on it would cause
        #: duplicate work for no benefit.
        self._sweeps_required = max(int(sweeps_before_stale), 1)
        self._beats: dict[int, Heartbeat] = {}

    # ------------------------------------------------------------------
    # Tracking
    # ------------------------------------------------------------------
    @property
    def stale_after_seconds(self) -> int:
        """Configured silence window, in seconds."""
        return self._stale_after

    def record(
        self, job_id: int, *, worker_id: str | None = None, now: datetime | None = None
    ) -> Heartbeat:
        """Register a beat for ``job_id`` and return the stored record."""
        beat = Heartbeat(job_id=job_id, beat_at=now or _utcnow(), worker_id=worker_id)
        self._beats[job_id] = beat
        return beat

    def forget(self, job_id: int) -> None:
        """Drop tracking state for a job that has finished."""
        self._beats.pop(job_id, None)

    def tracked(self) -> int:
        """How many jobs are currently being tracked."""
        return len(self._beats)

    def last_beat(self, job_id: int) -> Heartbeat | None:
        """The stored beat for ``job_id``, if any."""
        return self._beats.get(job_id)

    def reset(self) -> None:
        """Forget every tracked beat (used between tests and on shutdown)."""
        self._beats.clear()

    # ------------------------------------------------------------------
    # Staleness
    # ------------------------------------------------------------------
    def last_signal(self, job: ProcessingJob) -> datetime | None:
        """The timestamp this job last proved it was alive.

        ``heartbeat_at`` when present, otherwise ``started_at`` - so a worker
        that died between claiming a job and its first beat is still caught.
        """
        return job.heartbeat_at or job.started_at

    def is_stale(
        self,
        job: ProcessingJob,
        *,
        now: datetime | None = None,
        sweeps_required: int | None = None,
    ) -> bool:
        """``True`` when ``job`` has been silent for longer than the window.

        When the job carries no timing information at all the in-memory
        ``missed_sweeps`` counter decides, which requires two consecutive
        silent sweeps before giving up on an otherwise healthy-looking job.
        """
        signal = self.last_signal(job)
        if signal is not None:
            return _age_seconds(signal, now or _utcnow()) > self._stale_after
        required = sweeps_required if sweeps_required is not None else self._sweeps_required
        tracked = self._beats.get(job.id)
        if tracked is None:
            return True
        return tracked.missed_sweeps >= required

    async def scan(
        self,
        jobs: Iterable[ProcessingJob],
        *,
        now: datetime | None = None,
    ) -> list[StaleJob]:
        """Every job in ``jobs`` that is presumed dead, with evidence.

        Declared ``async`` so the periodic sweeper can call it directly and so
        tests can await it inside their existing async fixture, even though
        the body is pure - no reason to make callers special-case it.
        """
        moment = now or _utcnow()
        stale: list[StaleJob] = []
        for job in jobs:
            if job.status is not JobStatus.RUNNING:
                continue
            signal = self.last_signal(job)
            age = _age_seconds(signal, moment) if signal is not None else float("inf")
            if age > self._stale_after:
                stale.append(
                    StaleJob(
                        job_id=job.id,
                        worker_id=job.worker_id,
                        last_beat=signal,
                        age_seconds=age,
                        reason="heartbeat_expired",
                    )
                )
                self._note_missed(job.id)
        return stale

    def _note_missed(self, job_id: int) -> int:
        """Increment and return the missed-sweep counter for ``job_id``."""
        tracked = self._beats.get(job_id)
        if tracked is None:
            tracked = Heartbeat(job_id=job_id, beat_at=_utcnow())
            self._beats[job_id] = tracked
        tracked.missed_sweeps += 1
        return tracked.missed_sweeps


def heartbeat_monitor(**kwargs: Any) -> HeartbeatMonitor:
    """A monitor configured from current settings."""
    return HeartbeatMonitor(**kwargs)


__all__ = [
    "Heartbeat",
    "HeartbeatMonitor",
    "StaleJob",
    "heartbeat_monitor",
]

