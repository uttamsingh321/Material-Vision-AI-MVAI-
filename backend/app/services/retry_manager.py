"""Retry policy for background jobs: one decision, reused everywhere.

Three places need to answer "may this job run again?":

* a worker whose handler raised a transient error,
* the operator pressing **Retry**,
* the recovery sweep after a crash.

When each answered separately they drifted - most dangerously, an operator
retry could resurrect a job that had already exhausted its attempts, producing
an infinite crash loop that looked like "the job is stuck".

This module is the single arbiter.  It is deliberately **pure**: given a
``ProcessingJob``-shaped object and a clock it returns a decision, so the
policy can be exhaustively unit-tested without a database.

The distinction it encodes
--------------------------
A failure is retryable only while ``attempts < max_attempts``.  A job that has
used its budget is *permanently* failed regardless of who is asking - the
operator gets a clear error rather than a job that dies 5,000 more times.
Cancellation is separate and always wins: a cancelled job is never retried,
because the operator said to stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Final, Protocol

from app.config import get_settings
from app.config.logging import get_logger
from app.models.enums import JobStatus
from app.services.retry_queue import RetryPolicy

logger = get_logger(__name__)


class JobLike(Protocol):
    """The slice of :class:`ProcessingJob` this module needs.

    Declared as a protocol so the policy can be tested against a bare stub
    instead of a live ORM row.
    """

    id: int
    status: JobStatus
    attempts: int
    max_attempts: int
    cancel_requested: bool


class PermanentJobError(RuntimeError):
    """Raised when a retry is refused because the job's budget is spent."""


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """The outcome of asking whether a failed job may run again."""

    #: ``True`` when the job is eligible for another attempt.
    retry: bool
    #: Why not, when ``retry`` is ``False`` - surfaced to the API.
    reason: str
    #: When the next attempt may start.  ``None`` when not retryable.
    next_attempt_at: datetime | None = None

    def __bool__(self) -> bool:
        return self.retry


#: Reasons returned in :attr:`RetryDecision.reason`.
REASON_OK: Final[str] = "attempts_remain"
REASON_CANCELLED: Final[str] = "job_was_cancelled"
REASON_EXHAUSTED: Final[str] = "attempts_exhausted"
REASON_NOT_FAILED: Final[str] = "job_is_not_failed"
REASON_MANUAL: Final[str] = "operator_requested"


class RetryManager:
    """Decides whether a failed job gets another attempt, and when."""

    def __init__(self, policy: RetryPolicy | None = None) -> None:
        settings = get_settings()
        self._base_delay = float(
            policy.base_delay_seconds if policy else settings.job_retry_backoff_seconds
        )
        self._factor = policy.backoff_factor if policy else 2.0
        self._max_delay = policy.max_delay_seconds if policy else 300.0

    # ------------------------------------------------------------------
    def attempts_remaining(self, job: JobLike) -> int:
        """How many further attempts ``job`` is allowed."""
        return max(int(job.max_attempts) - int(job.attempts), 0)

    def delay_for(self, attempt: int) -> float:
        """Backoff before the next attempt, given ``attempt`` failures so far."""
        exponent = max(int(attempt) - 1, 0)
        return float(min(self._base_delay * (self._factor**exponent), self._max_delay))

    def evaluate(
        self,
        job: JobLike,
        *,
        now: datetime | None = None,
        force: bool = False,
    ) -> RetryDecision:
        """Decide whether ``job`` may be retried.

        Args:
            force: set by an explicit operator retry.  It bypasses the
                "must currently be failed" check so an operator can also
                re-run a job that a crash left in ``RECOVERING`` - but it
                deliberately does **not** bypass the attempt budget.
        """
        if job.cancel_requested or job.status is JobStatus.CANCELLED:
            return RetryDecision(False, REASON_CANCELLED)

        if not force and job.status is not JobStatus.FAILED:
            return RetryDecision(False, REASON_NOT_FAILED)

        if self.attempts_remaining(job) <= 0:
            return RetryDecision(False, REASON_EXHAUSTED)

        moment = now or datetime.now(timezone.utc)
        return RetryDecision(
            retry=True,
            reason=REASON_MANUAL if force else REASON_OK,
            next_attempt_at=moment + timedelta(seconds=self.delay_for(job.attempts)),
        )

    def ensure_retryable(
        self, job: JobLike, *, now: datetime | None = None, force: bool = False
    ) -> RetryDecision:
        """Like :meth:`evaluate` but raises instead of returning ``retry=False``.

        Used by the API so a refusal becomes a 409 with a useful message,
        rather than a silent no-op that looks like success.
        """
        decision = self.evaluate(job, now=now, force=force)
        if not decision.retry:
            raise PermanentJobError(
                f"job {job.id} cannot be retried: {decision.reason}"
            )
        return decision

    def reset(self, job: Any) -> None:
        """Clear the attempt counter so a fresh manual run starts from zero.

        Used only by the explicit "reset and retry" operator action, and kept
        separate from :meth:`evaluate` so an ordinary retry can never grant
        itself extra attempts.
        """
        job.attempts = 0
        job.error = None
        job.error_type = None
        job.finished_at = None
        logger.info("job.attempts_reset", job_id=getattr(job, "id", None))


def retry_manager() -> RetryManager:
    """A retry manager configured from current settings."""
    return RetryManager()


__all__ = [
    "REASON_CANCELLED",
    "REASON_EXHAUSTED",
    "REASON_MANUAL",
    "REASON_NOT_FAILED",
    "REASON_OK",
    "JobLike",
    "PermanentJobError",
    "RetryDecision",
    "RetryManager",
    "retry_manager",
]

