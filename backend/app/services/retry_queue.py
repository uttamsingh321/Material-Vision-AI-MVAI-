"""Configurable retry logic with exponential backoff and permanent failure.

Failures come in two flavours: *transient* (a provider timed out, the disk was
briefly locked) and *permanent* (the payload is malformed).  The retry queue
only concerns itself with the first kind - it decides **whether** an item may
be retried and **when**, while the caller decides what to do when the answer
becomes "no": move the item to its permanent failure state.

Backoff is ``base_delay * backoff_factor ** (attempt - 1)``, capped at
``max_delay_seconds``.  There is deliberately no random jitter: Phase 1 runs
single-process and tests must predict exact wake-up times.  Jitter can be
added behind :meth:`RetryPolicy.delay_for` when multi-worker deployments
arrive.

Time is tracked as aware UTC datetimes supplied by the caller (``now``); the
queue itself never sleeps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Knobs that decide how often and how late a retry may happen."""

    #: Retries allowed *after* the first attempt; ``0`` disables retrying.
    max_retries: int = 3
    #: Delay before the first retry (seconds).
    base_delay_seconds: float = 5.0
    #: Multiplier applied per consecutive failure.
    backoff_factor: float = 2.0
    #: Ceiling for any single delay, so backoff cannot explode.
    max_delay_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be >= 0")
        if self.backoff_factor < 1.0:
            raise ValueError("backoff_factor must be >= 1.0")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds must be >= 0")

    @classmethod
    def from_settings(cls) -> RetryPolicy:
        """Policy mirroring the job-retry settings (single source of truth)."""
        from app.config import get_settings

        settings = get_settings()
        return cls(
            max_retries=max(settings.job_max_attempts - 1, 0),
            base_delay_seconds=settings.job_retry_backoff_seconds,
        )

    def delay_for(self, attempt: int) -> float:
        """Seconds to wait after ``attempt`` consecutive failures (1-based).

        A non-positive attempt yields the base delay rather than raising -
        callers should not be able to crash a worker with arithmetic.
        """
        if attempt < 1:
            attempt = 1
        delay = self.base_delay_seconds * (self.backoff_factor ** (attempt - 1))
        return float(min(delay, self.max_delay_seconds))


@dataclass(slots=True)
class RetryEntry:
    """One item waiting for (or barred from) another chance."""

    key: str
    attempts: int = 0
    last_error: str | None = None
    #: When the next attempt becomes due; ``None`` once permanent.
    next_attempt_at: datetime | None = None
    #: ``True`` once retries are exhausted - the item is terminally failed.
    permanent: bool = False
    context: dict[str, Any] = field(default_factory=dict)


class RetryQueue:
    """Holds failed items and answers 'retry now / later / never'."""

    def __init__(self, policy: RetryPolicy | None = None) -> None:
        self.policy = policy or RetryPolicy()
        self._entries: dict[str, RetryEntry] = {}

    # ------------------------------------------------------------------
    # Recording failures
    # ------------------------------------------------------------------
    def record_failure(
        self,
        key: str,
        error: str,
        *,
        now: datetime | None = None,
        permanent: bool = False,
        context: dict[str, Any] | None = None,
    ) -> RetryEntry:
        """Register one more failure for ``key`` and schedule (or bar) a retry.

        Args:
            permanent: caller has decided no retry makes sense (bad input,
                cancelled job) - the entry jumps straight to its end state.
        """
        entry = self._entries.get(key) or RetryEntry(key=key, context={})
        entry.attempts += 1
        entry.last_error = error
        if context:
            entry.context.update(context)

        retries_exhausted = entry.attempts > self.policy.max_retries
        if permanent or retries_exhausted:
            entry.permanent = True
            entry.next_attempt_at = None
        else:
            current = now or datetime.now(timezone.utc)
            entry.next_attempt_at = current + timedelta(
                seconds=self.policy.delay_for(entry.attempts)
            )
        self._entries[key] = entry
        return entry

    def record_success(self, key: str) -> None:
        """Forget a key after it finally succeeded."""
        self._entries.pop(key, None)

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------
    def should_retry(self, key: str, *, now: datetime | None = None) -> bool:
        """``True`` when ``key`` is present, not permanent, and due."""
        entry = self._entries.get(key)
        if entry is None or entry.permanent or entry.next_attempt_at is None:
            return False
        current = now or datetime.now(timezone.utc)
        return entry.next_attempt_at <= current

    def is_permanent_failure(self, key: str) -> bool:
        """``True`` when ``key`` has exhausted its retries (or was forced)."""
        entry = self._entries.get(key)
        return bool(entry and entry.permanent)

    def get(self, key: str) -> RetryEntry | None:
        return self._entries.get(key)

    def due_keys(self, *, now: datetime | None = None) -> list[str]:
        """Every key that is retryable right now, in insertion order."""
        current = now or datetime.now(timezone.utc)
        return [
            key
            for key, entry in self._entries.items()
            if not entry.permanent
            and entry.next_attempt_at is not None
            and entry.next_attempt_at <= current
        ]

    def entries(self) -> list[RetryEntry]:
        """All tracked entries, in insertion order."""
        return list(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    def clear(self) -> None:
        self._entries.clear()

    @classmethod
    def from_entries(
        cls, policy: RetryPolicy, entries: Iterable[RetryEntry]
    ) -> RetryQueue:
        """Rebuild a queue, e.g. after recovering state from the database."""
        queue = cls(policy)
        for entry in entries:
            queue._entries[entry.key] = entry
        return queue


__all__ = ["RetryEntry", "RetryPolicy", "RetryQueue"]

