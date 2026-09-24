"""ORM mapping tests: schema shape, defaults, relationships and cascades."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.database.base import Base
from app.models import (
    AuditLog,
    ConfidenceScore,
    Duplicate,
    ExportHistory,
    ImageLibraryItem,
    Manufacturer,
    Material,
    MaterialImage,
    ProcessingJob,
    ProcessingLog,
    ProviderHistory,
    ReviewQueueItem,
    SearchResult,
    User,
)
from app.models.enums import (
    LOG_LEVEL_RANKS,
    AuditAction,
    ConfidenceBand,
    Decision,
    DuplicateMethod,
    ExportFormat,
    ExportStatus,
    ImageStatus,
    JobStatus,
    JobType,
    LogLevel,
    MaterialStatus,
    ProviderKind,
    ReviewReason,
    ReviewStatus,
    Role,
)

EXPECTED_TABLES = {
    "audit_logs",
    "confidence_scores",
    "duplicates",
    "export_history",
    "image_library",
    "images",
    "manufacturers",
    "materials",
    "processing_jobs",
    "processing_logs",
    "provider_history",
    "review_queue",
    "search_results",
    "users",
}


def test_every_documented_table_is_mapped() -> None:
    assert EXPECTED_TABLES == set(Base.metadata.tables)


async def _make_material(db_session, **overrides):  # noqa: ANN001, ANN202
    """Insert a minimal, valid material and return the flushed instance."""
    defaults = {
        "batch_id": "00000000-0000-0000-0000-000000000001",
        "batch_name": "sample.xlsx",
        "source_filename": "sample.xlsx",
        "source_sheet": "Sheet1",
        "row_number": 2,
        "material_code": "MC-1001",
        "description": "Schneider LC1D18 contactor 18A 230VAC coil",
        "brand": "Schneider",
        "model": "LC1D18",
    }
    material = Material(**{**defaults, **overrides})
    db_session.add(material)
    await db_session.flush()
    return material


async def test_material_defaults_to_pending_and_uncategorised(db_session) -> None:
    material = await _make_material(db_session)

    assert material.status is MaterialStatus.PENDING
    assert material.category == "Uncategorised"
    assert material.extra == {}
    assert material.image_count == 0
    assert material.attempts == 0
    assert material.created_at is not None


async def test_timestamps_are_timezone_aware_utc(db_session) -> None:
    material = await _make_material(db_session)
    await db_session.refresh(material)

    assert material.created_at.tzinfo is not None
    assert material.created_at.utcoffset().total_seconds() == 0


async def test_material_extra_payload_round_trips(db_session) -> None:
    material = await _make_material(
        db_session, extra={"Bin": "A-12", "Re-order": 25}, row_number=3
    )
    await db_session.flush()
    # ``refresh`` re-selects the row through the async session; ``expire`` alone
    # would defer IO to a plain attribute access, which async SQLAlchemy rejects.
    await db_session.refresh(material)

    assert material.extra == {"Bin": "A-12", "Re-order": 25}


async def test_batch_and_row_number_are_unique(db_session) -> None:
    await _make_material(db_session, row_number=10)

    with pytest.raises(IntegrityError):
        await _make_material(db_session, row_number=10)
    await db_session.rollback()


async def test_display_label_prefers_material_code(db_session) -> None:
    material = await _make_material(db_session, row_number=20)
    assert material.display_label.startswith("MC-1001:")

    without_code = await _make_material(db_session, row_number=21, material_code=None)
    assert without_code.display_label.startswith("row 21:")


async def test_search_result_and_image_link_to_material(db_session) -> None:
    material = await _make_material(db_session, row_number=30)
    result = SearchResult(
        material_id=material.id,
        provider="digikey",
        provider_kind=ProviderKind.DISTRIBUTOR,
        position=1,
        image_url="https://example.test/a.jpg",
        page_url="https://example.test/product",
        raw={"sponsored": False},
    )
    db_session.add(result)
    await db_session.flush()

    image = MaterialImage(
        material_id=material.id,
        search_result_id=result.id,
        filename="abc123.jpg",
        storage_path="cache/ab/abc123.jpg",
        status=ImageStatus.DOWNLOADED,
    )
    db_session.add(image)
    await db_session.flush()
    await db_session.refresh(material)

    assert [r.provider for r in material.search_results] == ["digikey"]
    assert [i.filename for i in material.images] == ["abc123.jpg"]
    assert material.images[0].library_relative_path == "cache/ab/abc123.jpg"


async def test_accepted_image_property_resolves_soft_reference(db_session) -> None:
    material = await _make_material(db_session, row_number=40)
    image = MaterialImage(
        material_id=material.id,
        filename="winner.png",
        storage_path="cache/winner.png",
        is_accepted=True,
    )
    db_session.add(image)
    await db_session.flush()

    material.accepted_image_id = image.id
    await db_session.flush()
    await db_session.refresh(material)

    assert material.accepted_image is not None
    assert material.accepted_image.filename == "winner.png"


async def test_accepted_image_property_is_none_without_reference(db_session) -> None:
    assert (await _make_material(db_session, row_number=41)).accepted_image is None


async def test_image_rejection_helper_flags_statuses(db_session) -> None:
    material = await _make_material(db_session, row_number=50)
    rejected = MaterialImage(
        material_id=material.id,
        filename="bad.jpg",
        storage_path="cache/bad.jpg",
        status=ImageStatus.REJECTED,
    )
    duplicate = MaterialImage(
        material_id=material.id,
        filename="dupe.jpg",
        storage_path="cache/dupe.jpg",
        status=ImageStatus.DUPLICATE,
    )
    ok = MaterialImage(
        material_id=material.id,
        filename="fine.jpg",
        storage_path="cache/fine.jpg",
        status=ImageStatus.ACCEPTED,
    )
    db_session.add_all([rejected, duplicate, ok])
    await db_session.flush()

    assert rejected.is_rejected is True
    assert duplicate.is_rejected is True
    assert ok.is_rejected is False


async def test_deleting_material_cascades_to_children(db_session) -> None:
    material = await _make_material(db_session, row_number=60)
    material_id = material.id

    result = SearchResult(material_id=material_id, provider="bing", position=0)
    db_session.add(result)
    await db_session.flush()

    image = MaterialImage(
        material_id=material_id,
        search_result_id=result.id,
        filename="child.jpg",
        storage_path="cache/child.jpg",
    )
    db_session.add(image)
    await db_session.flush()

    db_session.add(ConfidenceScore(material_id=material_id, image_id=image.id, overall=0.9))
    db_session.add(
        ReviewQueueItem(
            material_id=material_id, image_id=image.id, reason=ReviewReason.LOW_CONFIDENCE
        )
    )
    await db_session.flush()

    await db_session.delete(material)
    await db_session.flush()

    for model in (SearchResult, MaterialImage, ConfidenceScore, ReviewQueueItem):
        remaining = await db_session.scalar(select(func.count()).select_from(model))
        assert remaining == 0, f"{model.__name__} rows survived the cascade"


async def test_duplicate_records_retain_canonical_image(db_session) -> None:
    material = await _make_material(db_session, row_number=70)
    canonical = MaterialImage(
        material_id=material.id, filename="canonical.jpg", storage_path="cache/c.jpg"
    )
    copy = MaterialImage(
        material_id=material.id, filename="copy.jpg", storage_path="cache/copy.jpg"
    )
    db_session.add_all([canonical, copy])
    await db_session.flush()

    duplicate = Duplicate(
        material_id=material.id,
        image_id=copy.id,
        duplicate_of_image_id=canonical.id,
        method=DuplicateMethod.SHA256,
        similarity=1.0,
    )
    db_session.add(duplicate)
    await db_session.flush()

    assert duplicate.similarity == 1.0
    assert duplicate.method is DuplicateMethod.SHA256


async def test_confidence_score_persists_weight_breakdown(db_session) -> None:
    material = await _make_material(db_session, row_number=80)
    score = ConfidenceScore(
        material_id=material.id,
        overall=0.83,
        band=ConfidenceBand.HIGH,
        decision=Decision.AUTO_ACCEPT,
        ocr_score=0.9,
        vision_score=0.8,
        weights={"ocr": 0.3, "vision": 0.3},
        contributions={"ocr": 0.27, "vision": 0.24},
        missing_signals=["provider"],
    )
    db_session.add(score)
    await db_session.flush()
    await db_session.refresh(score)

    assert score.weights == {"ocr": 0.3, "vision": 0.3}
    assert score.missing_signals == ["provider"]
    assert score.decision is Decision.AUTO_ACCEPT


async def test_processing_job_progress_helpers(db_session) -> None:
    job = ProcessingJob(
        job_type=JobType.PROCESS_BATCH,
        batch_id="00000000-0000-0000-0000-000000000002",
        total_items=10,
        processed_items=4,
    )
    db_session.add(job)
    await db_session.flush()

    assert job.status is JobStatus.QUEUED
    assert job.is_resumable is True
    assert job.remaining_items() == 6
    assert job.cancel_requested is False
    assert job.pause_requested is False


async def test_processing_job_remaining_items_never_negative(db_session) -> None:
    job = ProcessingJob(job_type=JobType.PRUNE_CACHE, total_items=2, processed_items=5)
    db_session.add(job)
    await db_session.flush()

    assert job.remaining_items() == 0


def test_job_status_activity_flags() -> None:
    assert JobStatus.SUCCEEDED.is_final is True
    assert JobStatus.SUCCEEDED.is_active is False
    assert JobStatus.RUNNING.is_active is True
    assert JobStatus.PAUSED.is_active is True


def test_material_status_terminal_flags() -> None:
    assert MaterialStatus.MATCHED.is_terminal is True
    assert MaterialStatus.FAILED.is_terminal is True
    # A material awaiting review is not "done" - something must still act on it.
    assert MaterialStatus.NEEDS_REVIEW.is_terminal is False


async def test_user_role_helpers(db_session) -> None:
    admin = User(
        email="admin@mvai.test", hashed_password="x", role=Role.ADMIN, is_superuser=False
    )
    viewer = User(email="viewer@mvai.test", hashed_password="x", role=Role.VIEWER)
    db_session.add_all([admin, viewer])
    await db_session.flush()

    assert admin.is_admin is True
    assert viewer.is_admin is False
    assert "admin@mvai.test" in str(admin)


async def test_user_email_is_unique(db_session) -> None:
    db_session.add(User(email="dup@mvai.test", hashed_password="x"))
    await db_session.flush()

    db_session.add(User(email="dup@mvai.test", hashed_password="y"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_review_queue_item_defaults(db_session) -> None:
    material = await _make_material(db_session, row_number=90)
    item = ReviewQueueItem(
        material_id=material.id, reason=ReviewReason.AMBIGUOUS_MATCH, priority=5
    )
    db_session.add(item)
    await db_session.flush()

    assert item.status is ReviewStatus.PENDING
    assert item.priority == 5
    assert ReviewStatus.PENDING.is_open is True
    assert ReviewStatus.APPROVED.is_open is False


async def test_audit_log_survives_user_deletion(db_session) -> None:
    """The trail must outlive the account it refers to."""
    user = User(email="leaver@mvai.test", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        AuditLog(
            actor_id=user.id,
            actor_email=user.email,
            action=AuditAction.LOGIN,
            entity_type="user",
            entity_id=str(user.id),
            request_id="req-1",
        )
    )
    await db_session.flush()

    await db_session.delete(user)
    await db_session.flush()

    log = await db_session.scalar(select(AuditLog))
    assert log is not None
    assert log.actor_email == "leaver@mvai.test"
    assert log.actor_id is None


async def test_manufacturer_registry_fields(db_session) -> None:
    manufacturer = Manufacturer(
        name="Schneider Electric",
        slug="schneider-electric",
        website="https://www.se.com",
        search_domain="se.com",
        priority=10,
    )
    db_session.add(manufacturer)
    await db_session.flush()

    assert manufacturer.is_active is True
    assert manufacturer.priority == 10
    assert str(manufacturer) == "Schneider Electric"


# ---------------------------------------------------------------------------
# Wave 1: image library, provider history, processing logs, export history
# ---------------------------------------------------------------------------


async def test_image_library_item_defaults_and_path(db_session) -> None:
    item = ImageLibraryItem(
        category="Electrical",
        library_path="Electrical/contactor.png",
        filename="contactor.png",
        sha256="a" * 64,
        material_code="MC-1001",
        description="Schneider LC1D18 contactor",
    )
    db_session.add(item)
    await db_session.flush()

    assert item.category == "Electrical"
    assert item.material_id is None, "library rows outlive their batch"
    assert item.image_id is None
    assert str(item) == "<ImageLibraryItem Electrical/contactor.png>"


async def test_image_library_category_is_queryable(db_session) -> None:
    for category in ("Electrical", "Electrical", "Chemical"):
        db_session.add(
            ImageLibraryItem(category=category, library_path=f"{category}/x.png", filename="x.png")
        )
    await db_session.flush()

    count = await db_session.scalar(
        select(func.count())
        .select_from(ImageLibraryItem)
        .where(ImageLibraryItem.category == "Electrical")
    )
    assert count == 2


async def test_provider_history_records_outcome(db_session) -> None:
    history = ProviderHistory(
        provider="mock",
        provider_kind=ProviderKind.IMAGE_SEARCH,
        query="schneider lc1d18",
        outcome="ok",
        result_count=15,
        accepted_count=4,
        latency_ms=120,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(history)
    await db_session.flush()

    assert history.failure_streak == 0
    assert history.detail == {}
    assert history.finished_at is None
    assert str(history) == "<ProviderHistory mock ok>"


async def test_provider_history_outcome_and_provider_are_indexed(db_session) -> None:
    for outcome in ("ok", "error", "error"):
        db_session.add(
            ProviderHistory(
                provider="bing_images",
                outcome=outcome,
                started_at=datetime.now(timezone.utc),
            )
        )
    await db_session.flush()

    errors = await db_session.scalar(
        select(func.count())
        .select_from(ProviderHistory)
        .where(
            ProviderHistory.outcome == "error",
            ProviderHistory.provider == "bing_images",
        )
    )
    assert errors == 2


async def test_processing_log_persists_context(db_session) -> None:
    log = ProcessingLog(
        timestamp=datetime.now(timezone.utc),
        level=LogLevel.WARNING,
        logger="app.services.search_pipeline",
        message="provider returned no results",
        job_id=7,
        batch_id="00000000-0000-0000-0000-000000000009",
        provider="mock",
        context={"query": "skf 6205", "attempt": 2},
    )
    db_session.add(log)
    await db_session.flush()

    assert log.level == LogLevel.WARNING
    assert log.context["attempt"] == 2
    assert str(log).startswith("<ProcessingLog warning")


async def test_processing_log_level_filter(db_session) -> None:
    for level in (LogLevel.DEBUG, LogLevel.INFO, LogLevel.ERROR):
        db_session.add(
            ProcessingLog(
                timestamp=datetime.now(timezone.utc), level=level, message=f"{level} message"
            )
        )
    await db_session.flush()

    # Enum values are stored as strings, so severity comparison must go
    # through LOG_LEVEL_RANKS rather than a lexicographic ``>=``.
    levels = (await db_session.scalars(select(ProcessingLog))).all()
    serious = [entry for entry in levels if entry.level.rank >= LogLevel.WARNING.rank]
    assert len(serious) == 1
    assert serious[0].level is LogLevel.ERROR


async def test_export_history_lifecycle(db_session) -> None:
    export = ExportHistory(
        batch_id="00000000-0000-0000-0000-00000000000a",
        filename="batch-export.xlsx",
        storage_path="batch-export.xlsx",
        format=ExportFormat.XLSX,
        status=ExportStatus.PENDING,
        row_count=5,
    )
    db_session.add(export)
    await db_session.flush()

    assert export.is_available is False
    export.status = ExportStatus.COMPLETED
    export.byte_size = 2048
    await db_session.flush()
    assert export.is_available is True


async def test_export_history_failed_is_terminal_not_available(db_session) -> None:
    export = ExportHistory(filename="broken.xlsx", status=ExportStatus.FAILED, error="disk full")
    db_session.add(export)
    await db_session.flush()

    assert export.status.is_terminal is True
    assert export.is_available is False
    assert export.storage_path is None


def test_log_level_rank_orders_severities() -> None:
    assert LogLevel.CRITICAL.rank > LogLevel.ERROR.rank > LogLevel.WARNING.rank
    assert LogLevel.INFO.rank > LogLevel.DEBUG.rank
    assert LOG_LEVEL_RANKS[LogLevel.INFO] == 20


def test_export_status_terminal_set() -> None:
    assert ExportStatus.COMPLETED.is_terminal is True
    assert ExportStatus.FAILED.is_terminal is True
    assert ExportStatus.PENDING.is_terminal is False
    assert ExportStatus.RUNNING.is_terminal is False

