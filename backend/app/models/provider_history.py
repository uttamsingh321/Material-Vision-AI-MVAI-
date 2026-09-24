"""Per-provider invocation history.

Every call the pipeline makes to a provider - successful or not - appends one
row here.  Together the rows answer the operational questions that decide
whether a source is still worth consulting: how often it errors, how slow it
has become, when it was last seen working, and whether it is currently
circuit-broken after repeated failures.

The table is deliberately append-only and time-series shaped; aggregates for
the dashboard are computed with ``GROUP BY provider`` over a recent window.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UTCDateTime
from app.models.enums import ProviderKind
from app.models.types import enum_column

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass


class ProviderHistory(Base, TimestampMixin):
    """One recorded invocation of one search/download provider."""

    __tablename__ = "provider_history"
    __table_args__ = (
        Index("ix_provider_history_provider_started", "provider", "started_at"),
        Index("ix_provider_history_material", "material_id"),
        Index("ix_provider_history_outcome", "outcome"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: Registry id, e.g. ``mock`` or ``digikey``.
    provider: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    provider_kind: Mapped[ProviderKind] = mapped_column(
        enum_column(ProviderKind, "provider_kind"),
        nullable=False,
        default=ProviderKind.WEB_SEARCH,
    )
    #: Correlates with ``processing_jobs.id`` when the call came from a job.
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    material_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    #: The query actually issued, so a bad result can be reproduced.
    query: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- outcome ---------------------------------------------------------
    #: ``ok``, ``error``, ``timeout``, ``rate_limited`` or ``no_results``.
    outcome: Mapped[str] = mapped_column(String(30), nullable=False, default="ok")
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Number of results the caller kept after de-duplication/filtering.
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: HTTP status when the failure came from a remote endpoint.
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Structured extras (headers of interest, page title, ...) for debugging.
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: Consecutive failures at the time of this row - drives circuit-breaking.
    failure_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"<ProviderHistory {self.provider} {self.outcome}>"