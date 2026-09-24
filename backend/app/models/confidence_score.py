"""Confidence scores: the auditable justification for every automatic decision.

A row is written for each scored (material, image) pair.  The component scores
are stored **alongside** the weighted total so that:

* a reviewer can see *why* something landed below the threshold;
* the weights can be retuned and the pipeline re-scored offline, without
  re-crawling, because the raw inputs are still here;
* the audit report can prove how a given image was chosen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.models.enums import ConfidenceBand, Decision
from app.models.types import enum_column

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.image import MaterialImage
    from app.models.material import Material


class ConfidenceScore(Base, TimestampMixin):
    """Weighted evidence for one candidate image of one material."""

    __tablename__ = "confidence_scores"
    __table_args__ = (
        Index("ix_confidence_scores_material_decision", "material_id", "decision"),
        Index("ix_confidence_scores_overall", "overall"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_id: Mapped[int | None] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), nullable=True, index=True
    )

    #: Weighted total in ``[0, 1]`` - the number compared to the thresholds.
    overall: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    band: Mapped[ConfidenceBand] = mapped_column(
        enum_column(ConfidenceBand, "confidence_band"),
        nullable=False,
        default=ConfidenceBand.NONE,
    )
    decision: Mapped[Decision] = mapped_column(
        enum_column(Decision, "score_decision"),
        nullable=False,
        default=Decision.REVIEW,
        index=True,
    )

    # --- component scores (each in ``[0, 1]``) ---------------------------
    ocr_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    vision_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    brand_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    text_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: Exact weights used, so the result is reproducible after retuning.
    weights: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: Weighted contributions per component (score x weight) for explanation.
    contributions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: Human-readable sentence summarising the verdict.
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Identifier of the scoring strategy, e.g. ``weighted-v1``.
    strategy: Mapped[str] = mapped_column(String(60), nullable=False, default="weighted")
    #: Component values that were unavailable, so a score is not misread.
    missing_signals: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    material: Mapped[Material] = relationship(back_populates="confidence_scores")
    image: Mapped[MaterialImage | None] = relationship(back_populates="confidence_scores")

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"<ConfidenceScore material={self.material_id} overall={self.overall:.3f}>"