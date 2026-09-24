"""Structured processing log entries, queryable from the UI.

Complements - does not replace - the log *files* written by structlog.  Files
are for operators reading a server; this table is for the Logs page, which
needs to filter by job, material and severity, page through results, and
correlate with ``processing_jobs`` / ``audit_logs`` through ``request_id``.

Rows are written by the pipeline at meaningful transitions only (job start,
material finished, provider failure), not per debug line - the volume would
drown the useful signal and slow the hot path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UTCDateTime
from app.models.enums import LogLevel
from app.models.types import enum_column


class ProcessingLog(Base, TimestampMixin):
    """One structured log entry produced while processing a job."""

    __tablename__ = "processing_logs"
    __table_args__ = (
        Index("ix_processing_logs_job_created", "job_id", "created_at"),
        Index("ix_processing_logs_level_created", "level", "created_at"),
        Index("ix_processing_logs_material", "material_id"),
        Index("ix_processing_logs_batch", "batch_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: Processing-time stamp; ``created_at`` is the row-insert time from the mixin.
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    level: Mapped[LogLevel] = mapped_column(
        enum_column(LogLevel, "log_level", length=20),
        nullable=False,
        default=LogLevel.INFO,
        index=True,
    )
    #: Dotted logger name, e.g. ``app.services.search_pipeline``.
    logger: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: One-line human summary; the full template lives in ``message``.
    message: Mapped[str] = mapped_column(Text, nullable=False)

    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    job_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    material_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    provider: Mapped[str | None] = mapped_column(String(60), nullable=True)
    #: Correlates with ``audit_logs.request_id`` for a single API request.
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    #: Structured key/value context that accompanied the message.
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"<ProcessingLog {self.level} {self.message[:40]!r}>"