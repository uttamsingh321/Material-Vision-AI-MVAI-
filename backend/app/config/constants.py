"""Contract-level constants shared across the backend.

Only values that are part of the application's *contract* belong here - things
that the rest of the code and the persisted data depend on, such as the alias
table used to recognise Excel columns, or the canonical images MIME map.

Every operator-tunable value lives in :mod:`app.config.settings` instead, so
nothing in the codebase needs a literal path, URL or credential.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Mapping

# ---------------------------------------------------------------------------
# Spreadsheet ingestion contract
# ---------------------------------------------------------------------------

#: Logical material attributes the parser understands.  ``description`` is the
#: only mandatory field; everything else is optional and is copied through to
#: ``materials.extra`` when the source workbook has no dedicated column.
CANONICAL_MATERIAL_FIELDS: Final[tuple[str, ...]] = (
    "material_code",
    "description",
    "brand",
    "model",
    "category",
    "unit",
    "quantity",
    "location",
    "remarks",
)

REQUIRED_MATERIAL_FIELDS: Final[frozenset[str]] = frozenset({"description"})

#: Accepted header spellings per logical field.  Matching runs against a
#: normalised header (lower-cased, alphanumerics only), so ``"Material No."``,
#: ``"material_no"`` and ``"MATERIAL NO"`` all resolve to ``material_code``.
#: Operators extend this table through ``MVAI_COLUMN_ALIASES_JSON`` without
#: touching code.
DEFAULT_COLUMN_ALIASES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "material_code": (
            "material code",
            "materialcode",
            "material no",
            "material number",
            "material id",
            "mat code",
            "mat no",
            "part number",
            "part no",
            "partno",
            "part code",
            "item code",
            "item no",
            "item number",
            "sku",
            "code",
        ),
        "description": (
            "description",
            "material description",
            "item description",
            "product description",
            "long description",
            "short description",
            "material name",
            "item name",
            "description of material",
            "desc",
            "name",
            "material",
        ),
        "brand": (
            "brand",
            "brand name",
            "make",
            "manufacturer",
            "manufacturer name",
            "mfr",
            "mfg",
            "oem",
            "vendor",
        ),
        "model": (
            "model",
            "model no",
            "model number",
            "model code",
            "part model",
            "catalog number",
            "catalogue number",
            "catalogue no",
            "catalog no",
            "mpn",
            "manufacturer part number",
        ),
        "category": (
            "category",
            "material category",
            "material group",
            "material type",
            "group",
            "type",
            "class",
            "segment",
        ),
        "unit": ("unit", "uom", "unit of measure", "units", "unit of issue"),
        "quantity": (
            "quantity",
            "qty",
            "stock",
            "stock qty",
            "stock quantity",
            "on hand",
            "balance",
        ),
        "location": (
            "location",
            "bin",
            "bin location",
            "warehouse",
            "store",
            "storage location",
            "plant",
            "shelf",
        ),
        "remarks": (
            "remarks",
            "remark",
            "notes",
            "note",
            "comment",
            "comments",
            "additional info",
            "additional information",
        ),
    }
)

#: File extensions the upload endpoint accepts.
SUPPORTED_SPREADSHEET_SUFFIXES: Final[tuple[str, ...]] = (".xlsx", ".xlsm")

#: Excel's hard sheet limits - used to fail fast on absurd workbooks.
EXCEL_MAX_ROWS: Final[int] = 1_048_576
EXCEL_MAX_COLUMNS: Final[int] = 16_384

# ---------------------------------------------------------------------------
# Image handling contract
# ---------------------------------------------------------------------------

#: Canonical image suffix -> MIME type.  Used when a remote server omits or
#: misreports ``Content-Type``.
MIME_TYPE_BY_SUFFIX: Final[Mapping[str, str]] = MappingProxyType(
    {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".avif": "image/avif",
    }
)

#: Remote-image file extensions the downloader is willing to persist.
DEFAULT_ALLOWED_IMAGE_SUFFIXES: Final[tuple[str, ...]] = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
)

#: Substrings that betray a thumbnail / placeholder / site-chrome asset.  The
#: candidate filter rejects URLs containing any of these (case-insensitive).
THUMBNAIL_URL_MARKERS: Final[tuple[str, ...]] = (
    "thumb",
    "thumbnail",
    "sprite",
    "placeholder",
    "no-image",
    "noimage",
    "missing",
    "blank.gif",
    "pixel.gif",
    "spacer",
    "loading",
    "/logo",
    "logo_",
    "banner",
    "icon",
    "avatar",
    "favicon",
    "flag",
)

# ---------------------------------------------------------------------------
# Image library taxonomy (mirrors the image-library/ folder tree)
# ---------------------------------------------------------------------------

DEFAULT_MATERIAL_CATEGORIES: Final[tuple[str, ...]] = (
    "Electrical",
    "Mechanical",
    "Chemical",
    "Packaging",
    "ESD",
    "Fixtures",
    "Consumables",
    "Bearings",
    "Connectors",
    "Tools",
    "Uncategorised",
)

UNCATEGORISED: Final[str] = "Uncategorised"

# ---------------------------------------------------------------------------
# HTTP / API contract
# ---------------------------------------------------------------------------

#: Default dev-server origins for the Vite frontend.  Overridable through the
#: comma-separated ``MVAI_CORS_ORIGINS`` setting.
DEFAULT_CORS_ORIGINS: Final[tuple[str, ...]] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

#: Default page size for collection endpoints, and the hard ceiling a client
#: may request - protects the API from ``?page_size=1000000``.
DEFAULT_PAGE_SIZE: Final[int] = 50
MAX_PAGE_SIZE: Final[int] = 500

#: Headers used to correlate a request across logs, audit rows and responses.
REQUEST_ID_HEADER: Final[str] = "X-Request-ID"
PROCESS_TIME_HEADER: Final[str] = "X-Process-Time-Ms"

#: WebSocket channel names used by the live-progress fan-out.
WS_CHANNEL_JOBS: Final[str] = "jobs"
WS_CHANNEL_LOGS: Final[str] = "logs"
WS_CHANNEL_DASHBOARD: Final[str] = "dashboard"
ALL_WS_CHANNELS: Final[tuple[str, ...]] = (
    WS_CHANNEL_JOBS,
    WS_CHANNEL_LOGS,
    WS_CHANNEL_DASHBOARD,
)

# ---------------------------------------------------------------------------
# Export / report contract
# ---------------------------------------------------------------------------

#: Columns appended to the source workbook by the export service, in order.
#: Prefixed so they can never collide with an operator's own headers.
EXPORT_EXTRA_COLUMNS: Final[tuple[str, ...]] = (
    "MVAI Status",
    "MVAI Image File",
    "MVAI Image Count",
    "MVAI Confidence",
    "MVAI Image Source",
    "MVAI Source Page",
    "MVAI Brand (parsed)",
    "MVAI Model (parsed)",
    "MVAI Search Query",
    "MVAI Notes",
)

#: Fields the CSV/JSON exporters emit for every material.
EXPORT_FIELDS: Final[tuple[str, ...]] = (
    "row_number",
    "material_code",
    "description",
    "brand",
    "model",
    "category",
    "unit",
    "quantity",
    "location",
    "remarks",
    "status",
    "confidence",
    "image_count",
    "accepted_image_path",
    "accepted_image_source",
    "accepted_image_page",
    "search_query",
    "last_error",
)
