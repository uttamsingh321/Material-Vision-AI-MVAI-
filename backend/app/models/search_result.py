"""Search-engine and distributor hits for a material.

Every provider that answers a query writes one row per result, in ranked order.
Nothing is discarded at this stage - the candidate filter and the verifier make
the accept/reject decision later, and both need the full provenance trail.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UTCDateTime
from app.models.enums import ProviderKind
from app.models.types import enum_column

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.image import MaterialImage
    from app.models.manufacturer import Manufacturer
    from app.models.material import Material


class SearchResult(Base, TimestampMixin):
    """One result returned by one provider for one material."""

    __tablename__ = "search_results"
    __table_args__ = (
        Index("ix_search_results_material_provider", "material_id", "provider"),
        Index("ix_search_results_image_url_hash", "image_url_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, index=True
    )
    manufacturer_id: Mapped[int | None] = mapped_column(
        ForeignKey("manufacturers.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # --- provider provenance ---------------------------------------------
    #: Registry id of the provider, e.g. ``digikey`` or ``bing_images``.
    provider: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    provider_kind: Mapped[ProviderKind] = mapped_column(
        enum_column(ProviderKind, "provider_kind"),
        nullable=False,
        default=ProviderKind.WEB_SEARCH,
    )
    #: Rank within this provider's result set (0-based).
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- result payload --------------------------------------------------
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Landing page the image was found on.
    page_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    #: Direct image URL, when the provider exposes one.
    image_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    source_domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    #: SHA-256 of ``image_url`` - the cheapest duplicate signal available.
    image_url_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Unmodified provider payload, retained for replay and debugging.
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    #: Set when the candidate ranker promotes this result to a download.
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Populated when the downloader rejects the URL before fetching it.
    rejection_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    searched_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=True)
    #: Request latency in milliseconds, for provider health reporting.
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- relationships ---------------------------------------------------
    material: Mapped[Material] = relationship(back_populates="search_results")
    manufacturer: Mapped[Manufacturer | None] = relationship(back_populates="search_results")
    images: Mapped[list[MaterialImage]] = relationship(
        back_populates="search_result", cascade="all, delete-orphan", lazy="noload"
    )

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"<SearchResult {self.provider}#{self.position} {self.image_url}>"