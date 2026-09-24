"""structlog configuration shared by the API server, workers and scripts.

A single renderer is installed for both structlog-native records and records
emitted by third-party libraries (uvicorn, SQLAlchemy, httpx) so that log files
and container output are uniform.

``MVAI_LOG_FORMAT=console`` produces human-readable coloured output for local
development; ``json`` produces one JSON object per line for log shippers.
Correlation identifiers (``request_id``, ``job_id``, ``material_id``) are bound
via :mod:`structlog.contextvars` and therefore travel with every log line
emitted while handling a request or inside a worker task.
"""

from __future__ import annotations

import importlib.util
import logging
import logging.handlers
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog

from app.config.settings import Settings

_configured = False

#: Context variable names recognised across the codebase.  Grouped here so the
#: middleware, the workers and the log processor never drift apart.
CONTEXT_REQUEST_ID = "request_id"
CONTEXT_JOB_ID = "job_id"
CONTEXT_MATERIAL_ID = "material_id"
CONTEXT_USER_ID = "user_id"
CONTEXT_WORKER_ID = "worker_id"


def _build_shared_processors() -> list[Any]:
    """Processors applied identically to native and foreign log records."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        structlog.processors.format_exc_info,
    ]


def _console_colors_enabled(stream: Any) -> bool:
    """Decide whether ANSI colouring is safe for ``stream``.

    Honours the ``NO_COLOR`` convention, requires a TTY, and on Windows also
    requires ``colorama`` (which structlog insists on there) - if it is absent
    we simply render plain text instead of failing to start.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if sys.platform == "win32":
        return importlib.util.find_spec("colorama") is not None
    return True


def configure_logging(settings: Settings) -> None:
    """Install the logging pipeline.  Idempotent; safe to call from any entry point."""
    global _configured
    if _configured:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    shared = _build_shared_processors()

    if settings.log_format == "json":
        renderer: Any = structlog.processors.JSONRenderer(sort_keys=True)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=_console_colors_enabled(sys.stdout))

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handlers: list[logging.Handler] = []
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    handlers.append(console)

    if settings.log_file_enabled:
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(
            settings.logs_dir / settings.log_file_name,
            maxBytes=settings.log_file_max_bytes,
            backupCount=settings.log_file_backup_count,
            encoding="utf-8",
        )
        rotating.setFormatter(formatter)
        handlers.append(rotating)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    for handler in handlers:
        handler.setLevel(level)
        root.addHandler(handler)
    root.setLevel(level)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _quiet_noisy_loggers(settings, level)
    _configured = True


def _quiet_noisy_loggers(settings: Settings, level: int) -> None:
    """Keep third-party chatter proportional to the configured verbosity."""
    mapping = {
        "uvicorn.error": level,
        "uvicorn.access": level,
        "alembic": level,
        "sqlalchemy.engine": logging.INFO if settings.log_sql_statements else logging.WARNING,
        "httpx": logging.WARNING,
        "httpcore": logging.WARNING,
        "watchfiles": logging.WARNING,
        "multipart": logging.WARNING,
    }
    for name, logger_level in mapping.items():
        logging.getLogger(name).setLevel(logger_level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger.  ``name`` is conventionally ``__name__``."""
    return structlog.get_logger(name)


def bind_context(**values: Any) -> None:
    """Bind correlation values for the remainder of the current context."""
    structlog.contextvars.bind_contextvars(**{k: v for k, v in values.items() if v is not None})


def clear_context() -> None:
    """Drop all context-bound values (called at the end of a request/task)."""
    structlog.contextvars.clear_contextvars()


@contextmanager
def log_context(**values: Any) -> Iterator[None]:
    """Bind values for the duration of the ``with`` block, then restore state."""
    tokens = structlog.contextvars.bind_contextvars(
        **{k: v for k, v in values.items() if v is not None}
    )
    try:
        yield
    finally:
        structlog.contextvars.reset_contextvars(**tokens)
