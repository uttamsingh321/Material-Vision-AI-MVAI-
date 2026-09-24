"""Alembic environment for MVAI.

Wired to the application rather than to the .ini file:

* the database URL comes from :class:`app.config.Settings`, so migrations and
  the running app can never disagree about which database they target;
* ``target_metadata`` is ``app.database.base.Base.metadata`` with every model
  imported, so autogenerate sees the full schema;
* the engine is created *async* (the app's URL carries an async driver such as
  ``sqlite+aiosqlite``) and migrations run through ``connection.run_sync``,
  which is how SQLAlchemy expects sync-style migration code to be executed
  against an async engine;
* ``render_as_batch=True`` because SQLite cannot ALTER most constraints in
  place - without it, generated migrations would fail on the default database.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# ``<repo>/database/alembic/env.py`` -> ``<repo>/backend`` on sys.path so the
# ``app`` package resolves no matter where alembic is invoked from.
BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import models  # noqa: E402,F401  (registers every mapper)
from app.config import get_settings  # noqa: E402
from app.database.base import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode: emit SQL without a live connection."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:  # noqa: ANN001
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def _run_migrations_online_async() -> None:
    """Run migrations against a live database through an async engine."""
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_migrations_online_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
