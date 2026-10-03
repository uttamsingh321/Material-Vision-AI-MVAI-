"""The canonical structured-event vocabulary and the publisher for it.

The in-process :class:`~app.services.events.EventBus` moves plain dicts.  This
module gives those dicts a *name* and a *shape*, so a frontend can switch on
``event["type"]`` and a test can assert that a pause emitted exactly one
``JOB_PAUSED``.

Design notes
------------
* **One envelope for every event.**  ``id``, ``type`` and ``occurred_at`` are
  always present; everything else is context.  Subscribers therefore never
  need a ``.get("type")`` guard.
* **Contexts are merged, never overwritten.**  A caller may pass
  ``job_id`` twice without silently losing the first value.
* **Pydantic models are deliberately not used here.**  The bus payload must be
  JSON-serialisable *and* cheap to build for every candidate image; the typed
  contracts belong in the API layer, not on the hot path.
* **Publishing never raises.**  An orchestration step must not fail because a
  websocket subscriber is slow, so a bus-level error is logged and swallowed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Final
from uuid import uuid4

from app.config.constants import WS_CHANNEL_DASHBOARD, WS_CHANNEL_JOBS
from app.config.logging import get_logger
from app.services.events import get_event_bus

logger = get_logger(__name__)


class EventType(StrEnum):
    """Every event name the platform emits.

    The names are the contract shared with the frontend, so they are
    UPPER_SNAKE_CASE and must not be renamed casually.  Values are what appears
    on the wire.
    """

    # --- job lifecycle ------------------------------------------------
    JOB_CREATED = "JOB_CREATED"
    JOB_QUEUED = "JOB_QUEUED"
    JOB_STARTED = "JOB_STARTED"
    JOB_PAUSED = "JOB_PAUSED"
    JOB_RESUMED = "JOB_RESUMED"
    JOB_CANCELLED = "JOB_CANCELLED"
    JOB_RETRIED = "JOB_RETRIED"
    JOB_RECOVERING = "JOB_RECOVERING"
    JOB_RECOVERED = "JOB_RECOVERED"
    JOB_STATUS_CHANGED = "JOB_STATUS_CHANGED"
    JOB_COMPLETED = "JOB_COMPLETED"
    JOB_FAILED = "JOB_FAILED"
    JOB_PROGRESS = "JOB_PROGRESS"
    JOB_HEARTBEAT = "JOB_HEARTBEAT"

    # --- search -------------------------------------------------------
    SEARCH_STARTED = "SEARCH_STARTED"
    PROVIDER_COMPLETED = "PROVIDER_COMPLETED"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    SEARCH_COMPLETED = "SEARCH_COMPLETED"

    # --- verification -------------------------------------------------
    IMAGE_DOWNLOADED = "IMAGE_DOWNLOADED"
    OCR_COMPLETED = "OCR_COMPLETED"
    BRAND_MATCHED = "BRAND_MATCHED"
    MODEL_MATCHED = "MODEL_MATCHED"
    VISION_COMPLETED = "VISION_COMPLETED"
    DUPLICATE_DETECTED = "DUPLICATE_DETECTED"
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
    CONFIDENCE_ASSIGNED = "CONFIDENCE_ASSIGNED"
    IMAGE_ACCEPTED = "IMAGE_ACCEPTED"
    IMAGE_REJECTED = "IMAGE_REJECTED"
    REVIEW_QUEUED = "REVIEW_QUEUED"

    # --- export -------------------------------------------------------
    EXPORT_STARTED = "EXPORT_STARTED"
    EXPORT_COMPLETED = "EXPORT_COMPLETED"

    # --- generic ------------------------------------------------------
    ERROR_OCCURRED = "ERROR_OCCURRED"


#: Events that describe overall job movement.  The dashboard subscribes to
#: this subset to rebuild its cards without parsing every candidate image.
JOB_LIFECYCLE_EVENTS: Final[frozenset[EventType]] = frozenset(
    {
        EventType.JOB_CREATED,
        EventType.JOB_QUEUED,
        EventType.JOB_STARTED,
        EventType.JOB_PAUSED,
        EventType.JOB_RESUMED,
        EventType.JOB_CANCELLED,
        EventType.JOB_RETRIED,
        EventType.JOB_RECOVERING,
        EventType.JOB_RECOVERED,
        EventType.JOB_STATUS_CHANGED,
        EventType.JOB_COMPLETED,
        EventType.JOB_FAILED,
        EventType.JOB_PROGRESS,
    }
)

#: Envelope keys guaranteed on every payload.
_ENVELOPE_KEYS: Final[frozenset[str]] = frozenset({"id", "type", "occurred_at"})


def new_envelope(
    event_type: EventType | str,
    context: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the standard event envelope for ``event_type``.

    ``context`` keys that collide with the envelope are rejected rather than
    silently dropped, because a caller that thinks it sent ``job_id`` must not
    have it overwritten by a framework default.
    """
    name = str(event_type)
    payload: dict[str, Any] = {
        "id": str(uuid4()),
        "type": name,
        "occurred_at": (now or datetime.now(timezone.utc)).isoformat(),
    }
    for key, value in (context or {}).items():
        if key in _ENVELOPE_KEYS:
            raise ValueError(f"{key!r} is reserved by the event envelope")
        payload[key] = value
    return payload


def emit(
    event_type: EventType | str,
    context: dict[str, Any] | None = None,
    *,
    channel: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Publish ``event_type`` and return the envelope that was sent.

    A job-lifecycle event is mirrored onto the dashboard channel so a client
    watching only the dashboard still sees job state changes.
    """
    payload = new_envelope(event_type, context, now=now)
    target = channel or WS_CHANNEL_JOBS
    bus = get_event_bus()
    try:
        bus.publish(target, payload)
        if event_type in JOB_LIFECYCLE_EVENTS and target == WS_CHANNEL_JOBS:
            bus.publish(WS_CHANNEL_DASHBOARD, payload)
    except Exception as exc:  # noqa: BLE001 - a bus fault must not fail a job
        logger.warning(
            "event.publish_failed", event_type=payload["type"], error=str(exc)
        )
    return payload


__all__ = [
    "EventType",
    "JOB_LIFECYCLE_EVENTS",
    "emit",
    "new_envelope",
]
