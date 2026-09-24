"""Test data builders.

The Excel parser and the export service both need real ``.xlsx`` bytes, not
mocks - a mocked workbook would not exercise header detection, merged title
rows or cell type coercion.  :func:`build_workbook` produces genuine files in
memory with ``openpyxl``.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Sequence

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

#: The headers used by most tests.  Deliberately spelled three different ways so
#: alias matching is exercised rather than assumed.
DEFAULT_HEADERS: tuple[str, ...] = (
    "Material No.",
    "Material Description",
    "Brand",
    "Model Number",
    "Category",
    "UOM",
    "Qty",
    "Bin Location",
    "Remarks",
)

#: A small but realistic material master.
SAMPLE_ROWS: tuple[tuple[Any, ...], ...] = (
    (
        "MC-1001",
        "Schneider Electric LC1D18 contactor 18A 230VAC coil 5 pcs",
        "Schneider Electric",
        "LC1D18",
        "Electrical",
        "Nos",
        12,
        "A-01-02",
        "Preferred vendor",
    ),
    (
        "MC-1002",
        "SKF 6205-2RS deep groove ball bearing",
        "",
        "",
        "",
        "Nos",
        40,
        "B-04-11",
        "",
    ),
    (
        "MC-1003",
        "Loctite 243 threadlocker medium strength 50ml bottle",
        "Henkel",
        "243",
        "Chemical",
        "Bottle",
        8,
        "C-02-01",
        "",
    ),
    (
        "MC-1004",
        "8mm hex bolt stainless steel SS304 zinc plated",
        "",
        "",
        "",
        "Nos",
        500,
        "A-09-07",
        "Fasteners",
    ),
    (
        "MC-1005",
        "Anti static ESD wrist strap with coiled cord and banana plug",
        "",
        "",
        "",
        "Nos",
        25,
        "D-01-01",
        "",
    ),
)


def build_workbook(
    rows: Sequence[Sequence[Any]],
    *,
    sheet_name: str = "Sheet1",
    headers: Sequence[str] | None = DEFAULT_HEADERS,
    title_rows: Sequence[Sequence[Any]] = (),
    extra_sheets: dict[str, Sequence[Sequence[Any]]] | None = None,
) -> bytes:
    """Build a genuine workbook and return its bytes.

    Args:
        rows: data rows, written beneath the header.
        headers: header row, or ``None`` to write no header at all.
        title_rows: rows written *above* the header, to simulate a title block.
        extra_sheets: additional worksheets by name, written verbatim - include a
            header row when the sheet is meant to be parsed.
    """
    workbook = Workbook()
    sheet: Worksheet = workbook.active
    sheet.title = sheet_name

    for title_row in title_rows:
        sheet.append(list(title_row))
    if headers is not None:
        sheet.append(list(headers))
    for row in rows:
        sheet.append(list(row))

    for name, extra_rows in (extra_sheets or {}).items():
        extra_sheet = workbook.create_sheet(title=name)
        for row in extra_rows:
            extra_sheet.append(list(row))

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_simple_workbook(
    rows: Sequence[Sequence[Any]],
    *,
    headers: Sequence[str] = ("Description",),
) -> bytes:
    """A minimal workbook with a single ``Description`` column."""
    return build_workbook(rows, headers=headers)
