"""In-process publish/subscribe bus for live-progress fan-out.

A single process runs the API, the worker and the WebSocket endpoints, so a
tiny asyncio fan-out is all that is needed to stream job progress and log
lines to connected clients - no Redis, no external broker (ADR-004: local
queue backend for Phase 1).

Semantics:

* Channels are plain strings; the canonical names live in
  :mod:`app.config.constants` (``jobs``, ``logs``, ``dashboard``).
* Each subscriber owns its own bounded :class:`asyncio.Queue`.  A slow client
  that stops reading must never stall the pipeline, so publishes are
  *fire-and-forget*: when a queue is full the oldest event is dropped and the
  newest is delivered - the UI only ever cares about the latest state.
* The bus is deliberately process-local.  Moving to a clustered topology
  means swapping this module for a Redis pub/sub implementation behind the
  same two-method interface.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

#: Per-subscriber queue depth before old events start being dropped.
QUEUE_MAXSIZE = 256


class EventBus:
    """Fan-out of JSON-serialisable events to per-subscriber queues."""

    def __init__(self, *, maxsize: int = QUEUE_MAXSIZE) -> None:
        self._maxsize = maxsize
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscribe(self, channel: str) -> asyncio.Queue[dict[str, Any]]:
        """Register a new subscriber queue for ``channel``."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers[channel].add(queue)
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscriber queue; safe to call twice."""
        self._subscribers[channel].discard(queue)
        if not self._subscribers[channel]:
            self._subscribers.pop(channel, None)

    def subscriber_count(self, channel: str) -> int:
        """How many queues are currently listening on ``channel``."""
        return len(self._subscribers.get(channel, ()))

    def publish(self, channel: str, payload: dict[str, Any]) -> int:
        """Deliver ``payload`` to every subscriber of ``channel``.

        Returns the number of queues that received the event.  A full queue
        drops its oldest entry to make room - see the module docstring.
        """
        delivered = 0
        for queue in tuple(self._subscribers.get(channel, ())):
            while queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover - raced consumer
                    break
            try:
                queue.put_nowait(payload)
                delivered += 1
            except asyncio.QueueFull:  # pragma: no cover - raced consumer
                continue
        return delivered

    def reset(self) -> None:
        """Drop every subscription (used between tests)."""
        self._subscribers.clear()


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Process-wide bus singleton."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def reset_event_bus() -> None:
    """Drop the singleton so the next access rebuilds it (used by tests)."""
    global _bus
    _bus = None


__all__ = ["EventBus", "get_event_bus", "reset_event_bus"]
