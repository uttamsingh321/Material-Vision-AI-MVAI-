"""Background job records - the durable heart of "resume after interruption".

The database - not the in-process queue - is the source of truth.  A worker
claims a row by flipping it to ``running`` and refreshing ``heartbeat_at`` every
few seconds.  If the process dies, the heartbeat goes stale and the recovery
sweep on the next start-up flips the row back to ``queued``; the pipeline then
re-reads ``processed_items`` and continues from where it stopped.

``progress`` is a plain 0-100 integer so the UI can render a bar without
knowing anything about the job type.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UTCDateTime
from app.models.enums import JobStatus, JobType
from app.models.types import enum_column

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.material import Material
    from app.models.user import User


class ProcessingJob(Base, TimestampMixin):
    """A unit of background work, durable across restarts."""

    __tablename__ = "processing_jobs"
    __table_args__ = (
        Index("ix_processing_jobs_status_queued", "status", "queued_at"),
        Index("ix_processing_jobs_batch_type", "batch_id", "job_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[JobType] = mapped_column(
        enum_column(JobType, "job_type"), nullable=False, index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus, "job_status"),
        nullable=False,
        default=JobStatus.QUEUED,
        index=True,
    )

    #: Batch this job operates on; ``None`` for global jobs (cache pruning).
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    batch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Set for single-material jobs; ``None`` for batch jobs.
    material_id: Mapped[int | None] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=True, index=True
    )
    parent_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("processing_jobs.id", ondelete="SET NULL"), nullable=True
    )

    # --- counters ---------------------------------------------------------
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- control ----------------------------------------------------------
    #: Cooperative cancellation/pause flags polled by the pipeline loop.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pause_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    #: Worker identity (``host:pid:slot``) that currently holds the job.
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    # --- payload / outcome -------------------------------------------------
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(120), nullable=True)

    queued_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # --- relationships ----------------------------------------------------
    created_by: Mapped[User | None] = relationship(
        back_populates="created_jobs", foreign_keys=[created_by_id]
    )
    material: Mapped[Material | None] = relationship(foreign_keys=[material_id], lazy="noload")

    # --- derived helpers --------------------------------------------------
    def remaining_items(self) -> int:
        """Items not yet processed, floored at zero."""
        return max(self.total_items - self.processed_items, 0)

    @property
    def is_resumable(self) -> bool:
        """``True`` when the pipeline can pick this job up again."""
        return self.status in {JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.QUEUED}

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"<ProcessingJob {self.id} {self.job_type} {self.status} {self.progress}%>"