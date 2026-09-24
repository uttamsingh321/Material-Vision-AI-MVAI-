"""Async engine and session management.

The engine is created lazily and cached per process.  All dialect-specific
tuning (connection-pool arguments, SQLite ``PRAGMA`` setup) lives here so the
rest of the application stays dialect-agnostic and testable.

Typical use inside a service::

    async with session_scope() as session:
        ...

Inside a FastAPI route, depend on :func:`get_db` instead - it binds the session
to the request lifecycle.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.config.logging import get_logger
from app.database.base import Base

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _engine_kwargs(url: str) -> dict[str, Any]:
    """Assemble ``create_async_engine`` arguments for the active dialect."""
    settings = get_settings()

    if _is_sqlite(url):
        # WAL keeps readers (API) from blocking the writer (worker).  The
        # asyncio SQLite dialect already defaults to an adapted QueuePool for
        # file databases, which is exactly the behaviour we want - overriding
        # ``poolclass`` here would raise "Pool class cannot be used with
        # asyncio engine", so only the sizing is customised.
        return {
            "connect_args": {
                "check_same_thread": False,
                "timeout": settings.db_pool_timeout_seconds,
            },
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout_seconds,
            "pool_recycle": settings.db_pool_recycle_seconds,
            "pool_pre_ping": settings.db_pool_pre_ping,
        }

    return {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout_seconds,
        "pool_recycle": settings.db_pool_recycle_seconds,
        "pool_pre_ping": settings.db_pool_pre_ping,
    }


def _install_sqlite_pragmas(engine: AsyncEngine) -> None:
    """Apply durability/concurrency pragmas to every new SQLite connection."""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA temp_store=MEMORY")
        finally:
            cursor.close()


def build_engine(url: str | None = None) -> AsyncEngine:
    """Create a new engine.  Prefer :func:`get_engine` for shared use."""
    settings = get_settings()
    target = url or settings.database_url
    engine = create_async_engine(
        target,
        echo=settings.db_echo,
        future=True,
        **_engine_kwargs(target),
    )
    if _is_sqlite(target):
        _install_sqlite_pragmas(engine)
    logger.debug("database.engine_created", dialect=engine.dialect.name)
    return engine


def get_engine() -> AsyncEngine:
    """Process-wide engine singleton."""
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Process-wide session factory bound to :func:`get_engine`."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope: commit on success, roll back on any exception."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency.

    Commits are the caller's responsibility so a route can choose its own
    transaction boundary; the session is always closed for us.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_models() -> None:
    """Create tables for every registered model.

    A development convenience guarded by ``MVAI_DB_AUTO_CREATE``.  Production
    deployments run ``alembic upgrade head`` instead.
    """
    from app import models  # noqa: F401  (registers mappers on Base.metadata)

    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    logger.info("database.schema_ready", tables=len(Base.metadata.tables))


async def dispose_engine() -> None:
    """Release all pooled connections.  Called on application shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.debug("database.engine_disposed")
    _engine = None
    _session_factory = None


async def ping_database() -> bool:
    """``True`` when a trivial query succeeds.  Used by the health endpoint."""
    try:
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("database.ping_failed", error=str(exc))
        return False
