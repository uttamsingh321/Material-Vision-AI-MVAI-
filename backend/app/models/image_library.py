"""Local image-library catalogue.

The ``image-library/`` folder on disk is the operator-facing taxonomy (one
subfolder per material category).  This table is its index: it records which
accepted image was promoted into the library, where it lives, and which
material it was chosen for, so the library page and the exporter can answer
"what do we already have?" without walking the filesystem on every request.

Rows are appended when an accepted image is promoted and are never reused for
a different image - if the same picture ends up chosen for another material,
a second row is written, because the provenance differs even when the bytes
do not.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class ImageLibraryItem(Base, TimestampMixin):
    """One image file present in the local, categorised image library."""

    __tablename__ = "image_library"
    __table_args__ = (
        Index("ix_image_library_category", "category"),
        Index("ix_image_library_path", "library_path"),
        Index("ix_image_library_material", "material_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: Soft reference - the library row outlives any single processing batch.
    material_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    image_id: Mapped[int | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL"), nullable=True, index=True
    )

    #: Category subfolder, e.g. ``Electrical`` - one of the configured taxonomy.
    category: Mapped[str] = mapped_column(String(120), nullable=False, default="Uncategorised")
    #: Path relative to ``image-library/``, always POSIX-style.
    library_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    #: SHA-256 of the stored bytes, so identical promotions dedupe.
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    #: Denormalised description so the library page needs no joins.
    material_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    #: Where the bytes originally came from, for provenance.
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    source_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ``material_id`` and ``image_id`` are deliberately *soft* references (no
    # ORM relationships): the library row outlives any single processing batch,
    # and the same design as ``Material.accepted_image_id`` applies (ADR-006).
    # Consumers resolve them with an explicit query when needed.

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"<ImageLibraryItem {self.library_path}>"