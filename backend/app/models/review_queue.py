"""Human-in-the-loop review queue.

Items land here when the machine is not confident enough to decide alone -
below the accept threshold but above the reject floor, conflicting evidence, or
an explicit operator request.  The queue stores *why* it was raised so reviewers
can be routed by cause rather than opening every item.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UTCDateTime
from app.models.enums import ReviewReason, ReviewStatus
from app.models.types import enum_column

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.image import MaterialImage
    from app.models.material import Material
    from app.models.user import User


class ReviewQueueItem(Base, TimestampMixin):
    """One material (optionally with a specific candidate) awaiting a decision."""

    __tablename__ = "review_queue"
    __table_args__ = (
        Index("ix_review_queue_status_priority", "status", "priority"),
        Index("ix_review_queue_material_status", "material_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Candidate under review.  ``None`` means "no acceptable candidate yet".
    image_id: Mapped[int | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL"), nullable=True, index=True
    )

    reason: Mapped[ReviewReason] = mapped_column(
        enum_column(ReviewReason, "review_reason"), nullable=False, index=True
    )
    status: Mapped[ReviewStatus] = mapped_column(
        enum_column(ReviewStatus, "review_status"),
        nullable=False,
        default=ReviewStatus.PENDING,
        index=True,
    )
    #: Lower number is more urgent; drives queue ordering.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    assigned_to_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Image the reviewer picked, when they overrode the machine's candidate.
    selected_image_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # --- relationships ---------------------------------------------------
    material: Mapped[Material] = relationship(back_populates="review_items")
    image: Mapped[MaterialImage | None] = relationship(back_populates="review_items")
    assigned_to: Mapped[User | None] = relationship(
        foreign_keys=[assigned_to_id], lazy="noload"
    )
    reviewer: Mapped[User | None] = relationship(
        back_populates="review_items", foreign_keys=[reviewer_id], lazy="noload"
    )

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"<ReviewQueueItem {self.id} {self.reason} {self.status}>"