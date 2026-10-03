"""Background removal contract: isolate the product from its backdrop.

**Interface only (Phase 1).**  The segmentation models (rembg / U2-Net and
friends) arrive with the imaging stack in a later phase.  The contract is
fixed now because downstream expectations are already written: callers want
PNG-with-alpha output, a confidence estimate of the cut, and a hard rule that
an unavailable engine must never silently pass the original image through as
if it had been cleaned - that would launder unprocessed bytes into a step
which assumes a transparent background.

Accordingly :class:`BackgroundRemover.remove` raises when the engine is
unavailable instead of returning the input untouched.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True)
class BackgroundResult:
    """Outcome of stripping the background from one image."""

    #: Processed bytes - PNG with an alpha channel when ``changed`` is True.
    image_bytes: bytes
    #: ``True`` when a background was actually removed.
    changed: bool = False
    #: Quality estimate in ``[0, 1]`` for the cut, when the model gives one.
    confidence: float | None = None
    #: Identifier of the engine that produced the result.
    engine: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


class BackgroundRemovalUnavailableError(RuntimeError):
    """The engine is declared but cannot run in this environment."""


class BackgroundRemover(ABC):
    """Contract every background-removal implementation fulfils."""

    #: Stable identifier recorded in evidence payloads / reports.
    engine_name: ClassVar[str] = ""

    @property
    @abstractmethod
    def available(self) -> bool:
        """``True`` when the engine can run right now (deps present, ...)."""

    @abstractmethod
    async def remove(self, image_bytes: bytes) -> BackgroundResult:
        """Return ``image_bytes`` with its background made transparent.

        Raises:
            BackgroundRemovalUnavailableError: when ``available`` is
                ``False``.  The input is never passed through unchanged.
        """


__all__ = [
    "BackgroundRemovalUnavailableError",
    "BackgroundRemover",
    "BackgroundResult",
]
