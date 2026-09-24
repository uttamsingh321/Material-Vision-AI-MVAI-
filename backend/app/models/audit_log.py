"""Append-only security and change log.

Every state-changing operation writes exactly one row.  The table is treated as
append-only: rows are never updated, and deleting a user nulls ``actor_id``
while keeping ``actor_email`` so the trail survives.

``request_id`` correlates an audit row with the application log lines emitted
while handling the same request (structures bound through
:mod:`app.config.logging`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.models.enums import AuditAction
from app.models.types import enum_column

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.user import User


class AuditLog(Base, TimestampMixin):
    """One recorded action."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_action_created", "action", "created_at"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_request", "request_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Denormalised so the trail stays readable after the user is gone.
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    action: Mapped[AuditAction] = mapped_column(
        enum_column(AuditAction, "audit_action", length=40), nullable=False, index=True
    )

    #: Free-form target descriptor, e.g. ``"material"`` / ``"processing_job"``.
    entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Structured before/after payload for the changed fields.
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    actor: Mapped[User | None] = relationship(
        back_populates="audit_logs", foreign_keys=[actor_id]
    )

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"<AuditLog {self.action} by {self.actor_email}>"