"""Image similarity contract: decide whether two images show the same thing.

**Interface only (Phase 1).**  Perceptual hashing (the cheap, dependency-free
first tier) already lives in :mod:`app.utils.hashing`; this module fixes the
contract for the *heavier* comparisons - embedding distance, structural
similarity - that arrive with the imaging stack in a later phase.

The pipeline consumes :class:`SimilarityResult` and a numeric ``score`` in
``[0, 1]`` where ``1.0`` means "indistinguishable", so swapping the algorithm
later cannot change what the thresholds mean.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True)
class SimilarityResult:
    """Outcome of comparing two images."""

    #: Similarity in ``[0, 1]``: ``1.0`` identical, ``0.0`` unrelated.
    score: float
    #: Identifier of the algorithm that produced the score, e.g. ``phash``.
    method: str = ""
    #: ``True`` when the score met the caller's accept threshold.
    is_match: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be within [0, 1], got {self.score}")


class SimilarityUnavailableError(RuntimeError):
    """The comparison method is declared but cannot run here."""


class ImageSimilarity(ABC):
    """Contract every similarity implementation fulfils."""

    #: Stable identifier persisted in evidence payloads / reports.
    method_name: ClassVar[str] = ""

    @property
    @abstractmethod
    def available(self) -> bool:
        """``True`` when the method can run right now (deps present, ...)."""

    @abstractmethod
    async def compare(self, left: bytes, right: bytes) -> SimilarityResult:
        """Score how alike ``left`` and ``right`` are.

        Raises:
            SimilarityUnavailableError: when ``available`` is ``False``.
        """


__all__ = ["ImageSimilarity", "SimilarityResult", "SimilarityUnavailableError"]
