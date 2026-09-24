"""Central, environment-driven configuration for the MVAI backend.

Every tunable lives here exactly once.  Nothing in the application may hardcode
a path, URL, credential, timeout or provider endpoint - it must be read from
:class:`Settings`, which is populated from environment variables (prefix
``MVAI_``) and/or a ``.env`` file at the repository root.

Usage::

    from app.config import get_settings

    settings = get_settings()
    settings.uploads_dir          # resolved, guaranteed to exist

``get_settings`` is memoised, so the environment is parsed once per process.
Tests override values with ``get_settings.cache_clear()`` or by setting
environment variables before the first call.
"""

from __future__ import annotations

import json
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.constants import (
    DEFAULT_ALLOWED_IMAGE_SUFFIXES,
    DEFAULT_COLUMN_ALIASES,
    DEFAULT_CORS_ORIGINS,
    DEFAULT_MATERIAL_CATEGORIES,
    SUPPORTED_SPREADSHEET_SUFFIXES,
)

# ``<repo>/backend/app/config/settings.py`` -> ``<repo>``
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
BACKEND_ROOT: Path = PROJECT_ROOT / "backend"

Environment = Literal["local", "development", "staging", "production"]
StorageBackend = Literal["local", "s3"]
QueueBackend = Literal["local", "redis"]
LogFormat = Literal["console", "json"]


class Settings(BaseSettings):
    """Runtime configuration, immutable by convention."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_prefix="MVAI_",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    app_name: str = "Material Vision AI"
    app_version: str = "0.1.0"
    app_tagline: str = "Enterprise Material Image Intelligence Platform"
    environment: Environment = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    host: str = "0.0.0.0"
    port: int = 8000
    root_path: str = ""
    docs_url: str = "/docs"
    redoc_url: str = "/redoc"
    openapi_url: str = "/openapi.json"

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    secret_key: str = Field(
        default_factory=lambda: secrets.token_urlsafe(48),
        description=(
            "HMAC key for signing JWTs.  A random value is generated when "
            "unset, which invalidates all tokens on restart - always set this "
            "in any shared or production environment."
        ),
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    refresh_token_expire_days: int = 7
    password_min_length: int = 8
    bcrypt_rounds: int = 12
    cors_origins: str = ",".join(DEFAULT_CORS_ORIGINS)
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 240
    trusted_hosts: str = "*"

    #: Bootstrap account created by ``scripts/seed.py`` and on first start when
    #: ``bootstrap_superuser`` is true.  Override in every deployment.
    bootstrap_superuser: bool = True
    first_superuser_email: str = "admin@mvai.local"
    first_superuser_password: str = "ChangeMe!123"
    first_superuser_name: str = "MVAI Administrator"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    #: SQLAlchemy async URL.  Defaults to a file-backed SQLite database so the
    #: stack runs with no external services.  Point it at
    #: ``postgresql+asyncpg://user:pass@host:5432/mvai`` for production.
    database_url: str = (
        f"sqlite+aiosqlite:///{(PROJECT_ROOT / 'database' / 'mvai.db').as_posix()}"
    )
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1_800
    db_pool_pre_ping: bool = True
    #: Emit native PostgreSQL enums when true; ``VARCHAR`` otherwise (portable).
    db_native_enums: bool = False
    db_auto_create: bool = True

    # ------------------------------------------------------------------
    # Queue / cache
    # ------------------------------------------------------------------
    #: ``local`` runs an in-process asyncio worker pool (no Redis required);
    #: ``redis`` moves both the queue broker and the cache onto Redis.
    queue_backend: QueueBackend = "local"
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 86_400
    cache_namespace: str = "mvai"

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    storage_backend: StorageBackend = "local"
    storage_bucket: str = "mvai-images"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    s3_region: str = "us-east-1"
    s3_use_ssl: bool = False

    uploads_dir: Path = PROJECT_ROOT / "uploads"
    exports_dir: Path = PROJECT_ROOT / "exports"
    image_cache_dir: Path = PROJECT_ROOT / "image-cache"
    image_library_dir: Path = PROJECT_ROOT / "image-library"
    logs_dir: Path = PROJECT_ROOT / "logs"
    max_upload_size_mb: int = 100
    upload_chunk_size_bytes: int = 1_048_576

    # ------------------------------------------------------------------
    # Excel ingestion
    # ------------------------------------------------------------------
    #: How many leading rows to inspect when locating the header row.  Real
    #: material masters often carry a title/logo block above the actual table.
    excel_header_scan_rows: int = 15
    #: Empty string means "use the workbook's active sheet".
    excel_sheet_name: str = ""
    excel_max_rows: int = 200_000
    #: When true a workbook missing the mandatory columns is rejected outright
    #: instead of being ingested with the offending rows skipped.
    excel_strict_columns: bool = False
    #: JSON object merged over ``constants.DEFAULT_COLUMN_ALIASES``, e.g.
    #: ``{"material_code": ["sap code"]}``.
    column_aliases_json: str = ""

    # ------------------------------------------------------------------
    # Search providers (Phase 2)
    # ------------------------------------------------------------------
    #: Comma-separated provider ids resolved through the crawler registry.
    search_providers: str = "google,bing,manufacturer"
    #: Providers allowed to actually run, comma-separated.  Everything else is
    #: registered but inert.  Phase 1 ships with only the local mock source so
    #: the whole application runs end-to-end with no external API.
    enabled_providers: str = "mock"
    search_timeout_seconds: float = 20.0
    search_max_results_per_provider: int = 15
    search_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 MVAI/0.1"
    )
    search_rate_limit_per_minute: int = 30
    search_concurrency: int = 6
    download_concurrency: int = 8
    download_timeout_seconds: float = 30.0
    download_max_bytes: int = 15_000_000
    download_min_bytes: int = 3_000
    image_min_dimension: int = 300
    image_max_candidates: int = 24
    allowed_image_suffixes: str = ",".join(DEFAULT_ALLOWED_IMAGE_SUFFIXES)

    google_api_key: str = ""
    google_cse_id: str = ""
    bing_api_key: str = ""
    serpapi_api_key: str = ""
    #: Restrict manufacturer-site lookups to these domains (comma separated).
    manufacturer_domains: str = ""

    # ------------------------------------------------------------------
    # AI verification and OCR (Phase 3)
    # ------------------------------------------------------------------
    #: The vision model is used *only* to verify a candidate image that was
    #: already found on the web.  It never generates imagery.  See ADR-007.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_vision_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 45.0
    vision_verify_enabled: bool = False
    ocr_enabled: bool = True
    ocr_languages: str = "eng"
    ocr_timeout_seconds: float = 60.0
    clip_enabled: bool = False
    clip_model_name: str = "ViT-B-32"
    perceptual_hash_size: int = 8
    #: Hamming distance at or below which two perceptual hashes are "the same".
    perceptual_duplicate_distance: int = 6

    # ------------------------------------------------------------------
    # Confidence scoring
    # ------------------------------------------------------------------
    confidence_accept_threshold: float = 0.80
    confidence_review_threshold: float = 0.45
    weight_ocr: float = 0.30
    weight_vision: float = 0.30
    weight_brand: float = 0.15
    weight_model: float = 0.15
    weight_text: float = 0.10
    weight_provider: float = 0.10

    #: Comma-separated taxonomy; also materialised as image-library subfolders.
    material_categories: str = ",".join(DEFAULT_MATERIAL_CATEGORIES)

    # ------------------------------------------------------------------
    # Background processing
    # ------------------------------------------------------------------
    worker_enabled: bool = True
    worker_concurrency: int = 4
    worker_poll_interval_seconds: float = 1.0
    job_max_attempts: int = 3
    job_retry_backoff_seconds: float = 5.0
    job_heartbeat_interval_seconds: int = 15
    #: A running job whose heartbeat is older than this is presumed dead and
    #: is automatically requeued - this is what makes a crash survivable.
    job_stale_after_seconds: int = 180
    job_batch_size: int = 250
    export_include_images: bool = True

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_level: str = "INFO"
    log_format: LogFormat = "console"
    log_file_enabled: bool = True
    log_file_name: str = "mvai.log"
    log_file_max_bytes: int = 10_485_760
    log_file_backup_count: int = 5
    log_sql_statements: bool = False

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}:
            raise ValueError(f"unsupported log level: {value!r}")
        return level

    @field_validator("column_aliases_json")
    @classmethod
    def _validate_column_aliases(cls, value: str) -> str:
        """Fail fast on a malformed alias override rather than at ingestion."""
        if not value.strip():
            return ""
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"MVAI_COLUMN_ALIASES_JSON is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("MVAI_COLUMN_ALIASES_JSON must be a JSON object")
        for logical_field, aliases in parsed.items():
            if logical_field not in DEFAULT_COLUMN_ALIASES:
                raise ValueError(
                    f"unknown logical field {logical_field!r}; expected one of "
                    f"{sorted(DEFAULT_COLUMN_ALIASES)}"
                )
            if not isinstance(aliases, (list, tuple)) or not all(
                isinstance(alias, str) for alias in aliases
            ):
                raise ValueError(f"aliases for {logical_field!r} must be a list of strings")
        return value

    @field_validator("confidence_review_threshold")
    @classmethod
    def _validate_review_threshold(cls, value: float, info: ValidationInfo) -> float:
        accept = info.data.get("confidence_accept_threshold", 1.0)
        if value > accept:
            raise ValueError(
                "confidence_review_threshold must not exceed confidence_accept_threshold"
            )
        return value

    @field_validator(
        "weight_ocr",
        "weight_vision",
        "weight_brand",
        "weight_model",
        "weight_text",
        "weight_provider",
    )
    @classmethod
    def _validate_weight(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence weights must be between 0.0 and 1.0")
        return value

    @model_validator(mode="after")
    def _enforce_production_hardening(self) -> Settings:
        """Refuse to boot a shared environment with development defaults."""
        if self.environment not in {"staging", "production"}:
            return self

        problems: list[str] = []
        if len(self.secret_key) < 32:
            problems.append("MVAI_SECRET_KEY must be at least 32 characters")
        if self.first_superuser_password == "ChangeMe!123":
            problems.append("MVAI_FIRST_SUPERUSER_PASSWORD must be changed")
        if self.debug:
            problems.append("MVAI_DEBUG must be disabled")
        if "*" in self.trusted_host_list:
            problems.append("MVAI_TRUSTED_HOSTS must list explicit hosts")
        if problems:
            raise ValueError("invalid configuration for " f"{self.environment}: " + "; ".join(problems))
        return self

    # ------------------------------------------------------------------
    # Derived accessors - the only way the app reads list-ish settings
    # ------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment in {"staging", "production"}

    @property
    def cors_origin_list(self) -> list[str]:
        return list(_split_csv(self.cors_origins))

    @property
    def trusted_host_list(self) -> tuple[str, ...]:
        return _split_csv(self.trusted_hosts)

    @property
    def allowed_image_suffix_list(self) -> tuple[str, ...]:
        return tuple(suffix.lower() for suffix in _split_csv(self.allowed_image_suffixes))

    @property
    def search_provider_list(self) -> tuple[str, ...]:
        return tuple(provider.lower() for provider in _split_csv(self.search_providers))

    @property
    def enabled_provider_list(self) -> tuple[str, ...]:
        """Providers permitted to run, lower-cased and de-duplicated.

        Order is preserved (it is the consultation priority), repeats are not.
        """
        return tuple(dict.fromkeys(provider.lower() for provider in _split_csv(self.enabled_providers)))

    @property
    def manufacturer_domain_list(self) -> tuple[str, ...]:
        return tuple(domain.lower() for domain in _split_csv(self.manufacturer_domains))

    @property
    def material_category_list(self) -> tuple[str, ...]:
        return _split_csv(self.material_categories)

    @property
    def ocr_language_list(self) -> tuple[str, ...]:
        return _split_csv(self.ocr_languages)

    @property
    def spreadsheet_suffixes(self) -> tuple[str, ...]:
        return SUPPORTED_SPREADSHEET_SUFFIXES

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def column_aliases(self) -> dict[str, tuple[str, ...]]:
        """Header-alias table, with ``MVAI_COLUMN_ALIASES_JSON`` merged on top.

        Overrides are *additive*: an operator extending ``material_code`` keeps
        every built-in alias, which is what people actually want when a new ERP
        export renames one column.
        """
        merged: dict[str, tuple[str, ...]] = {
            field: tuple(aliases) for field, aliases in DEFAULT_COLUMN_ALIASES.items()
        }
        if not self.column_aliases_json.strip():
            return merged

        overrides: dict[str, Any] = json.loads(self.column_aliases_json)
        for field, aliases in overrides.items():
            if field in merged:
                merged[field] = merged[field] + tuple(aliases)
            else:  # pragma: no cover - guarded by the validator above
                merged[field] = tuple(aliases)
        return merged

    @property
    def confidence_weights(self) -> dict[str, float]:
        """Normalised scoring weights; always sums to 1.0 (or all zeros)."""
        raw = {
            "ocr": self.weight_ocr,
            "vision": self.weight_vision,
            "brand": self.weight_brand,
            "model": self.weight_model,
            "text": self.weight_text,
            "provider": self.weight_provider,
        }
        total = sum(raw.values())
        if total <= 0:
            return raw
        return {name: value / total for name, value in raw.items()}

    def ensure_directories(self) -> None:
        """Create every runtime directory.

        Safe to call repeatedly.  Also materialises the ``image-library``
        taxonomy so a fresh clone has the documented folder tree.
        """
        for directory in (
            self.uploads_dir,
            self.exports_dir,
            self.image_cache_dir,
            self.image_library_dir,
            self.logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        for category in self.material_category_list:
            (self.image_library_dir / category).mkdir(parents=True, exist_ok=True)

        if self.database_url.startswith("sqlite"):
            db_path = self.database_url.split("///", 1)[-1]
            if db_path and db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def redacted(self) -> dict[str, Any]:
        """Settings dump with secrets masked - safe for the settings endpoint."""
        secret_fields = {
            "secret_key",
            "redis_url",
            "s3_access_key_id",
            "s3_secret_access_key",
            "openai_api_key",
            "google_api_key",
            "bing_api_key",
            "serpapi_api_key",
            "google_cse_id",
            "database_url",
            "first_superuser_password",
        }
        dump = self.model_dump(mode="json")
        for field in secret_fields:
            value = dump.get(field)
            if value:
                dump[field] = "***configured***"
        return dump


def _split_csv(raw: str) -> tuple[str, ...]:
    """Split a comma-separated setting into trimmed, non-empty parts."""
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Memoised deliberately: settings are read on every request, and re-parsing
    the environment each time would be wasteful.  Tests call
    ``get_settings.cache_clear()`` after mutating the environment.
    """
    return Settings()
