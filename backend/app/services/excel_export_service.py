"""Excel export service: assemble result rows, write the workbook, record history.

One call produces the operator's deliverable for a batch:

1. Load every :class:`~app.models.material.Material` in the batch and resolve
   its accepted image (file name, source page, confidence).
2. Hand the rows plus the retained source workbook to
   :class:`app.services.workbook_writer.WorkbookWriter`, which appends the ten
   ``MVAI ...`` columns.
3. Write the result atomically under ``exports/<batch_id>/`` and append an
   :class:`app.models.export_history.ExportHistory`` row with size, digest and
   row count - so the UI can list past exports and re-serve them without
   regenerating anything.
4. Emit an ``EXPORT_CREATED`` audit row and a processing-log line.

Failure handling: the ``ExportHistory`` row is only written once the file is
safely on disk, so a half-done export never masquerades as available; callers
see the underlying exception and no audit/log trail is recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.config.logging import get_logger
from app.models.enums import AuditAction, ExportFormat, ExportStatus
from app.models.export_history import ExportHistory
from app.models.image import MaterialImage
from app.models.material import Material
from app.services.audit import get_audit_logger, get_processing_logger
from app.services.upload_service import UploadService
from app.services.workbook_writer import ExportRow, WorkbookWriter
from app.utils.files import atomic_write_bytes, ensure_within, relative_posix, safe_filename
from app.utils.hashing import sha256_bytes
from app.utils.text import slugify

logger = get_logger(__name__)


class ExportRejectedError(ValueError):
    """The requested batch does not exist (or has no materials)."""


@dataclass(frozen=True, slots=True)
class ExportOutcome:
    """The generated artifact plus its history row id."""

    history_id: int
    batch_id: str
    filename: str
    #: POSIX path relative to ``exports/``.
    relative_path: str
    path: Path
    byte_size: int
    row_count: int
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "history_id": self.history_id,
            "batch_id": self.batch_id,
            "filename": self.filename,
            "relative_path": self.relative_path,
            "byte_size": self.byte_size,
            "row_count": self.row_count,
            "sha256": self.sha256,
        }


class ExcelExportService:
    """Builds, persists and records one processed-workbook export."""

    def __init__(
        self,
        *,
        writer: WorkbookWriter | None = None,
        uploads: UploadService | None = None,
    ) -> None:
        self.settings = get_settings()
        self.writer = writer or WorkbookWriter()
        self.uploads = uploads or UploadService()

    @property
    def exports_dir(self) -> Path:
        directory = self.settings.exports_dir
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    # ------------------------------------------------------------------
    # Row assembly
    # ------------------------------------------------------------------
    async def _load_materials(self, session: AsyncSession, batch_id: str) -> list[Material]:
        rows = (
            await session.execute(
                select(Material)
                .where(Material.batch_id == batch_id)
                .order_by(Material.row_number)
            )
        ).scalars().all()
        if not rows:
            raise ExportRejectedError(f"batch {batch_id!r} has no materials to export")
        return list(rows)

    async def _build_export_rows(
        self, session: AsyncSession, materials: list[Material]
    ) -> list[ExportRow]:
        image_ids = [
            material.accepted_image_id
            for material in materials
            if material.accepted_image_id is not None
        ]
        images: dict[int, MaterialImage] = {}
        if image_ids:
            found = (
                await session.execute(select(MaterialImage).where(MaterialImage.id.in_(image_ids)))
            ).scalars().all()
            images = {image.id: image for image in found}

        export_rows: list[ExportRow] = []
        for material in materials:
            image = images.get(material.accepted_image_id or -1)
            export_rows.append(
                ExportRow(
                    row_number=material.row_number,
                    material_code=material.material_code,
                    description=material.description,
                    brand=material.brand,
                    model=material.model,
                    category=material.category,
                    unit=material.unit,
                    quantity=material.quantity,
                    location=material.location,
                    remarks=material.remarks,
                    status=str(material.status),
                    image_file=image.library_relative_path if image else None,
                    image_count=material.image_count,
                    confidence=material.confidence,
                    image_source=image.source_domain if image else None,
                    source_page=image.source_page_url if image else None,
                    search_query=material.search_query,
                    last_error=material.last_error,
                    extra=dict(material.extra),
                )
            )
        return export_rows

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    async def export_batch(
        self,
        session: AsyncSession,
        batch_id: str,
        *,
        actor_id: int | None = None,
        actor_email: str | None = None,
        request_id: str | None = None,
        job_id: int | None = None,
    ) -> ExportOutcome:
        """Generate the processed workbook for ``batch_id`` and record it.

        Raises:
            ExportRejectedError: the batch has no materials.
        """
        materials = await self._load_materials(session, batch_id)
        export_rows = await self._build_export_rows(session, materials)
        source = self.uploads.read_source(batch_id)
        payload = self.writer.write(source, export_rows)

        batch_name = materials[0].batch_name or materials[0].source_filename or "export"
        filename = safe_filename(
            f"{slugify(batch_name, max_length=80, fallback='batch')}-processed.xlsx",
            fallback="export.xlsx",
        )
        directory = self.exports_dir / batch_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        atomic_write_bytes(path, payload)

        history = ExportHistory(
            batch_id=batch_id,
            batch_name=batch_name,
            job_id=job_id,
            format=ExportFormat.XLSX,
            status=ExportStatus.COMPLETED,
            filename=filename,
            storage_path=relative_posix(path, self.exports_dir),
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            byte_size=len(payload),
            sha256=sha256_bytes(payload),
            row_count=len(export_rows),
            include_images=False,
            created_by_id=actor_id,
            requested_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            detail={"source_retained": source is not None},
        )
        session.add(history)
        await session.flush()

        await get_audit_logger().record(
            session,
            AuditAction.EXPORT_CREATED,
            actor_id=actor_id,
            actor_email=actor_email,
            entity_type="export_history",
            entity_id=history.id,
            summary=f"exported {len(export_rows)} rows for batch {batch_id}",
            context={"batch_id": batch_id, "filename": filename},
            request_id=request_id,
        )
        await get_processing_logger().info(
            session,
            f"export completed: {filename} ({len(export_rows)} rows)",
            job_id=job_id,
            batch_id=batch_id,
            request_id=request_id,
        )

        outcome = ExportOutcome(
            history_id=history.id,
            batch_id=batch_id,
            filename=filename,
            relative_path=history.storage_path or "",
            path=path,
            byte_size=len(payload),
            row_count=len(export_rows),
            sha256=history.sha256 or "",
        )
        logger.info("export.completed", batch_id=batch_id, rows=outcome.row_count)
        return outcome

    # ------------------------------------------------------------------
    # Retrieval of past exports
    # ------------------------------------------------------------------
    async def get_history(self, session: AsyncSession, history_id: int) -> ExportHistory | None:
        return await session.get(ExportHistory, history_id)

    async def list_history(
        self,
        session: AsyncSession,
        *,
        batch_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ExportHistory], int]:
        """Newest-first page of export records, optionally per batch."""
        query = select(ExportHistory)
        if batch_id:
            query = query.where(ExportHistory.batch_id == batch_id)
        total = (
            await session.execute(select(func.count()).select_from(query.subquery()))
        ).scalar_one()
        rows = (
            await session.execute(
                query.order_by(ExportHistory.created_at.desc(), ExportHistory.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), int(total)

    def resolve_file(self, history: ExportHistory) -> Path:
        """Absolute path of a completed export (traversal-guarded)."""
        if not history.storage_path:
            raise ExportRejectedError(f"export {history.id} has no stored file")
        return ensure_within(self.exports_dir, history.storage_path)

    def read_file(self, history: ExportHistory) -> bytes:
        return self.resolve_file(history).read_bytes()


def excel_export_service() -> ExcelExportService:
    """An export service configured from the current settings."""
    return ExcelExportService()


__all__ = [
    "ExcelExportService",
    "ExportOutcome",
    "ExportRejectedError",
    "excel_export_service",
]



