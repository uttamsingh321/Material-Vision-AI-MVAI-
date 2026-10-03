"""Upload and workbook validation - the gate every file passes through.

Two stages, deliberately separated:

1. :meth:`ValidationService.validate_upload` - cheap container checks (name,
   extension, size).  Runs *before* anything touches the disk, so a huge junk
   file never gets written to ``uploads/``.
2. :meth:`ValidationService.validate_parsed` - semantic checks over an already
   parsed :class:`app.services.excel_parser.SheetParseResult`: are there any
   usable rows, how many were invalid, which headers were found.

:meth:`ValidationService.validate_workbook` chains both plus a real parse, so
the upload endpoint can return a full report ("5 rows found, 2 invalid")
without persisting anything.

The service never raises for *content* problems - it reports them.  Callers
decide which findings are fatal (the upload route treats ``report.ok == False``
as HTTP 400).  :meth:`ensure_uploadable` is the convenience wrapper that turns
fatal findings into :class:`UploadRejectedError`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import get_settings
from app.config.constants import SUPPORTED_SPREADSHEET_SUFFIXES

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.services.excel_parser import SheetParseResult

#: Severities.
ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One finding: what it is, how bad it is, where it came from."""

    code: str
    message: str
    severity: str = ERROR
    #: Column/row the issue points at, when applicable.
    location: str | None = None


@dataclass(slots=True)
class ValidationReport:
    """The outcome of a validation pass."""

    issues: list[ValidationIssue] = field(default_factory=list)
    row_count: int = 0
    valid_row_count: int = 0
    invalid_row_count: int = 0
    sheet_name: str | None = None
    header_row: int | None = None
    headers: tuple[str, ...] = ()

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == WARNING]

    @property
    def ok(self) -> bool:
        """``True`` when nothing fatal was found and there is work to do."""
        return not self.errors and self.valid_row_count > 0

    def add(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "row_count": self.row_count,
            "valid_row_count": self.valid_row_count,
            "invalid_row_count": self.invalid_row_count,
            "sheet_name": self.sheet_name,
            "header_row": self.header_row,
            "headers": list(self.headers),
            "errors": [
                {"code": i.code, "message": i.message, "location": i.location}
                for i in self.errors
            ],
            "warnings": [
                {"code": i.code, "message": i.message, "location": i.location}
                for i in self.warnings
            ],
        }


class UploadRejectedError(ValueError):
    """The file container itself is unacceptable (type/size/emptiness)."""


class ValidationService:
    """Stateless validator; safe to share a single instance."""

    def __init__(
        self,
        *,
        allowed_suffixes: tuple[str, ...] | None = None,
        max_bytes: int | None = None,
    ) -> None:
        settings = get_settings()
        self.allowed_suffixes = allowed_suffixes or SUPPORTED_SPREADSHEET_SUFFIXES
        self.max_bytes = (
            max_bytes if max_bytes is not None else settings.max_upload_size_mb * 1024 * 1024
        )

    # ------------------------------------------------------------------
    # Stage 1: container checks
    # ------------------------------------------------------------------
    def validate_upload(self, filename: str | None, payload: bytes) -> list[ValidationIssue]:
        """Filename/extension/size/emptiness findings for a raw upload."""
        issues: list[ValidationIssue] = []
        name = (filename or "").strip()

        if not name:
            issues.append(
                ValidationIssue("missing_filename", "no file name was supplied")
            )
        else:
            suffix = Path(name).suffix.lower()
            if suffix not in {item.lower() for item in self.allowed_suffixes}:
                allowed = ", ".join(self.allowed_suffixes)
                issues.append(
                    ValidationIssue(
                        "unsupported_type",
                        f"{name!r} is not a supported spreadsheet ({allowed})",
                        location=name,
                    )
                )

        if not payload:
            issues.append(ValidationIssue("empty_file", "the uploaded file is empty"))
        elif self.max_bytes and len(payload) > self.max_bytes:
            limit_mb = self.max_bytes // (1024 * 1024)
            issues.append(
                ValidationIssue(
                    "too_large",
                    f"file is {len(payload)} bytes; the limit is {limit_mb} MB",
                )
            )
        return issues

    def ensure_uploadable(self, filename: str | None, payload: bytes) -> None:
        """Raise :class:`UploadRejectedError` when stage-1 checks fail."""
        issues = self.validate_upload(filename, payload)
        fatal = [issue for issue in issues if issue.severity == ERROR]
        if fatal:
            raise UploadRejectedError("; ".join(issue.message for issue in fatal))

    # ------------------------------------------------------------------
    # Stage 2: semantic checks over a parse result
    # ------------------------------------------------------------------
    def validate_parsed(self, result: SheetParseResult) -> ValidationReport:
        """Grade an already-parsed sheet: rows, invalid lines, warnings."""
        report = ValidationReport(
            row_count=len(result.rows) + len(result.invalid_rows),
            valid_row_count=len(result.rows),
            invalid_row_count=len(result.invalid_rows),
            sheet_name=result.sheet_name,
            header_row=result.header_row,
            headers=tuple(column.header_text for column in result.columns),
        )

        for message in result.warnings:
            report.add(ValidationIssue("parser_warning", message, severity=WARNING))

        if not result.rows:
            report.add(
                ValidationIssue(
                    "no_usable_rows",
                    f"worksheet {result.sheet_name!r} contains no usable material rows",
                )
            )

        for invalid in result.invalid_rows[:50]:
            report.add(
                ValidationIssue(
                    "invalid_row",
                    f"row {invalid.row_number}: {invalid.reason}",
                    severity=WARNING,
                    location=f"row {invalid.row_number}",
                )
            )
        if len(result.invalid_rows) > 50:
            report.add(
                ValidationIssue(
                    "invalid_row_truncated",
                    f"{len(result.invalid_rows) - 50} further invalid rows not listed",
                    severity=WARNING,
                )
            )
        return report

    # ------------------------------------------------------------------
    # Chained check used by the upload endpoint
    # ------------------------------------------------------------------
    def validate_workbook(self, payload: bytes, filename: str | None) -> ValidationReport:
        """Container checks + real parse + semantic checks, in one report.

        Never raises for content problems; a structurally broken workbook
        (unreadable zip, no header row) becomes a fatal issue in the report.
        """
        from app.services.excel_parser import SpreadsheetError, spreadsheet_parser

        container_issues = self.validate_upload(filename, payload)
        if any(issue.severity == ERROR for issue in container_issues):
            report = ValidationReport()
            for issue in container_issues:
                report.add(issue)
            return report

        try:
            result = spreadsheet_parser().parse_bytes(payload, filename=filename or "upload.xlsx")
        except SpreadsheetError as exc:
            report = ValidationReport()
            report.add(ValidationIssue("unreadable_workbook", str(exc)))
            return report

        report = self.validate_parsed(result)
        for issue in container_issues:  # warnings from stage 1, if any
            report.add(issue)
        return report


def validation_service() -> ValidationService:
    """A validator configured from the current settings."""
    return ValidationService()


__all__ = [
    "ERROR",
    "UploadRejectedError",
    "ValidationIssue",
    "ValidationReport",
    "ValidationService",
    "validation_service",
    "WARNING",
]

