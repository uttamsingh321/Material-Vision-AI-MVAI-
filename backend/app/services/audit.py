"""Structured audit and processing logs persisted to the database.

Two tables, two audiences:

``audit_logs``
    Append-only, security/change oriented: who started, paused, cancelled or
    exported what.  Written through :class:`AuditLogger` with an
    :class:`app.models.enums.AuditAction` so reports can group on action.

``processing_logs``
    Operational, job-scoped: "search finished for material 42", "provider
    mock failed".  Written through :class:`ProcessingLogger` with a
    :class:`app.models.enums.LogLevel`.  These rows are what the Logs page
    pages through and what the ``logs`` WebSocket channel streams live.

Both loggers take an explicit ``AsyncSession`` - the caller owns the
transaction boundary.  Both also mirror their payload onto the in-process
:class:`app.services.events.EventBus` so connected UIs see events without
polling; the database remains the source of truth.

Severity note: filtering by level uses :attr:`LogLevel.rank` in Python or an
explicit ``IN`` set in SQL - SQLite cannot compare string enums with ``>=``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.constants import WS_CHANNEL_JOBS, WS_CHANNEL_LOGS
from app.config.logging import get_logger
from app.models.audit_log import AuditLog
from app.models.enums import LogLevel
from app.models.processing_log import ProcessingLog
from app.services.events import get_event_bus

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.enums import AuditAction

logger = get_logger(__name__)

#: Truncation ceilings matching the column definitions.
_MAX_MESSAGE = 4_000
_MAX_SUMMARY = 4_000


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return value[:limit]


class AuditLogger:
    """Writes append-only rows to ``audit_logs``."""

    async def record(
        self,
        session: AsyncSession,
        action: AuditAction,
        *,
        actor_id: int | None = None,
        actor_email: str | None = None,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        summary: str | None = None,
        context: dict[str, Any] | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        """Append one audit row and flush it into the caller's transaction."""
        row = AuditLog(
            actor_id=actor_id,
            actor_email=actor_email,
            action=action,
            entity_type=entity_type,
            entity_id=None if entity_id is None else str(entity_id),
            summary=_truncate(summary, _MAX_SUMMARY),
            context=context or {},
            request_id=request_id,
            ip_address=ip_address,
            user_agent=_truncate(user_agent, 500),
        )
        session.add(row)
        await session.flush()
        logger.info(
            "audit.recorded",
            action=str(action),
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
        )
        return row

    async def list_recent(
        self,
        session: AsyncSession,
        *,
        action: AuditAction | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        """Newest-first page of audit rows, optionally filtered by action."""
        query = select(AuditLog)
        if action is not None:
            query = query.where(AuditLog.action == action)
        total = (
            await session.execute(select(func.count()).select_from(query.subquery()))
        ).scalar_one()
        rows = (
            await session.execute(
                query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()


class ProcessingLogger:
    """Writes job-scoped rows to ``processing_logs`` and streams them live."""

    async def log(
        self,
        session: AsyncSession,
        level: LogLevel,
        message: str,
        *,
        logger_name: str | None = None,
        job_id: int | None = None,
        job_type: str | None = None,
        material_id: int | None = None,
        batch_id: str | None = None,
        provider: str | None = None,
        request_id: str | None = None,
        context: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> ProcessingLog:
        """Persist one log line and publish it on the ``logs``/``jobs`` channels."""
        row = ProcessingLog(
            timestamp=timestamp or datetime.now(timezone.utc),
            level=level,
            logger=logger_name,
            message=_truncate(message, _MAX_MESSAGE) or "",
            job_id=job_id,
            job_type=job_type,
            material_id=material_id,
            batch_id=batch_id,
            provider=provider,
            request_id=request_id,
            context=context or {},
        )
        session.add(row)
        await session.flush()

        payload = {
            "id": row.id,
            "timestamp": row.timestamp.isoformat(),
            "level": str(level),
            "logger": logger_name,
            "message": row.message,
            "job_id": job_id,
            "job_type": job_type,
            "material_id": material_id,
            "batch_id": batch_id,
            "provider": provider,
            "context": context or {},
        }
        bus = get_event_bus()
        bus.publish(WS_CHANNEL_LOGS, payload)
        if job_id is not None:
            bus.publish(WS_CHANNEL_JOBS, {"event": "log", **payload})
        return row

    async def info(self, session: AsyncSession, message: str, **kwargs: Any) -> ProcessingLog:
        return await self.log(session, LogLevel.INFO, message, **kwargs)

    async def warning(self, session: AsyncSession, message: str, **kwargs: Any) -> ProcessingLog:
        return await self.log(session, LogLevel.WARNING, message, **kwargs)

    async def error(self, session: AsyncSession, message: str, **kwargs: Any) -> ProcessingLog:
        return await self.log(session, LogLevel.ERROR, message, **kwargs)

    async def debug(self, session: AsyncSession, message: str, **kwargs: Any) -> ProcessingLog:
        return await self.log(session, LogLevel.DEBUG, message, **kwargs)

    async def query(
        self,
        session: AsyncSession,
        *,
        job_id: int | None = None,
        batch_id: str | None = None,
        material_id: int | None = None,
        min_level: LogLevel | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ProcessingLog], int]:
        """Newest-first page of log rows with the requested filters.

        ``min_level`` is resolved with an explicit ``IN`` set derived from
        :data:`app.models.enums.LOG_LEVEL_RANKS` - never a SQL ``>=`` on the
        enum value, which would compare strings lexically.
        """
        query = select(ProcessingLog)
        if job_id is not None:
            query = query.where(ProcessingLog.job_id == job_id)
        if batch_id is not None:
            query = query.where(ProcessingLog.batch_id == batch_id)
        if material_id is not None:
            query = query.where(ProcessingLog.material_id == material_id)
        if min_level is not None:
            allowed = [level for level in LogLevel if level.rank >= min_level.rank]
            query = query.where(ProcessingLog.level.in_(allowed))

        total = (
            await session.execute(select(func.count()).select_from(query.subquery()))
        ).scalar_one()
        rows = (
            await session.execute(
                query.order_by(ProcessingLog.timestamp.desc(), ProcessingLog.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), int(total)


_audit_logger: AuditLogger | None = None
_processing_logger: ProcessingLogger | None = None


def get_audit_logger() -> AuditLogger:
    """Process-wide audit logger singleton."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def get_processing_logger() -> ProcessingLogger:
    """Process-wide processing logger singleton."""
    global _processing_logger
    if _processing_logger is None:
        _processing_logger = ProcessingLogger()
    return _processing_logger


__all__ = [
    "AuditLogger",
    "ProcessingLogger",
    "get_audit_logger",
    "get_processing_logger",
]

