"""Portable column types shared by the ORM models."""

from __future__ import annotations

from enum import Enum as PyEnum
from typing import TypeVar

from sqlalchemy import Enum as SAEnum

from app.config import get_settings

E = TypeVar("E", bound=PyEnum)


def enum_column(enum_cls: type[E], name: str, *, length: int = 40) -> SAEnum:
    """Build an ``Enum`` column type that works on SQLite *and* PostgreSQL.

    ``MVAI_DB_NATIVE_ENUMS`` selects between a native database enum and a
    validated ``VARCHAR``.  SQLite has no enum type, so the portable form is the
    default and the only one used by local development.

    The member *values* (``"matched"``) rather than the member *names*
    (``"MATCHED"``) are persisted, so the stored contract stays stable even if a
    member is renamed later.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=get_settings().db_native_enums,
        length=length,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )
