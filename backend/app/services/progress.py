"""Progress tracking: one snapshot shape for the API, the UI and the logs.

The numbers a reviewer cares about during a run - overall percentage, which
material and provider are being worked on right now, how many succeeded /
need review / failed, when it will finish, and how fast it is going - are
computed here in one place so the WebSocket payload, the polling endpoint and
the job row can never disagree.

Two layers of state exist:

* **Durable** - the ``ProcessingJob`` counters (``processed_items`` and
  friends), which survive a crash.
* **Live** - :class:`ProgressTracker`, an in-memory per-job scratchpad holding
  "what is happening this second" (current material/provider, start time).
  It is lost on restart, which is fine: after recovery the durable counters
  remain correct and the live fields simply read ``None``.

All arithmetic is total: an empty or freshly-created job reports 0% progress
and a ``None`` ETA rather than dividing by zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.processing_job import ProcessingJob


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    """Everything the UI needs to render one job's progress bar."""

    job_id: int
    job_type: str
    status: str
    #: Whole percent in ``[0, 100]``.
    overall: int
    total: int
    processed: int
    succeeded: int
    failed: int
    skipped: int
    #: Materials whose disposition is "a human must decide".
    review: int
    current_material: str | None = None
    current_provider: str | None = None
    #: Seconds since the job first started, ``None`` before start.
    processing_seconds: float | None = None
    #: Estimated seconds until completion, ``None`` while unknown.
    eta_seconds: float | None = None
    #: Items completed per second so far, ``None`` before the first item.
    throughput: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready mapping for API and WebSocket payloads."""
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "overall": self.overall,
            "total": self.total,
            "processed": self.processed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "review": self.review,
            "current_material": self.current_material,
            "current_provider": self.current_provider,
            "processing_seconds": self.processing_seconds,
            "eta_seconds": self.eta_seconds,
            "throughput": self.throughput,
        }


def percent(processed: int, total: int) -> int:
    """Whole-percent completion, clamped to ``[0, 100]``; 0 when empty."""
    if total <= 0:
        return 0
    return max(0, min(100, round(processed * 100 / total)))


def estimate_eta(processed: int, total: int, elapsed_seconds: float) -> float | None:
    """Seconds remaining, or ``None`` while no estimate is possible.

    Linear extrapolation of the observed rate.  Before the first item
    completes there is no rate, so ``None`` is honest.
    """
    remaining = total - processed
    if remaining <= 0 or elapsed_seconds <= 0 or processed <= 0:
        return None
    rate = processed / elapsed_seconds
    if rate <= 0:  # pragma: no cover - guarded by processed > 0
        return None
    return round(remaining / rate, 3)


def throughput(processed: int, elapsed_seconds: float) -> float | None:
    """Items per second, or ``None`` before any time has passed."""
    if elapsed_seconds <= 0 or processed <= 0:
        return None


@dataclass(slots=True)
class ProgressTracker:
    """Live per-job scratchpad: current work item plus timing anchors."""

    job_id: int
    started_at: datetime | None = None
    current_material: str | None = None
    current_provider: str | None = None
    #: Rolling per-material durations (seconds) for the current run only.
    _samples: list[float] = field(default_factory=list, repr=False)

    def start(self, now: datetime | None = None) -> None:
        """Anchor the clock; idempotent so re-resume keeps the first start."""
        if self.started_at is None:
            self.started_at = now or datetime.now(timezone.utc)

    def set_current(self, material: str | None, provider: str | None = None) -> None:
        """Record what is being processed right now."""
        self.current_material = material
        self.current_provider = provider

    def record_sample(self, seconds: float) -> None:
        """Keep a per-item duration (bounded) for local rate estimation."""
        self._samples.append(seconds)
        if len(self._samples) > 512:
            del self._samples[:256]

    def elapsed(self, now: datetime | None = None) -> float | None:
        """Seconds since :meth:`start`, ``None`` if never started."""
        if self.started_at is None:
            return None
        current = now or datetime.now(timezone.utc)
        if self.started_at.tzinfo is None:  # pragma: no cover - defensive
            anchor = self.started_at.replace(tzinfo=timezone.utc)
        else:
            anchor = self.started_at
        return max((current - anchor).total_seconds(), 0.0)

    def snapshot(
        self,
        job: ProcessingJob,
        *,
        review_count: int = 0,
        now: datetime | None = None,
    ) -> ProgressSnapshot:
        """Merge durable job counters with this tracker's live fields."""
        elapsed = self.elapsed(now) if self.started_at is not None else None
        # Fall back to the job's own timestamps when this process has no live
        # anchor (e.g. the page was reloaded after a restart).
        if elapsed is None and job.started_at is not None:
            anchor = (
                job.started_at
                if job.started_at.tzinfo
                else job.started_at.replace(tzinfo=timezone.utc)
            )
            end = job.finished_at or (now or datetime.now(timezone.utc))
            end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
            elapsed = max((end - anchor).total_seconds(), 0.0)

        return ProgressSnapshot(
            job_id=job.id,
            job_type=str(job.job_type),
            status=str(job.status),
            overall=percent(job.processed_items, job.total_items),
            total=job.total_items,
            processed=job.processed_items,
            succeeded=job.succeeded_items,
            failed=job.failed_items,
            skipped=job.skipped_items,
            review=review_count,
            current_material=self.current_material,
            current_provider=self.current_provider,
            processing_seconds=round(elapsed, 3) if elapsed is not None else None,
            eta_seconds=estimate_eta(job.processed_items, job.total_items, elapsed or 0.0),
            throughput=throughput(job.processed_items, elapsed or 0.0),
        )


__all__ = [
    "ProgressSnapshot",
    "ProgressTracker",
    "estimate_eta",
    "percent",
    "throughput",
]

