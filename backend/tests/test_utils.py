"""Utility layer tests: text normalisation, hashing, files, URLs, pagination."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.utils.files import (
    ensure_within,
    has_suffix,
    human_bytes,
    relative_posix,
    safe_filename,
    unique_path,
)
from app.utils.hashing import (
    build_cache_key,
    hamming_distance,
    hamming_similarity,
    sha256_file,
    sha256_text,
    unique_preserving_order,
)
from app.utils.pagination import PageParams, paginate
from app.utils.text import (
    clean_text,
    combined_similarity,
    contains_normalised,
    extract_model_candidates,
    jaccard_similarity,
    normalise_code,
    normalise_header,
    parse_float,
    parse_int,
    sequence_similarity,
    slugify,
    strip_units,
    tokenize,
    truncate,
)
from app.utils.urls import (
    domain_of,
    filename_from_url,
    is_probable_image_url,
    is_same_domain,
    is_thumbnail_url,
    normalise_url,
    resolve_url,
    suffix_from_url,
)


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        ("  Contactor   18A  ", "Contactor 18A"),
        ("line\nbreak\there", "line break here"),
        (25, "25"),
        (25.0, "25"),
        (25.5, "25.5"),
        ("ＦＵＬＬＷＩＤＴＨ１２３", "FULLWIDTH123"),
    ],
)
def test_clean_text_normalises_cells(value: object, expected: str) -> None:
    assert clean_text(value) == expected


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Material No.", "materialno"),
        ("material_no", "materialno"),
        ("MATERIAL  NO", "materialno"),
        ("Part  Number ", "partnumber"),
    ],
)
def test_normalise_header_collapses_punctuation(header: str, expected: str) -> None:
    assert normalise_header(header) == expected


def test_normalise_code_removes_separators() -> None:
    assert normalise_code("LC1-D18") == normalise_code("lc1 d18") == "lc1d18"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Schneider Electric", "schneider-electric"),
        ("  Terminals & Lugs!! ", "terminals-lugs"),
        ("", "unnamed"),
        ("!!!", "unnamed"),
    ],
)
def test_slugify(value: str, expected: str) -> None:
    assert slugify(value) == expected


def test_slugify_respects_max_length() -> None:
    assert len(slugify("a" * 300, max_length=20)) <= 20


def test_tokenize_drops_short_tokens_and_duplicates() -> None:
    assert tokenize("Contactor a 18A contactor coil") == ["contactor", "18a", "coil"]


def test_jaccard_similarity_bounds() -> None:
    assert jaccard_similarity("contactor 18A", "contactor 18A") == 1.0
    assert jaccard_similarity("contactor", "bearing") == 0.0
    assert jaccard_similarity("", "bearing") == 0.0


def test_sequence_similarity_detects_near_miss_codes() -> None:
    assert sequence_similarity("LC1D18G7", "LC1D18G6") > 0.85
    assert sequence_similarity("LC1D18G7", "XYZ") < 0.5


def test_combined_similarity_ranks_exact_above_partial() -> None:
    assert combined_similarity("LC1D18", "LC1D18") == 1.0
    assert combined_similarity("LC1D18", "LC1D18G7") > combined_similarity("LC1D18", "ABC123")


def test_contains_normalised_ignores_separators_and_case() -> None:
    assert contains_normalised("Schneider LC1-D18 contactor", "lc1d18")
    assert not contains_normalised("Schneider LC1-D18 contactor", "lc1d25")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, None),
        (12, 12.0),
        (12.5, 12.5),
        ("1,250.75", 1250.75),
        ("1,250.75 pcs", 1250.75),
        ("Rs. 99", 99.0),
        ("no digits here", None),
        ("", None),
    ],
)
def test_parse_float(value: object, expected: float | None) -> None:
    assert parse_float(value) == expected


def test_parse_int() -> None:
    assert parse_int("42 units") == 42
    assert parse_int(None) is None


def test_strip_units_removes_packaging_words() -> None:
    assert strip_units("Contactor 18A 5 pcs") == "Contactor 18A 5"


def test_truncate() -> None:
    assert truncate("abcdefghij", 5) == "abcd…"
    assert truncate("abc", 10) == "abc"
    assert truncate("abc", 0) == "abc"


def test_extract_model_candidates_prefers_separated_tokens() -> None:
    text = "Schneider LC1D18 18A contactor 230VAC coil 5 pcs"
    candidates = extract_model_candidates(text)

    assert "LC1D18" in candidates
    assert "18A" in candidates
    # Bare numbers must never be offered as a model.
    assert "5" not in candidates
    assert "230" not in candidates


def test_extract_model_candidates_respects_limit() -> None:
    assert len(extract_model_candidates("A1B2 C3D4 E5F6 G7H8", limit=2)) == 2


# ---------------------------------------------------------------------------
# hashing
# ---------------------------------------------------------------------------


def test_sha256_text_is_stable_and_distinct() -> None:
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abd")
    assert len(sha256_text("abc")) == 64


def test_sha256_file_streams_content(tmp_path: Path) -> None:
    import hashlib

    payload = b"mvai-image-bytes"
    target = tmp_path / "payload.bin"
    target.write_bytes(payload)

    assert sha256_file(target) == hashlib.sha256(payload).hexdigest()


def test_build_cache_key_ignores_empty_parts() -> None:
    assert build_cache_key("a", None, "b") == build_cache_key("a", "", "b")
    assert build_cache_key("a", "b").startswith("mvai:")
    assert build_cache_key("a", "b") != build_cache_key("a", "c")


def test_build_cache_key_honours_namespace() -> None:
    assert build_cache_key("a", namespace="other").startswith("other:")


def test_hamming_distance_and_similarity() -> None:
    assert hamming_distance("1010", "1010") == 0
    assert hamming_distance("1010", "1111") == 2
    # Incomparable inputs are signalled with -1 rather than raising.
    assert hamming_distance("1010", "1") == -1
    assert hamming_similarity(0, 64) == 1.0
    assert hamming_similarity(-1, 64) == 0.0
    assert hamming_similarity(16, 64) == pytest.approx(0.75)


def test_unique_preserving_order() -> None:
    assert unique_preserving_order(["b", "a", "b", "c"]) == ["b", "a", "c"]


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32\\cmd.exe", "cmd.exe"),
        ("bad:name?*.xlsx", "bad_name_.xlsx"),
        ("nul.xlsx", "nul_file.xlsx"),
        ("", "file"),
        ("!!!", "file"),
    ],
)
def test_safe_filename_neutralises_hostile_input(raw: str, expected: str) -> None:
    assert safe_filename(raw) == expected


def test_safe_filename_caps_length() -> None:
    assert len(safe_filename(f"{'a' * 400}.xlsx", max_length=40)) <= 40


def test_ensure_within_allows_descendants(tmp_path: Path) -> None:
    resolved = ensure_within(tmp_path, "sub/dir/file.png")
    assert resolved == (tmp_path / "sub" / "dir" / "file.png").resolve()


def test_ensure_within_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes the storage root"):
        ensure_within(tmp_path, "../outside.png")


def test_relative_posix_uses_forward_slashes(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")

    assert relative_posix(target, tmp_path) == "a/b.png"


def test_unique_path_disambiguates(tmp_path: Path) -> None:
    (tmp_path / "img.png").write_bytes(b"x")
    (tmp_path / "img-1.png").write_bytes(b"x")

    assert unique_path(tmp_path, "img.png").name == "img-2.png"


def test_unique_path_returns_name_when_free(tmp_path: Path) -> None:
    assert unique_path(tmp_path, "fresh.png").name == "fresh.png"


def test_human_bytes() -> None:
    assert human_bytes(0) == "0 B"
    assert human_bytes(None) == "0 B"
    assert human_bytes(512) == "512 B"
    assert human_bytes(1536) == "1.5 KB"
    assert human_bytes(1024 * 1024) == "1.0 MB"


def test_has_suffix_is_case_insensitive() -> None:
    assert has_suffix("IMAGE.PNG", (".png", ".jpg")) is True
    assert has_suffix("image.gif", (".png", ".jpg")) is False


# ---------------------------------------------------------------------------
# urls
# ---------------------------------------------------------------------------


def test_normalise_url_strips_fragment_and_default_port() -> None:
    assert normalise_url("HTTPS://Example.com:443/a/b.png#frag") == "https://example.com/a/b.png"
    assert normalise_url("http://example.com:80/x") == "http://example.com/x"


def test_normalise_url_protocol_relative_and_garbage() -> None:
    assert normalise_url("//cdn.test/img.png") == "https://cdn.test/img.png"
    assert normalise_url("not a url") is None
    assert normalise_url(None) is None


def test_domain_of_removes_www_and_port() -> None:
    assert domain_of("https://www.se.com:8443/product") == "se.com"
    assert domain_of("https://digikey.com/x") == "digikey.com"
    assert domain_of("garbage") is None


def test_resolve_url_handles_relative_hrefs() -> None:
    assert resolve_url("https://se.com/a/b", "c.png") == "https://se.com/a/c.png"
    assert resolve_url(None, "https://x.test/y.png") == "https://x.test/y.png"
    assert resolve_url("https://se.com", None) is None


def test_is_probable_image_url() -> None:
    assert is_probable_image_url("https://x.test/a.png") is True
    assert is_probable_image_url("https://x.test/page", allowed_suffixes=(".png",)) is False
    assert is_probable_image_url("https://x.test/api/image/123") is True


def test_is_thumbnail_url_flags_placeholders() -> None:
    assert is_thumbnail_url("https://x.test/thumbs/a.png") is True
    assert is_thumbnail_url("https://x.test/no-image.png") is True
    assert is_thumbnail_url("https://x.test/products/lc1d18.jpg") is False


def test_filename_and_suffix_from_url() -> None:
    assert filename_from_url("https://x.test/a/b/Part%20Photo.png?v=2") == "Part_Photo.png"
    assert filename_from_url(None) == "image"
    assert suffix_from_url("https://x.test/a.JPG") == ".jpg"
    assert suffix_from_url("https://x.test/a") == ""


def test_is_same_domain_tolerates_www() -> None:
    assert is_same_domain("https://www.se.com/a", "https://se.com/b") is True
    assert is_same_domain("https://se.com/a", "https://abb.com/b") is False


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------


def test_page_params_clamp_client_input() -> None:
    assert PageParams.from_query(page=0, page_size=0).page == 1
    assert PageParams.from_query(page=2, page_size=10_000).page_size == 500
    assert PageParams.from_query(page=3, page_size=25).offset == 50


def test_paginate_reports_navigation() -> None:
    page = paginate(["a", "b"], total=120, params=PageParams.from_query(page=2, page_size=50))

    assert page.pages == 3
    assert page.has_previous is True
    assert page.has_next is True


def test_paginate_empty_result_set() -> None:
    page = paginate([], total=0, params=PageParams())

    assert page.pages == 0
    assert page.has_next is False
    assert page.has_previous is False
