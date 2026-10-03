"""Vision verification contract: does this image show the described product?

**Interface only (Phase 1).**  The model-backed verifier (a yes/no VLM call
that *verifies* and never generates) ships with the vision dependencies in a
later phase.  This module fixes the evidence shape now so the confidence
engine, the review queue and the reviewer-facing UI are already built against
the real contract.

Design rule encoded by the type: a verdict is **tri-state**.  ``True`` means
the model confirmed the match, ``False`` means it refuted it, ``None`` means
the model was unavailable and contributed *no evidence* - which the confidence
engine treats as an absent signal, distinct from a negative one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True)
class VisionVerdict:
    """Result of a vision model checking one image against one description."""

    #: ``True`` confirmed, ``False`` refuted, ``None`` model unavailable.
    verified: bool | None = None
    #: Short human-readable rationale from the model (or why it is ``None``).
    notes: str = ""
    #: Model identifier, e.g. ``gpt-4o-mini`` or ``local-vlm``.
    model: str = ""
    #: Confidence in ``[0, 1]`` when the model reports one.
    confidence: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def is_refuted(self) -> bool:
        """``True`` only for a definite negative - ``None`` is *not* a no."""
        return self.verified is False


class VisionUnavailableError(RuntimeError):
    """The vision model is declared but cannot run in this environment."""


class VisionValidator(ABC):
    """Contract every vision-verification implementation fulfils."""

    #: Stable identifier persisted in ``images.vision_model``.
    model_name: ClassVar[str] = ""

    @property
    @abstractmethod
    def available(self) -> bool:
        """``True`` when the model can be reached right now."""

    @abstractmethod
    async def verify(self, image_bytes: bytes, description: str) -> VisionVerdict:
        """Verify that ``image_bytes`` depicts the product in ``description``.

        Raises:
            VisionUnavailableError: when ``available`` is ``False``.
        """


__all__ = ["VisionUnavailableError", "VisionVerdict", "VisionValidator"]
