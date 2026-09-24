"""Declarative base, naming conventions and shared column mixins.

Two cross-dialect concerns are solved here once so that no model has to care
about them:

1. **Deterministic constraint names.**  Alembic cannot ``DROP`` an anonymous
   constraint, and PostgreSQL truncates auto-generated ones.  Every constraint
   therefore gets an explicit name through ``NAMING_CONVENTION``.
2. **Timezone-correct timestamps.**  SQLite silently drops ``tzinfo`` while
   PostgreSQL keeps it, which makes the same code behave differently per
   dialect.  :class:`UTCDateTime` normalises on write and re-attaches UTC on
   read, so the application only ever sees aware UTC datetimes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Current time as an aware UTC :class:`datetime`."""
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator[datetime]):
    """``DATETIME`` that always round-trips timezone-aware UTC values.

    * PostgreSQL stores ``TIMESTAMP WITH TIME ZONE`` and returns it untouched.
    * SQLite (which has no native date type) stores a naive UTC string but
      returns an aware datetime, so callers never have to guess.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        # SQLite's DATETIME bind processor ignores tzinfo; strip it explicitly
        # so the stored text is unambiguously UTC.
        if dialect.name == "sqlite":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for every ORM entity."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def to_dict(self) -> dict[str, Any]:
        """Shallow column dump.  Handy for audit payloads and log context.

        Relationships are intentionally excluded - callers that need them
        should use a Pydantic schema with explicit ``from_attributes``.
        """
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` maintained by the ORM and the DB."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utcnow,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )
