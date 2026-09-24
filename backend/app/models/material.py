"""The material master row - the central entity of the pipeline.

One :class:`Material` is produced per data row of the uploaded workbook.  Rows
are grouped by ``batch_id`` (a UUID minted at upload time), which is what the
dashboard, the resume logic and the exporters all key on.

Design note: ``accepted_image_id`` is a **soft reference** (indexed integer, no
foreign key).  A real FK would create a cycle - ``materials`` -> ``images`` ->
``materials`` - which SQLite cannot express because it lacks
``ALTER TABLE ADD CONSTRAINT``.  The authoritative relationship is
``images.material_id``; this column is a denormalised pointer that keeps library
and export queries to a single join.  See ``docs/DECISIONS.md`` (ADR-006).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.constants import UNCATEGORISED
from app.database.base import Base, TimestampMixin, UTCDateTime
from app.models.enums import MaterialStatus
from app.models.types import enum_column

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.confidence_score import ConfidenceScore
    from app.models.duplicate import Duplicate
    from app.models.image import MaterialImage
    from app.models.review_queue import ReviewQueueItem
    from app.models.search_result import SearchResult


class Material(Base, TimestampMixin):
    """A single stock item that needs a verified product image."""

    __tablename__ = "materials"
    __table_args__ = (
        # Re-uploading the same workbook must be idempotent within a batch.
        UniqueConstraint("batch_id", "row_number", name="batch_row"),
        Index("ix_materials_batch_status", "batch_id", "status"),
        Index("ix_materials_material_code", "material_code"),
        Index("ix_materials_search_query_hash", "search_query_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # --- provenance ------------------------------------------------------
    #: UUID grouping every row of one upload; also the resume/cancel unit.
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    #: Human-friendly label, derived from the uploaded file name.
    batch_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_filename: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    source_sheet: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    #: 1-based row number in the source sheet; the join key back to Excel.
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- parsed material attributes -------------------------------------
    material_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str] = mapped_column(
        String(120), nullable=False, default=UNCATEGORISED, index=True
    )
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Every source column without a canonical mapping, preserved verbatim so
    #: nothing from the operator's workbook is ever lost.
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # --- pipeline state --------------------------------------------------
    status: Mapped[MaterialStatus] = mapped_column(
        enum_column(MaterialStatus, "material_status"),
        nullable=False,
        default=MaterialStatus.PENDING,
        index=True,
    )
    #: The exact query sent to the providers - kept for reproducibility.
    search_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: SHA-256 of ``search_query``; lets the cache answer repeats cheaply.
    search_query_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Soft reference - see the module docstring and ADR-006.
    accepted_image_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    #: Soft reference to the ingestion job that created this row.  ``job_id`` is
    #: intentionally *not* a foreign key: ``processing_jobs.material_id`` points
    #: the other way, and a mutual FK is a cycle that SQLite's ``CREATE TABLE``
    #: cannot order around.  See ADR-006.
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # --- relationships ---------------------------------------------------
    search_results: Mapped[list[SearchResult]] = relationship(
        back_populates="material", cascade="all, delete-orphan", lazy="selectin"
    )
    images: Mapped[list[MaterialImage]] = relationship(
        back_populates="material", cascade="all, delete-orphan", lazy="selectin"
    )
    confidence_scores: Mapped[list[ConfidenceScore]] = relationship(
        back_populates="material", cascade="all, delete-orphan", lazy="noload"
    )
    review_items: Mapped[list[ReviewQueueItem]] = relationship(
        back_populates="material", cascade="all, delete-orphan", lazy="noload"
    )
    duplicates: Mapped[list[Duplicate]] = relationship(
        back_populates="material",
        cascade="all, delete-orphan",
        foreign_keys="Duplicate.material_id",
        lazy="noload",
    )

    # --- derived helpers -------------------------------------------------
    @property
    def accepted_image(self) -> MaterialImage | None:
        """The accepted image, when it is already loaded in this session."""
        if self.accepted_image_id is None:
            return None
        for image in self.images:
            if image.id == self.accepted_image_id:
                return image
        return None

    @property
    def display_label(self) -> str:
        """Short human label used in logs, review queues and notifications."""
        code = self.material_code or f"row {self.row_number}"
        return f"{code}: {self.description[:80]}"

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.display_label
