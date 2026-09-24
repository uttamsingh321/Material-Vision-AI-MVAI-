"""ORM models.

Importing this package registers every mapper on ``Base.metadata``, which is
what :func:`app.database.session.init_models` and Alembic's autogenerate both
rely on.  Always import models through here rather than by module path, so the
mapping is guaranteed to be complete before ``create_all`` runs.
"""

from __future__ import annotations

from app.models.audit_log import AuditLog
from app.models.confidence_score import ConfidenceScore
from app.models.duplicate import Duplicate
from app.models.image import MaterialImage
from app.models.manufacturer import Manufacturer
from app.models.material import Material
from app.models.processing_job import ProcessingJob
from app.models.review_queue import ReviewQueueItem
from app.models.search_result import SearchResult
from app.models.user import User

__all__ = [
    "AuditLog",
    "ConfidenceScore",
    "Duplicate",
    "Manufacturer",
    "Material",
    "MaterialImage",
    "ProcessingJob",
    "ReviewQueueItem",
    "SearchResult",
    "User",
]