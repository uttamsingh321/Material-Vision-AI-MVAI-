"""Downloaded candidate images and their verification evidence.

The class is named :class:`MaterialImage` rather than ``Image`` to avoid
shadowing ``PIL.Image`` in modules that import both.

A row exists from the moment a candidate is fetched and carries the *entire*
evidence trail - hashes, OCR text, vision verdict, score - so a reviewer can
answer "why was this accepted?" without re-running anything.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UTCDateTime
from app.models.enums import ImageStatus, RejectionReason
from app.models.types import enum_column

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.confidence_score import ConfidenceScore
    from app.models.material import Material
    from app.models.review_queue import ReviewQueueItem
    from app.models.search_result import SearchResult


class MaterialImage(Base, TimestampMixin):
    """A concrete image file associated with a material."""

    __tablename__ = "images"
    __table_args__ = (
        Index("ix_images_material_status", "material_id", "status"),
        Index("ix_images_sha256", "sha256"),
        Index("ix_images_phash", "phash"),
        Index("ix_images_source_url_hash", "source_url_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, index=True
    )
    search_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("search_results.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # --- storage ---------------------------------------------------------
    #: Name of the file as persisted (content-hash based, deduplicated).
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Name advertised by the remote server, kept for traceability.
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_backend: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    #: Path relative to the storage root - never an absolute filesystem path, so
    #: a bucket or volume can be relocated without rewriting rows.
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    #: Category-relative location inside ``image-library/`` once accepted.
    library_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extension: Mapped[str | None] = mapped_column(String(10), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- identity / deduplication ---------------------------------------
    #: SHA-256 of the raw bytes - exact-duplicate detection.
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Perceptual hash (hex) - near-duplicate detection.
    phash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: SHA-256 of the source URL, so the same URL is never fetched twice.
    source_url_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    source_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_page_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # --- disposition -----------------------------------------------------
    status: Mapped[ImageStatus] = mapped_column(
        enum_column(ImageStatus, "image_status"),
        nullable=False,
        default=ImageStatus.CANDIDATE,
        index=True,
    )
    rejection_reason: Mapped[RejectionReason | None] = mapped_column(
        enum_column(RejectionReason, "rejection_reason"), nullable=True
    )
    rejection_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_thumbnail: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_watermark: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- evidence: OCR ---------------------------------------------------
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr_engine: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ocr_tokens: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # --- evidence: vision verification -----------------------------------
    vision_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: The model's yes/no rationale.  The model *verifies*; it never generates.
    vision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    vision_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    vision_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    #: Winning score from the ``confidence_scores`` table.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Denormalised flag so image-library queries are index-only.
    is_accepted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )

    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # --- relationships ---------------------------------------------------
    material: Mapped[Material] = relationship(back_populates="images")
    search_result: Mapped[SearchResult | None] = relationship(back_populates="images")
    #: No ORM cascade here: deleting an image must remove its scores and review
    #: items, and the ``ON DELETE CASCADE`` foreign keys already do that at the
    #: database level (SQLite runs with ``PRAGMA foreign_keys=ON``).
    confidence_scores: Mapped[list[ConfidenceScore]] = relationship(
        back_populates="image", lazy="noload"
    )
    review_items: Mapped[list[ReviewQueueItem]] = relationship(
        back_populates="image", lazy="noload"
    )

    # --- derived helpers -------------------------------------------------
    @property
    def is_rejected(self) -> bool:
        """``True`` when the image can never be auto-selected again."""
        return self.status in {
            ImageStatus.REJECTED,
            ImageStatus.DUPLICATE,
            ImageStatus.ERROR,
        }

    @property
    def library_relative_path(self) -> str:
        """Best available display path: the library copy, else the cache copy."""
        return self.library_path or self.storage_path

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"<MaterialImage {self.id} {self.status} {self.filename}>"
