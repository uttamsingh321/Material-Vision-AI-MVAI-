"""Manufacturer registry.

Manufacturer entries drive the Phase 2 crawler: ``search_domain`` scopes a
site-restricted query, ``priority`` decides the order providers are consulted,
and ``is_active`` lets an operator disable a source that rate-limits or
returns poor imagery without a code change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.search_result import SearchResult


class Manufacturer(Base, TimestampMixin):
    """A brand/vendor whose catalogue may be searched for product imagery."""

    __tablename__ = "manufacturers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    #: Lower-case, hyphenated identifier used for folders and cache keys.
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: Domain used to scope ``site:`` queries, e.g. ``schneider-electric.com``.
    search_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Optional per-manufacturer image-URL template; ``{model}`` is substituted.
    image_url_template: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Lower number wins when several manufacturers match the same material.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    search_results: Mapped[list[SearchResult]] = relationship(
        back_populates="manufacturer", lazy="noload"
    )

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.name
