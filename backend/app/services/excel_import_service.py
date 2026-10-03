"""Excel import service: turn validated workbook bytes into Material rows.

The parser (:mod:`app.services.excel_services.excel_parser` terminology:
header discovery, alias mapping, descriptor interpretation) does the hard work
of *understanding* a sheet; this service does the bookkeeping of *persisting*
it:

* one :class:`app.models.material.Material` per usable data row;
* every row stamped with the same ``batch_id`` (UUID), which becomes the
  grouping key for jobs, progress, review and export;
* status set to ``PARSED`` - the row is understood but has not been searched;
* unmapped source columns preserved verbatim in ``Material.extra`` so nothing
  the operator recorded is ever lost.

Idempotency: re-importing the same workbook creates a *new* batch (new UUID),
so two uploads of the same file never collide on the
``(batch_id, row_number)`` unique constraint.  Within one import the parser
guarantees unique row numbers, so the constraint can never fire mid-write.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import get_logger
from app.models.enums import MaterialStatus
from app.models.material import Material
from app.services.excel_parser import SpreadsheetError, spreadsheet_parser

logger = get_logger(__name__)


class ImportRejectedError(ValueError):
    """The workbook parsed but produced no usable material rows."""


@dataclass(slots=True)
class ImportResult:
    """Summary of one completed import."""

    batch_id: str
    batch_name: str
    source_filename: str
    sheet_name: str
    created: int = 0
    invalid_rows: int = 0
    blank_rows: int = 0
    warnings: list[str] = field(default_factory=list)
    material_ids: list[int] = field(default_factory=list)
    headers: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "batch_name": self.batch_name,
            "source_filename": self.source_filename,
            "sheet_name": self.sheet_name,
            "created": self.created,
            "invalid_rows": self.invalid_rows,
            "blank_rows": self.blank_rows,
            "warnings": list(self.warnings),
            "headers": list(self.headers),
        }


class ExcelImportService:
    """Parse a workbook and persist its rows as materials."""

    def __init__(self, parser: Any = None) -> None:
        self._parser = parser

    @property
    def parser(self) -> Any:
        if self._parser is None:
            self._parser = spreadsheet_parser()
        return self._parser

    async def import_payload(
        self,
        session: AsyncSession,
        payload: bytes,
        filename: str,
        *,
        batch_id: str | None = None,
        batch_name: str | None = None,
        sheet_name: str | None = None,
    ) -> ImportResult:
        """Parse ``payload`` and insert one Material per usable row.

        Raises:
            app.services.excel_parser.SpreadsheetError: unreadable workbook.
            ImportRejectedError: parsed fine but nothing usable remains.
        """
        result = self.parser.parse_bytes(payload, filename=filename, sheet_name=sheet_name)
        if not result.rows:
            raise ImportRejectedError(
                f"{filename} contains no usable material rows "
                f"({len(result.invalid_rows)} invalid, {result.blank_rows} blank)"
            )

        batch = batch_id or str(uuid.uuid4())
        materials: list[Material] = []
        for row in result.rows:
            materials.append(
                Material(
                    batch_id=batch,
                    batch_name=batch_name or filename,
                    source_filename=filename,
                    source_sheet=result.sheet_name,
                    row_number=row.row_number,
                    material_code=row.material_code,
                    description=row.description,
                    brand=row.brand,
                    model=row.model,
                    category=row.category,
                    unit=row.unit,
                    quantity=row.quantity,
                    location=row.location,
                    remarks=row.remarks,
                    extra=dict(row.extra),
                    status=MaterialStatus.PARSED,
                )
            )

        session.add_all(materials)
        await session.flush()

        outcome = ImportResult(
            batch_id=batch,
            batch_name=batch_name or filename,
            source_filename=filename,
            sheet_name=result.sheet_name,
            created=len(materials),
            invalid_rows=len(result.invalid_rows),
            blank_rows=result.blank_rows,
            warnings=list(result.warnings),
            material_ids=[material.id for material in materials],
            headers=tuple(column.header_text for column in result.columns),
        )
        logger.info(
            "excel.imported",
            batch_id=batch,
            created=outcome.created,
            invalid=outcome.invalid_rows,
            sheet=result.sheet_name,
        )
        return outcome


def excel_import_service() -> ExcelImportService:
    """An import service using the settings-configured parser."""
    return ExcelImportService()


__all__ = ["ExcelImportService", "ImportRejectedError", "ImportResult", "excel_import_service"]
