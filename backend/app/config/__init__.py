"""Configuration package.

Re-exports the pieces every other module needs so imports stay short::

    from app.config import get_settings, get_logger
"""

from __future__ import annotations

from app.config.constants import (
    CANONICAL_MATERIAL_FIELDS,
    DEFAULT_COLUMN_ALIASES,
    DEFAULT_MATERIAL_CATEGORIES,
    REQUIRED_MATERIAL_FIELDS,
    SUPPORTED_SPREADSHEET_SUFFIXES,
)
from app.config.logging import (
    bind_context,
    clear_context,
    configure_logging,
    get_logger,
    log_context,
)
from app.config.settings import BACKEND_ROOT, PROJECT_ROOT, Settings, get_settings

__all__ = [
    "BACKEND_ROOT",
    "CANONICAL_MATERIAL_FIELDS",
    "DEFAULT_COLUMN_ALIASES",
    "DEFAULT_MATERIAL_CATEGORIES",
    "PROJECT_ROOT",
    "REQUIRED_MATERIAL_FIELDS",
    "SUPPORTED_SPREADSHEET_SUFFIXES",
    "Settings",
    "bind_context",
    "clear_context",
    "configure_logging",
    "get_logger",
    "get_settings",
    "log_context",
]
