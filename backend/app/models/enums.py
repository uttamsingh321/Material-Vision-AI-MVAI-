"""Enumerations persisted in the database.

Every enum mixes in :class:`enum.StrEnum` so values serialise cleanly to JSON
and can be stored either as ``VARCHAR`` (portable across SQLite/PostgreSQL) or
as a native database enum, depending on
:attr:`app.config.settings.Settings.db_native_enums`.

The string *values* - not the member names - are the persisted contract.
Rename a member freely; never change its value without a migration.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Coarse-grained authorisation roles, ordered by capability."""

    VIEWER = "viewer"
    REVIEWER = "reviewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class MaterialStatus(StrEnum):
    """Lifecycle of a single material row, from ingestion to disposition."""

    PENDING = "pending"
    PARSED = "parsed"
    QUEUED = "queued"
    SEARCHING = "searching"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    MATCHED = "matched"
    NEEDS_REVIEW = "needs_review"
    NOT_FOUND = "not_found"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def is_terminal(self) -> bool:
        """``True`` when no further automatic work will touch this material."""
        return self in MATERIAL_TERMINAL_STATUSES


MATERIAL_TERMINAL_STATUSES: frozenset[MaterialStatus] = frozenset(
    {
        MaterialStatus.MATCHED,
        MaterialStatus.NOT_FOUND,
        MaterialStatus.FAILED,
        MaterialStatus.SKIPPED,
    }
)

#: Statuses counted as "completed" on the dashboard.  ``NEEDS_REVIEW`` is
#: deliberately excluded here - it is surfaced by the review-queue card.
DASHBOARD_COMPLETED_STATUSES: frozenset[MaterialStatus] = frozenset(
    {
        MaterialStatus.MATCHED,
        MaterialStatus.NOT_FOUND,
        MaterialStatus.FAILED,
        MaterialStatus.SKIPPED,
        MaterialStatus.NEEDS_REVIEW,
    }
)

#: Statuses that mean "an image was successfully associated".
MATCHED_STATUSES: frozenset[MaterialStatus] = frozenset({MaterialStatus.MATCHED})


class ImageStatus(StrEnum):
    """Disposition of a candidate image."""

    CANDIDATE = "candidate"
    DOWNLOADED = "downloaded"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    ERROR = "error"


class RejectionReason(StrEnum):
    """Why a candidate was discarded.  An enum so reports can group on it."""

    THUMBNAIL = "thumbnail"
    WATERMARK = "watermark"
    TOO_SMALL = "too_small"
    DUPLICATE_HASH = "duplicate_hash"
    DUPLICATE_PERCEPTUAL = "duplicate_perceptual"
    UNSUPPORTED_TYPE = "unsupported_type"
    DOWNLOAD_FAILED = "download_failed"
    OCR_MISMATCH = "ocr_mismatch"
    VISION_REJECTED = "vision_rejected"
    LOW_CONFIDENCE = "low_confidence"
    BROKEN_IMAGE = "broken_image"
    MANUAL = "manual"


class ProviderKind(StrEnum):
    """Search provider families, used for rate-limit buckets and reporting."""

    MANUFACTURER = "manufacturer"
    DISTRIBUTOR = "distributor"
    MARKETPLACE = "marketplace"
    WEB_SEARCH = "web_search"
    IMAGE_SEARCH = "image_search"
    INTERNAL = "internal"


class JobType(StrEnum):
    """What a background job actually does."""

    INGEST_EXCEL = "ingest_excel"
    PROCESS_BATCH = "process_batch"
    PROCESS_MATERIAL = "process_material"
    RETRY_FAILED = "retry_failed"
    EXPORT_BATCH = "export_batch"
    PRUNE_CACHE = "prune_cache"


class JobStatus(StrEnum):
    """Job lifecycle.  ``QUEUED``/``RUNNING``/``PAUSED`` are resumable."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    COMPLETED = "completed"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RECOVERING = "recovering"
    RETRYING = "retrying"

    @property
    def is_active(self) -> bool:
        """``True`` while the job may still be picked up by a worker."""
        return self in JOB_ACTIVE_STATUSES

    @property
    def is_final(self) -> bool:
        """``True`` when the job will never be picked up again."""
        return not self.is_active


JOB_ACTIVE_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.RECOVERING, JobStatus.RETRYING}
)

#: Jobs found in these states at start-up are re-queued by the recovery sweep.
JOB_RECOVERABLE_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.RECOVERING, JobStatus.RETRYING}
)


class ReviewStatus(StrEnum):
    """State of a human-review item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    AUTO_RESOLVED = "auto_resolved"

    @property
    def is_open(self) -> bool:
        """``True`` while the item still needs a human decision."""
        return self in OPEN_REVIEW_STATUSES


OPEN_REVIEW_STATUSES: frozenset[ReviewStatus] = frozenset(
    {ReviewStatus.PENDING, ReviewStatus.IN_PROGRESS, ReviewStatus.ESCALATED}
)


class ReviewReason(StrEnum):
    """Why an item entered the review queue."""

    LOW_CONFIDENCE = "low_confidence"
    AMBIGUOUS_MATCH = "ambiguous_match"
    NO_CANDIDATE = "no_candidate"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    OCR_MISMATCH = "ocr_mismatch"
    DOUBTFUL_SOURCE = "doubtful_source"
    MANUAL_REQUEST = "manual_request"


class Decision(StrEnum):
    """Machine verdict attached to a confidence score."""

    AUTO_ACCEPT = "auto_accept"
    REVIEW = "review"
    REJECT = "reject"


class ConfidenceBand(StrEnum):
    """Coarse bucket used by the dashboard and reports."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class DuplicateMethod(StrEnum):
    """How a duplicate relationship was detected."""

    SHA256 = "sha256"
    PERCEPTUAL_HASH = "perceptual_hash"
    SOURCE_URL = "source_url"
    MANUAL = "manual"


class ExportFormat(StrEnum):
    """Supported export payloads."""

    XLSX = "xlsx"
    CSV = "csv"
    JSON = "json"
    ZIP = "zip"
    REPORT = "report"


class ExportStatus(StrEnum):
    """Lifecycle of one export file generation."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """``True`` when the export will never be worked on again."""
        return self in {ExportStatus.COMPLETED, ExportStatus.FAILED}


class LogLevel(StrEnum):
    """Severity of a persisted processing-log entry."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Numeric severity, so a threshold check needs no mapping table."""
        return LOG_LEVEL_RANKS[self]


#: Ordered severity for :attr:`LogLevel.rank`.
LOG_LEVEL_RANKS: dict[LogLevel, int] = {
    LogLevel.DEBUG: 10,
    LogLevel.INFO: 20,
    LogLevel.WARNING: 30,
    LogLevel.ERROR: 40,
    LogLevel.CRITICAL: 50,
}


class AuditAction(StrEnum):
    """Security-relevant events written to ``audit_logs``."""

    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    TOKEN_REFRESH = "token_refresh"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DEACTIVATED = "user_deactivated"
    PASSWORD_CHANGED = "password_changed"
    UPLOAD_CREATED = "upload_created"
    JOB_STARTED = "job_started"
    JOB_PAUSED = "job_paused"
    JOB_RESUMED = "job_resumed"
    JOB_CANCELLED = "job_cancelled"
    JOB_RETRIED = "job_retried"
    REVIEW_APPROVED = "review_approved"
    REVIEW_REJECTED = "review_rejected"
    IMAGE_ACCEPTED = "image_accepted"
    IMAGE_REJECTED = "image_rejected"
    EXPORT_CREATED = "export_created"
    SETTINGS_UPDATED = "settings_updated"
    API_KEY_UPDATED = "api_key_updated"
