"""Workbook ingestion: locate the header row, map columns, emit material rows.

Real material masters are messy.  They carry title blocks above the table, use
one of a dozen spellings for the same column, and sprinkle extra columns that
the pipeline has no canonical field for.  This module handles all three:

* **Header discovery** - the first ``header_scan_rows`` rows are scored by how
  many canonical fields they resolve, and the best-scoring row that contains the
  mandatory fields wins.  A title block therefore never becomes the header.
* **Alias mapping** - headers are normalised and matched against the alias table
  from :mod:`app.config.constants`, which operators can extend by configuration.
* **Lossless extras** - every column with no canonical mapping is preserved
  verbatim in ``extra``, so nothing from the operator's workbook is discarded.

Reading is single-pass: the first ``header_scan_rows`` rows are buffered (that
is how the header is found), then the remainder streams straight off the
worksheet, which keeps memory flat on a 100k-row file.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from io import BytesIO
from itertools import chain
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from app import ai_engine
from app.config import get_settings
from app.config.constants import CANONICAL_MATERIAL_FIELDS, REQUIRED_MATERIAL_FIELDS
from app.config.logging import get_logger
from app.utils.text import clean_text, normalise_header, parse_float

logger = get_logger(__name__)

#: Header value stored when the located header row has no usable cell.
_NO_HEADER_ROW = 0


class SpreadsheetError(Exception):
    """The workbook could not be interpreted."""


class MissingColumnsError(SpreadsheetError):
    """A mandatory column could not be located in the sheet."""


@dataclass(frozen=True, slots=True)
class ColumnMapping:
    """A resolved canonical field and where it came from."""

    field: str
    column_index: int
    header_text: str


@dataclass(frozen=True, slots=True)
class _ColumnLayout:
    """Resolved column positions for one worksheet.

    ``by_field`` and ``extra_columns`` hold *zero-based* offsets, because they
    index into the raw row tuple; ``ColumnMapping.column_index`` is one-based so
    it can be shown to a user as a spreadsheet column number.
    """

    columns: tuple[ColumnMapping, ...]
    by_field: Mapping[str, int]
    extra_columns: tuple[tuple[str, int], ...]
    unmapped_headers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParsedMaterialRow:
    """One usable data row, already interpreted by the description parser."""

    row_number: int
    description: str
    descriptor: Any  # ai-engine MaterialDescriptor
    material_code: str | None = None
    brand: str | None = None
    model: str | None = None
    category: str | None = None
    unit: str | None = None
    quantity: float | None = None
    location: str | None = None
    remarks: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def values(self) -> dict[str, Any]:
        """Canonical field -> value, ignoring the interpreted descriptor."""
        return {
            "material_code": self.material_code,
            "description": self.description,
            "brand": self.brand,
            "model": self.model,
            "category": self.category,
            "unit": self.unit,
            "quantity": self.quantity,
            "location": self.location,
            "remarks": self.remarks,
        }


@dataclass(frozen=True, slots=True)
class InvalidRow:
    """A data row that had content but could not be ingested."""

    row_number: int
    reason: str
    values: dict[str, Any]


@dataclass(slots=True)
class SheetParseResult:
    """Everything the ingestion service needs to create materials."""

    filename: str
    sheet_name: str
    sheet_names: tuple[str, ...]
    header_row: int
    columns: tuple[ColumnMapping, ...]
    unmapped_headers: tuple[str, ...]
    rows: list[ParsedMaterialRow] = field(default_factory=list)
    invalid_rows: list[InvalidRow] = field(default_factory=list)
    blank_rows: int = 0
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def mapped_fields(self) -> tuple[str, ...]:
        return tuple(column.field for column in self.columns)

    @property
    def total_rows_scanned(self) -> int:
        """Data rows seen, whatever their outcome."""
        return len(self.rows) + len(self.invalid_rows) + self.blank_rows

    @property
    def is_usable(self) -> bool:
        return bool(self.rows)


@dataclass(frozen=True, slots=True)
class SpreadsheetParser:
    """Turns a workbook into :class:`ParsedMaterialRow` objects.

    Args:
        column_aliases: Logical field -> accepted header spellings.  Defaults to
            the setting-derived table, so ``MVAI_COLUMN_ALIASES_JSON`` is honoured
            automatically by :meth:`from_settings`.
        header_scan_rows: How many leading rows to consider for the header.
        max_rows: Hard ceiling on data rows, to bound a runaway import.
        strict_columns: Raise :class:`MissingColumnsError` instead of ingesting
            with the offending rows skipped.
        description_parser: Injectable interpreter for the description text.
    """

    column_aliases: Mapping[str, tuple[str, ...]]
    header_scan_rows: int = 15
    max_rows: int = 200_000
    strict_columns: bool = False
    description_parser: Any = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    @classmethod
    def from_settings(cls) -> SpreadsheetParser:
        """Build a parser from :func:`app.config.get_settings`."""
        settings = get_settings()
        return cls(
            column_aliases=settings.column_aliases,
            header_scan_rows=settings.excel_header_scan_rows,
            max_rows=settings.excel_max_rows,
            strict_columns=settings.excel_strict_columns,
            description_parser=ai_engine.description_parser().DescriptionParser(),
        )

    @property
    def _interpreter(self) -> Any:
        """The description parser, lazily defaulted so construction stays cheap."""
        if self.description_parser is None:
            return ai_engine.description_parser().parser
        return self.description_parser

    @property
    def _reverse_aliases(self) -> dict[str, str]:
        """Normalised alias -> logical field.

        Where two fields claim the same normalised alias the *first declared
        field in* :data:`CANONICAL_MATERIAL_FIELDS` wins, so the mapping is
        stable regardless of dictionary ordering.
        """
        index: dict[str, str] = {}
        for canonical_field in CANONICAL_MATERIAL_FIELDS:
            for alias in self.column_aliases.get(canonical_field, ()):
                index.setdefault(normalise_header(alias), canonical_field)
        return index

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def parse_file(
        self, path: str | Path, *, sheet_name: str | None = None
    ) -> SheetParseResult:
        """Parse a workbook from disk."""
        target = Path(path)
        if not target.is_file():
            raise SpreadsheetError(f"workbook not found: {target}")
        # ``read_only`` streams rows and keeps memory flat; ``data_only`` returns
        # cached formula results rather than the formula text.
        workbook = load_workbook(filename=target, read_only=True, data_only=True)
        try:
            return self._parse(workbook, filename=target.name, sheet_name=sheet_name)
        finally:
            workbook.close()

    def parse_bytes(
        self, payload: bytes, *, filename: str, sheet_name: str | None = None
    ) -> SheetParseResult:
        """Parse a workbook already held in memory (the upload path)."""
        if not payload:
            raise SpreadsheetError("workbook payload is empty")
        workbook = load_workbook(filename=BytesIO(payload), read_only=True, data_only=True)
        try:
            return self._parse(workbook, filename=filename, sheet_name=sheet_name)
        finally:
            workbook.close()

    # ------------------------------------------------------------------
    # Sheet selection and iteration
    # ------------------------------------------------------------------
    def _parse(
        self, workbook: Any, *, filename: str, sheet_name: str | None
    ) -> SheetParseResult:
        sheet_names = tuple(workbook.sheetnames)
        if not sheet_names:
            raise SpreadsheetError(f"{filename} contains no worksheets")

        requested = (sheet_name or get_settings().excel_sheet_name or "").strip()
        if requested and requested not in sheet_names:
            raise SpreadsheetError(
                f"worksheet {requested!r} not found in {filename}; "
                f"available: {list(sheet_names)}"
            )
        active = requested or sheet_names[0]
        worksheet: Worksheet = workbook[active]

        warnings: list[str] = []
        row_iterator = worksheet.iter_rows(values_only=True)

        # The header can only be found by looking at the leading rows, so those
        # are buffered; everything after them streams straight off the sheet.
        buffered: list[tuple[int, tuple[Any, ...]]] = []
        consumed = 0
        for index, values in enumerate(row_iterator, start=1):
            buffered.append((index, tuple(values)))
            consumed = index
            if index >= self.header_scan_rows:
                break

        header_row, header_values = self._locate_header(buffered)
        if header_row == _NO_HEADER_ROW:
            raise SpreadsheetError(
                f"no header row found in the first {self.header_scan_rows} rows of "
                f"worksheet {active!r} in {filename}"
            )

        layout = self._build_layout(header_values)
        missing = REQUIRED_MATERIAL_FIELDS - set(layout.by_field)
        if missing:
            message = (
                f"{active!r} has no column for: {', '.join(sorted(missing))}. "
                "Check the header spelling, or add an alias via "
                "MVAI_COLUMN_ALIASES_JSON."
            )
            if self.strict_columns:
                raise MissingColumnsError(message)
            warnings.append(message)

        result = SheetParseResult(
            filename=filename,
            sheet_name=active,
            sheet_names=sheet_names,
            header_row=header_row,
            columns=tuple(layout.columns),
            unmapped_headers=layout.unmapped_headers,
            warnings=warnings,
        )

        if missing:
            # Nothing can be ingested without the mandatory columns.
            return result

        # Rows already buffered below the header, then the remainder of the sheet.
        pending = ((index, values) for index, values in buffered if index > header_row)
        stream = chain(pending, enumerate(row_iterator, start=consumed + 1))

        for index, values in stream:
            self._absorb(index, values, layout, result)
            if len(result.rows) >= self.max_rows:
                result.truncated = True
                result.warnings.append(
                    f"reached the configured cap of {self.max_rows} rows; "
                    "remaining rows were not read"
                )
                break

        logger.info(
            "excel.parsed",
            file=filename,
            sheet=active,
            header_row=header_row,
            parsed=len(result.rows),
            invalid=len(result.invalid_rows),
            blank=result.blank_rows,
            truncated=result.truncated,
        )
        return result

    # ------------------------------------------------------------------
    # Header detection and column mapping
    # ------------------------------------------------------------------
    def _locate_header(
        self, buffered: list[tuple[int, tuple[Any, ...]]]
    ) -> tuple[int, tuple[Any, ...]]:
        """Find the header row among the buffered leading rows.

        Ranking is a tuple ``(carries_mandatory_columns, mapped_field_count)``,
        so a row that resolves the mandatory columns always outranks a title
        block that happens to contain many incidental words.  Comparison uses
        ``>`` (not ``>=``), which means the earliest row wins a tie.
        """
        reverse = self._reverse_aliases
        best_rank = (0, -1)
        best_row = _NO_HEADER_ROW
        best_values: tuple[Any, ...] = ()

        for index, values in buffered:
            mapped = {
                reverse[normalised]
                for value in values
                if (normalised := normalise_header(value)) in reverse
            }
            if not mapped:
                continue
            rank = (1 if REQUIRED_MATERIAL_FIELDS <= mapped else 0, len(mapped))
            if rank > best_rank:
                best_rank = rank
                best_row = index
                best_values = values

        return best_row, best_values

    def _build_layout(self, header_values: tuple[Any, ...]) -> "_ColumnLayout":
        """Resolve header cells to canonical fields, keeping the left-most win."""
        reverse = self._reverse_aliases
        columns: list[ColumnMapping] = []
        by_field: dict[str, int] = {}
        extra_columns: list[tuple[str, int]] = []
        unmapped: list[str] = []

        for offset, raw in enumerate(header_values):
            text = clean_text(raw)
            if not text:
                continue

            field_name = reverse.get(normalise_header(text))
            # A second column claiming the same logical field is ignored; the
            # left-most one wins, which is how people read a sheet.
            if field_name is None or field_name in by_field:
                unmapped.append(text)
                extra_columns.append((text, offset))
                continue

            by_field[field_name] = offset
            columns.append(
                ColumnMapping(field=field_name, column_index=offset + 1, header_text=text)
            )

        return _ColumnLayout(
            columns=tuple(columns),
            by_field=by_field,
            extra_columns=tuple(extra_columns),
            unmapped_headers=tuple(unmapped),
        )

    # ------------------------------------------------------------------
    # Row handling
    # ------------------------------------------------------------------
    def _absorb(
        self, index: int, values: tuple[Any, ...], layout: "_ColumnLayout", result: SheetParseResult
    ) -> None:
        """Classify one data row into ``blank``, ``invalid`` or ``parsed``."""
        cell = _CellReader(values, layout.by_field)

        description = clean_text(cell("description"))
        material_code = clean_text(cell("material_code")) or None
        remarks = clean_text(cell("remarks")) or None
        extra = {
            header: clean_text(values[offset])
            for header, offset in layout.extra_columns
            if offset < len(values) and clean_text(values[offset])
        }

        if not description:
            if material_code is None and not extra:
                # A trailing blank row - extremely common in real workbooks.
                result.blank_rows += 1
            else:
                result.invalid_rows.append(
                    InvalidRow(
                        row_number=index,
                        reason="missing description",
                        values={"material_code": material_code, **extra},
                    )
                )
            return

        descriptor = self._interpreter.parse(
            description,
            brand=clean_text(cell("brand")),
            model=clean_text(cell("model")),
            material_code=material_code or "",
            category=clean_text(cell("category")),
            remarks=remarks or "",
        )

        result.rows.append(
            ParsedMaterialRow(
                row_number=index,
                description=description,
                descriptor=descriptor,
                material_code=material_code,
                brand=descriptor.brand,
                model=descriptor.model,
                category=descriptor.category,
                unit=clean_text(cell("unit")) or None,
                quantity=parse_float(cell("quantity")),
                location=clean_text(cell("location")) or None,
                remarks=remarks,
                extra=extra,
            )
        )


class _CellReader:
    """Reads one canonical field out of a raw worksheet row.

    Keeps :meth:`SpreadsheetParser._absorb` free of index arithmetic, and returns
    ``None`` for any field the sheet has no column for.
    """

    __slots__ = ("_values", "_offsets")

    def __init__(self, values: tuple[Any, ...], offsets: Mapping[str, int]) -> None:
        self._values = values
        self._offsets = offsets

    def __call__(self, field_name: str) -> Any:
        offset = self._offsets.get(field_name)
        if offset is None or offset >= len(self._values):
            return None
        return self._values[offset]


def spreadsheet_parser() -> SpreadsheetParser:
    """A parser configured from the current settings - the usual entry point."""
    return SpreadsheetParser.from_settings()
