"""OCR contract: extract text rendered inside an image.

**Interface only (Phase 1).**  No engine - Tesseract, EasyOCR or otherwise -
is bundled yet, and no dependency for one is installed.  What this module
fixes *now* is the shape every future implementation must satisfy, so that
plugging an engine in later changes nothing above this boundary: the
verification pipeline already speaks ``OcrReader`` + ``OcrResult``.

An implementation is responsible for declaring :attr:`OcrReader.engine_name`
and :attr:`OcrReader.available`; callers check ``available`` before ``read``
and treat an unavailable engine as *absent evidence*, never as a failure -
the confidence engine already models missing signals correctly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True)
class OcrResult:
    """Text recovered from an image, plus how much to trust it."""

    #: Full text as read, normalised whitespace but otherwise unedited.
    text: str = ""
    #: Engine-reported confidence in ``[0, 1]``; ``None`` when unsupported.
    confidence: float | None = None
    #: Identifier of the engine that produced this result, e.g. ``tesseract``.
    engine: str = ""
    #: Per-line readings, when the engine exposes them (useful for review).
    lines: tuple[str, ...] = ()
    #: Structured extras the engine reported (bbox data, language, ...).
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def tokens(self) -> list[str]:
        """Whitespace-split tokens, lower-cased - the similarity input."""
        return self.text.lower().split()

    @property
    def is_empty(self) -> bool:
        """``True`` when the engine read nothing usable from the image."""
        return not self.text.strip()


class OcrUnavailableError(RuntimeError):
    """The engine is declared but cannot run in this environment."""


class OcrReader(ABC):
    """Contract every OCR implementation fulfils."""

    #: Stable identifier persisted in ``images.ocr_engine``.
    engine_name: ClassVar[str] = ""

    @property
    @abstractmethod
    def available(self) -> bool:
        """``True`` when the engine can run right now (deps present, ...)."""

    @abstractmethod
    async def read(self, image_bytes: bytes, *, mime_type: str | None = None) -> OcrResult:
        """Extract text from ``image_bytes``.

        Raises:
            OcrUnavailableError: when ``available`` is ``False``.
        """


__all__ = ["OcrReader", "OcrResult", "OcrUnavailableError"]
