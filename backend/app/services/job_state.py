"""The job lifecycle as a pure state machine.

Every status change in the platform funnels through :func:`ensure_transition`
so "can a paused job be cancelled?" has exactly one answer, in one place, that
can be unit-tested without a database, an event loop or a worker.

Why a table and not scattered ``if`` statements
----------------------------------------------
``ProcessingJobManager`` and ``RecoveryManager`` both move jobs between states
for different reasons.  When they each carried their own conditions the two
paths drifted, and the drift only showed up after a crash - the worst possible
moment.  The transition table below is the single source of truth; callers ask
permission and get an exception naming both states when the answer is no.

The machine is deliberately *pure*: no I/O, no clock, no logging.  It is a
function of ``(current, target)``, which is what makes the concurrency and
recovery tests deterministic.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Mapping

from app.models.enums import JOB_ACTIVE_STATUSES, JobStatus


class InvalidJobTransition(ValueError):
    """A requested status change is not permitted by the lifecycle.

    Carries both statuses so an API layer can turn this into a 409 without
    re-deriving what was attempted.
    """

    def __init__(self, current: JobStatus, target: JobStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"cannot move a job from {current} to {target}")


#: Allowed target statuses keyed by current status.
#:
#: A few entries are deliberate and worth stating explicitly:
#:
#: * ``RUNNING -> QUEUED`` exists because a recovery sweep may hand a job back
#:   to the queue without first routing it through ``RETRYING``.
#: * ``RUNNING -> RECOVERING`` is how a heartbeat monitor flags a suspected
#:   stall; the job is not lost, it is quarantined until a sweep decides.
#: * ``PAUSED -> QUEUED`` is the resume path.  Resume is *not* a new job: the
#:   row keeps its ``processed_items`` counter so work is never redone.
#: * Terminal states are absent from every value set, so a finished job can
#:   never be resurrected by a late worker callback.
_TRANSITIONS: Final[Mapping[JobStatus, frozenset[JobStatus]]] = MappingProxyType(
    {
        JobStatus.PENDING: frozenset(
            {JobStatus.QUEUED, JobStatus.CANCELLED, JobStatus.FAILED}
        ),
        JobStatus.QUEUED: frozenset(
            {
                JobStatus.RUNNING,
                JobStatus.PAUSED,
                JobStatus.CANCELLED,
                JobStatus.FAILED,
                JobStatus.RECOVERING,
            }
        ),
        JobStatus.RUNNING: frozenset(
            {
                JobStatus.PAUSED,
                JobStatus.QUEUED,
                JobStatus.COMPLETED,
                JobStatus.SUCCEEDED,
                JobStatus.PARTIALLY_SUCCEEDED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
                JobStatus.RECOVERING,
                JobStatus.RETRYING,
            }
        ),
        JobStatus.PAUSED: frozenset(
            {JobStatus.QUEUED, JobStatus.CANCELLED, JobStatus.FAILED}
        ),
        JobStatus.RECOVERING: frozenset(
            {
                JobStatus.QUEUED,
                JobStatus.RUNNING,
                JobStatus.RETRYING,
                JobStatus.CANCELLED,
                JobStatus.FAILED,
            }
        ),
        JobStatus.RETRYING: frozenset(
            {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED}
        ),
        JobStatus.COMPLETED: frozenset(),
        JobStatus.SUCCEEDED: frozenset(),
        JobStatus.PARTIALLY_SUCCEEDED: frozenset(),
        JobStatus.FAILED: frozenset({JobStatus.RETRYING, JobStatus.QUEUED}),
        JobStatus.CANCELLED: frozenset(),
    }
)

#: Statuses that mean the job will never be worked on again.
#:
#: ``FAILED`` is deliberately **not** here: a failed job still has a retry path
#: (``FAILED -> RETRYING -> QUEUED``) as long as attempts remain.  Use
#: :func:`app.services.retry_manager.RetryManager` for that decision rather
#: than reading this set, because exhaustion also depends on ``attempts``.
TERMINAL_STATUSES: Final[frozenset[JobStatus]] = frozenset(
    status for status, targets in _TRANSITIONS.items() if not targets
)

#: Statuses a fresh worker may claim.
CLAIMABLE_STATUSES: Final[frozenset[JobStatus]] = frozenset(
    {JobStatus.QUEUED, JobStatus.RETRYING, JobStatus.RECOVERING}
)


def allowed_targets(current: JobStatus) -> frozenset[JobStatus]:
    """Statuses reachable from ``current``."""
    return _TRANSITIONS.get(current, frozenset())


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    """``True`` when moving ``current`` -> ``target`` is permitted."""
    return target in _TRANSITIONS.get(current, frozenset())


def ensure_transition(current: JobStatus, target: JobStatus) -> None:
    """Raise :class:`InvalidJobTransition` unless the move is allowed.

    A no-op move (``current == target``) is rejected deliberately: it signals a
    caller bug (double-start, double-cancel) that would otherwise hide behind a
    silent success.
    """
    if not can_transition(current, target):
        raise InvalidJobTransition(current, target)


def is_terminal(status: JobStatus) -> bool:
    """``True`` when no worker will ever pick the job up again."""
    return status in TERMINAL_STATUSES


def is_active(status: JobStatus) -> bool:
    """``True`` while the job is still eligible to be worked on."""
    return status in JOB_ACTIVE_STATUSES


__all__ = [
    "CLAIMABLE_STATUSES",
    "InvalidJobTransition",
    "TERMINAL_STATUSES",
    "allowed_targets",
    "can_transition",
    "ensure_transition",
    "is_active",
    "is_terminal",
]
