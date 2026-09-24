"""User accounts and authentication state."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UTCDateTime
from app.models.enums import Role
from app.models.types import enum_column

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.audit_log import AuditLog
    from app.models.processing_job import ProcessingJob
    from app.models.review_queue import ReviewQueueItem


class User(Base, TimestampMixin):
    """An operator of the platform.

    Authentication is stateless (JWT); this table only stores identity,
    authorisation and the password hash.  Password hashing lives in
    :mod:`app.auth.security` and never leaks into the model.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        enum_column(Role, "user_role"), nullable=False, default=Role.VIEWER
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # --- relationships ---------------------------------------------------
    #: Audit rows are deliberately *not* cascade-deleted with the user: an
    #: audit trail that disappears with its subject is worthless.  The FK is
    #: nulled out and ``actor_email`` preserves the identity.
    audit_logs: Mapped[list[AuditLog]] = relationship(
        back_populates="actor", foreign_keys="AuditLog.actor_id", lazy="noload"
    )
    created_jobs: Mapped[list[ProcessingJob]] = relationship(
        back_populates="created_by", foreign_keys="ProcessingJob.created_by_id", lazy="noload"
    )
    review_items: Mapped[list[ReviewQueueItem]] = relationship(
        back_populates="reviewer", foreign_keys="ReviewQueueItem.reviewer_id", lazy="noload"
    )

    @property
    def is_admin(self) -> bool:
        """``True`` for superusers or members of the ``admin`` role."""
        return self.is_superuser or self.role == Role.ADMIN

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.full_name or self.email} <{self.email}>"
