"""Excel ingestion tests: header discovery, alias mapping, row classification."""

from __future__ import annotations

import pytest

from app.config.constants import DEFAULT_COLUMN_ALIASES
from app.services.excel_parser import (
    InvalidRow,
    MissingColumnsError,
    SpreadsheetError,
    SpreadsheetParser,
    spreadsheet_parser,
)
from tests.factories import SAMPLE_ROWS, build_workbook


def parse(rows, **kwargs):  # noqa: ANN001, ANN201
    """Parse an in-memory workbook with the settings-configured parser."""
    payload = build_workbook(rows, **kwargs)
    return spreadsheet_parser().parse_bytes(payload, filename="materials.xlsx")


# ---------------------------------------------------------------------------
# Header discovery
# ---------------------------------------------------------------------------


def test_parses_every_data_row_of_a_clean_sheet() -> None:
    result = parse(SAMPLE_ROWS)

    assert result.is_usable is True
    assert len(result.rows) == len(SAMPLE_ROWS)
    assert result.invalid_rows == []
    assert result.header_row == 1
    assert result.sheet_name == "Sheet1"


def test_title_block_above_the_table_is_skipped() -> None:
    """Material masters routinely carry a title/logo block above the header."""
    result = parse(
        SAMPLE_ROWS,
        title_rows=(
            ("ACME MANUFACTURING PVT LTD",),
            ("Material Master Extract",),
            ("Generated on 2026-01-15",),
        ),
    )

    assert result.header_row == 4
    assert len(result.rows) == len(SAMPLE_ROWS)
    assert result.rows[0].material_code == "MC-1001"


def test_header_row_outranks_a_wordier_title_row() -> None:
    """A row of incidental words must not beat the real header."""
    result = parse(
        SAMPLE_ROWS,
        title_rows=(("Material Description Report Code Type Group Unit Quantity",),),
    )

    assert result.header_row == 2


def test_workbook_without_a_usable_header_is_rejected() -> None:
    payload = build_workbook((("one", "two"),), headers=None)

    with pytest.raises(SpreadsheetError, match="no header row found"):
        spreadsheet_parser().parse_bytes(payload, filename="empty.xlsx")


def test_missing_mandatory_column_is_reported_without_raising() -> None:
    """Non-strict mode ingests nothing but explains exactly what is missing."""
    payload = build_workbook((("BOLT-1", "bolt"),), headers=("Part Code", "Notes"))

    result = spreadsheet_parser().parse_bytes(payload, filename="bad.xlsx")

    assert result.rows == []
    assert result.is_usable is False
    assert any("description" in warning for warning in result.warnings)


def test_missing_mandatory_column_raises_in_strict_mode() -> None:
    parser = SpreadsheetParser(column_aliases=DEFAULT_COLUMN_ALIASES, strict_columns=True)
    payload = build_workbook((("BOLT-1",),), headers=("Part Code",))

    with pytest.raises(MissingColumnsError, match="no column for"):
        parser.parse_bytes(payload, filename="bad.xlsx")


# ---------------------------------------------------------------------------
# Column mapping
# ---------------------------------------------------------------------------


def test_aliases_resolve_alternative_header_spellings() -> None:
    payload = build_workbook(
        (("DESC-1", "Steel bolt M8", "ACME", "M8-40"),),
        headers=("Item Code", "Item Description", "Make", "Catalogue No"),
    )
    result = spreadsheet_parser().parse_bytes(payload, filename="aliases.xlsx")

    assert result.mapped_fields == ("material_code", "description", "brand", "model")
    row = result.rows[0]
    assert row.material_code == "DESC-1"
    assert row.brand == "ACME"
    assert row.model == "M8-40"


def test_headers_are_matched_case_and_punctuation_insensitively() -> None:
    payload = build_workbook(
        (("X-1", "Bolt M8"),), headers=("MATERIAL  NO", "material_description")
    )
    result = spreadsheet_parser().parse_bytes(payload, filename="case.xlsx")

    assert result.mapped_fields == ("material_code", "description")


def test_unmapped_columns_are_preserved_verbatim_in_extra() -> None:
    payload = build_workbook(
        (("X-1", "Bolt M8", "A-12-3", 42, "SUP-9"),),
        headers=("Material No.", "Description", "Rack", "Reorder Level", "Supplier"),
    )
    result = spreadsheet_parser().parse_bytes(payload, filename="extra.xlsx")

    assert result.unmapped_headers == ("Rack", "Reorder Level", "Supplier")
    assert result.rows[0].extra == {
        "Rack": "A-12-3",
        "Reorder Level": "42",
        "Supplier": "SUP-9",
    }


def test_extra_omits_columns_that_are_blank_for_the_row() -> None:
    payload = build_workbook(
        (("X-1", "Bolt M8", "", "SUP-9"),),
        headers=("Material No.", "Description", "Rack", "Supplier"),
    )
    result = spreadsheet_parser().parse_bytes(payload, filename="extra2.xlsx")

    assert result.rows[0].extra == {"Supplier": "SUP-9"}


def test_leftmost_column_wins_when_a_field_is_declared_twice() -> None:
    payload = build_workbook(
        (("X-1", "Bolt M8", "duplicate text"),),
        headers=("Material No.", "Description", "Material Description"),
    )
    result = spreadsheet_parser().parse_bytes(payload, filename="dup.xlsx")

    assert result.mapped_fields.count("description") == 1
    assert result.rows[0].description == "Bolt M8"
    assert "Material Description" in result.unmapped_headers


# ---------------------------------------------------------------------------
# Row classification
# ---------------------------------------------------------------------------


def test_blank_rows_are_counted_not_reported_as_errors() -> None:
    payload = build_workbook(
        (("X-1", "Bolt M8"), ("", ""), (None, None), ("X-2", "Nut M8")),
        headers=("Material No.", "Description"),
    )
    result = spreadsheet_parser().parse_bytes(payload, filename="blank.xlsx")

    assert len(result.rows) == 2
    assert result.blank_rows == 2
    assert result.invalid_rows == []


def test_row_with_data_but_no_description_is_invalid() -> None:
    payload = build_workbook(
        (("X-1", "", "A-12"), ("X-2", "Nut M8", "A-13")),
        headers=("Material No.", "Description", "Rack"),
    )
    result = spreadsheet_parser().parse_bytes(payload, filename="invalid.xlsx")

    assert len(result.rows) == 1
    assert len(result.invalid_rows) == 1
    invalid: InvalidRow = result.invalid_rows[0]
    assert invalid.row_number == 2
    assert invalid.reason == "missing description"
    assert invalid.values["material_code"] == "X-1"


def test_row_numbers_match_the_spreadsheet() -> None:
    assert [row.row_number for row in parse(SAMPLE_ROWS).rows] == [2, 3, 4, 5, 6]


def test_total_rows_scanned_covers_every_outcome() -> None:
    payload = build_workbook(
        (("X-1", "Bolt M8"), ("", ""), ("X-2", "")),
        headers=("Material No.", "Description"),
    )
    result = spreadsheet_parser().parse_bytes(payload, filename="counts.xlsx")

    assert result.total_rows_scanned == 3
    assert len(result.rows) == 1
    assert result.blank_rows == 1
    assert len(result.invalid_rows) == 1


def test_max_rows_caps_the_import() -> None:
    parser = SpreadsheetParser(column_aliases=DEFAULT_COLUMN_ALIASES, max_rows=2)
    payload = build_workbook(
        ((f"X-{index}", f"Item {index}") for index in range(1, 6)),
        headers=("Material No.", "Description"),
    )
    result = parser.parse_bytes(payload, filename="big.xlsx")

    assert len(result.rows) == 2
    assert result.truncated is True
    assert any("cap of 2 rows" in warning for warning in result.warnings)


# ---------------------------------------------------------------------------
# Worksheet selection
# ---------------------------------------------------------------------------


def test_first_worksheet_is_used_by_default() -> None:
    payload = build_workbook(
        SAMPLE_ROWS, sheet_name="Data", extra_sheets={"ReadMe": (("ignore", "me"),)}
    )
    result = spreadsheet_parser().parse_bytes(payload, filename="multi.xlsx")

    assert result.sheet_name == "Data"
    assert result.sheet_names == ("Data", "ReadMe")


def test_worksheet_can_be_selected_by_name() -> None:
    payload = build_workbook(
        SAMPLE_ROWS,
        sheet_name="Data",
        extra_sheets={
            "Archive": (
                ("Material No.", "Description"),
                ("Y-1", "Archived widget"),
            )
        },
    )
    result = spreadsheet_parser().parse_bytes(
        payload, filename="multi.xlsx", sheet_name="Archive"
    )

    assert result.sheet_name == "Archive"
    assert result.rows[0].material_code == "Y-1"


def test_unknown_worksheet_lists_the_available_names() -> None:
    payload = build_workbook(SAMPLE_ROWS, sheet_name="Data")

    with pytest.raises(SpreadsheetError, match="available"):
        spreadsheet_parser().parse_bytes(payload, filename="multi.xlsx", sheet_name="Nope")


def test_empty_payload_is_rejected() -> None:
    with pytest.raises(SpreadsheetError, match="payload is empty"):
        spreadsheet_parser().parse_bytes(b"", filename="nothing.xlsx")


# ---------------------------------------------------------------------------
# Interpretation
# ---------------------------------------------------------------------------


def test_description_is_interpreted_into_brand_model_and_category() -> None:
    rows = {row.material_code: row for row in parse(SAMPLE_ROWS).rows}

    contactor = rows["MC-1001"]
    assert contactor.brand == "Schneider Electric"
    assert contactor.model == "LC1D18"
    assert contactor.category == "Electrical"

    # The brand and model columns were left blank, so both come from the text.
    bearing = rows["MC-1002"]
    assert bearing.brand == "SKF"
    assert bearing.model == "6205-2RS"
    assert bearing.category == "Bearings"


def test_search_query_leads_with_brand_and_model() -> None:
    query = parse(SAMPLE_ROWS).rows[0].descriptor.search_query

    assert query.startswith("Schneider Electric LC1D18")
    # Packaging units must not leak into the query.
    assert "5 pcs" not in query


def test_search_readiness_reflects_available_signals() -> None:
    rows = {row.material_code: row for row in parse(SAMPLE_ROWS).rows}

    # Brand and model columns are filled in, so a maker search is precise.
    assert rows["MC-1001"].descriptor.search_readiness == "high"
    # Brand column blank, but "SS304" is lifted from the text: still searchable.
    assert rows["MC-1004"].descriptor.search_readiness == "medium"

    # With neither signal the row belongs in the review queue.
    payload = build_workbook(
        (("R-1", "Mild steel plate"),), headers=("Material No.", "Description")
    )
    result = spreadsheet_parser().parse_bytes(payload, filename="bare.xlsx")

    assert result.rows[0].descriptor.search_readiness == "low"


def test_numeric_cells_are_coerced() -> None:
    payload = build_workbook(
        (("X-1", "Bolt M8", 250, "1,250.75"),),
        headers=("Material No.", "Description", "Qty", "Reorder Level"),
    )
    result = spreadsheet_parser().parse_bytes(payload, filename="numbers.xlsx")

    assert result.rows[0].quantity == 250.0
    assert result.rows[0].extra["Reorder Level"] == "1,250.75"


def test_parses_from_disk(tmp_path) -> None:  # noqa: ANN001
    target = tmp_path / "materials.xlsx"
    target.write_bytes(build_workbook(SAMPLE_ROWS))

    result = spreadsheet_parser().parse_file(target)

    assert len(result.rows) == len(SAMPLE_ROWS)
    assert result.filename == "materials.xlsx"


def test_missing_file_reports_a_clear_error(tmp_path) -> None:  # noqa: ANN001
    with pytest.raises(SpreadsheetError, match="workbook not found"):
        spreadsheet_parser().parse_file(tmp_path / "absent.xlsx")


def test_description_only_workbook_still_parses() -> None:
    payload = build_workbook((("Schneider LC1D18 contactor",),), headers=("Description",))
    result = spreadsheet_parser().parse_bytes(payload, filename="simple.xlsx")

    assert result.mapped_fields == ("description",)
    assert result.rows[0].brand == "Schneider Electric"