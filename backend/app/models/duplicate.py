"""Duplicate image relationships.

Three independent signals feed this table: exact content hash (SHA-256),
perceptual hash (Hamming distance) and repeated source URL.  Storing the
relationship rather than only a boolean makes it possible to answer "which
material already owns this image?" - which is exactly what the cache needs in
order to satisfy a repeat request without touching the network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.models.enums import DuplicateMethod
from app.models.types import enum_column

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.image import MaterialImage
    from app.models.material import Material


class Duplicate(Base, TimestampMixin):
    """Records that ``image_id`` duplicates ``duplicate_of_image_id``."""

    __tablename__ = "duplicates"
    __table_args__ = (
        Index("ix_duplicates_image", "image_id"),
        Index("ix_duplicates_canonical", "duplicate_of_image_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The discarded copy.
    image_id: Mapped[int] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    #: The retained, canonical copy.
    duplicate_of_image_id: Mapped[int] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )

    method: Mapped[DuplicateMethod] = mapped_column(
        enum_column(DuplicateMethod, "duplicate_method"), nullable=False, default=DuplicateMethod.SHA256
    )
    #: 1.0 for an exact hash match; ``1 - distance/64`` for perceptual matches.
    similarity: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    #: Free-form evidence, e.g. the hamming distance or the shared URL.
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)

    material: Mapped[Material] = relationship(
        back_populates="duplicates", foreign_keys=[material_id]
    )
    image: Mapped[MaterialImage] = relationship(foreign_keys=[image_id], lazy="noload")
    duplicate_of: Mapped[MaterialImage] = relationship(
        foreign_keys=[duplicate_of_image_id], lazy="noload"
    )

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"<Duplicate image={self.image_id} of={self.duplicate_of_image_id}>"