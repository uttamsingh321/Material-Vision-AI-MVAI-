"""Shared pytest fixtures.

Environment variables are set **before** any ``app.*`` module is imported,
because :func:`app.config.settings.get_settings` is memoised and reads the
environment exactly once per process.  Every test therefore runs against a
throwaway SQLite file and disposable upload/export/log directories under a
single session-scoped temporary root.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

#: Session-scoped scratch space, created at collection time.
TEMP_ROOT = Path(tempfile.mkdtemp(prefix="mvai-tests-"))

os.environ.update(
    {
        "MVAI_ENVIRONMENT": "local",
        "MVAI_DEBUG": "false",
        "MVAI_DATABASE_URL": f"sqlite+aiosqlite:///{(TEMP_ROOT / 'mvai-test.db').as_posix()}",
        "MVAI_UPLOADS_DIR": str(TEMP_ROOT / "uploads"),
        "MVAI_EXPORTS_DIR": str(TEMP_ROOT / "exports"),
        "MVAI_IMAGE_CACHE_DIR": str(TEMP_ROOT / "image-cache"),
        "MVAI_IMAGE_LIBRARY_DIR": str(TEMP_ROOT / "image-library"),
        "MVAI_LOGS_DIR": str(TEMP_ROOT / "logs"),
        "MVAI_LOG_FILE_ENABLED": "false",
        "MVAI_LOG_FORMAT": "json",
        # Background workers are started explicitly by the tests that need them
        "MVAI_WORKER_ENABLED": "false",
        "MVAI_QUEUE_BACKEND": "local",
        "MVAI_RATE_LIMIT_ENABLED": "false",
        "MVAI_DB_AUTO_CREATE": "true",
        "MVAI_SECRET_KEY": "unit-test-secret-key-with-sufficient-length-0123456789",
        "MVAI_VISION_VERIFY_ENABLED": "false",
        "MVAI_BOOTSTRAP_SUPERUSER": "false",
    }
)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:  # noqa: ARG001
    """Remove the scratch tree once the whole run has finished."""
    shutil.rmtree(TEMP_ROOT, ignore_errors=True)


@pytest.fixture(scope="session")
def settings():
    """Reified application settings for the test process."""
    from app.config import get_settings

    return get_settings()


@pytest.fixture(scope="session", autouse=True)
def _prepare_directories(settings) -> None:  # noqa: ANN001
    settings.ensure_directories()


@pytest.fixture(scope="session", autouse=True)
async def _database(_prepare_directories) -> AsyncIterator[None]:  # noqa: ANN001
    """Create the schema once for the whole session, then dispose the engine."""
    from app.database.session import dispose_engine, init_models, ping_database

    assert await ping_database() is False or True  # forces the engine to build
    await init_models()
    yield
    await dispose_engine()


@pytest.fixture
async def db_session() -> AsyncIterator["AsyncSession"]:  # noqa: F821
    """A session whose work is rolled back, keeping tests independent."""
    from app.database.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def anyio_backend() -> str:
    """Run the async test suite on asyncio only (no trio dependency)."""
    return "asyncio"
