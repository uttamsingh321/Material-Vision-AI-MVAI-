"""AI-engine loader, brand detector and material classifier tests."""

from __future__ import annotations

import pytest

from app.ai_engine import (
    PACKAGE_ALIASES,
    REPO_ROOT,
    SiblingPackageError,
    available_modules,
    brand_detector,
    confidence_engine,
    description_parser,
    duplicate_detector,
    load,
    material_classifier,
)


# ---------------------------------------------------------------------------
# loader
# ---------------------------------------------------------------------------


def test_repo_root_points_at_the_repository() -> None:
    assert (REPO_ROOT / "backend").is_dir()
    assert (REPO_ROOT / "ai-engine").is_dir()


def test_loader_registers_the_hyphenated_directory() -> None:
    module = brand_detector()

    assert module.__name__ == f"{PACKAGE_ALIASES['ai-engine']}.brand_detector"
    assert hasattr(module, "detect_brand")


def test_loader_is_idempotent() -> None:
    assert brand_detector() is brand_detector()


def test_every_declared_package_has_an_initialiser() -> None:
    for package in PACKAGE_ALIASES:
        assert (REPO_ROOT / package / "__init__.py").is_file(), f"{package} lacks __init__.py"


def test_available_modules_lists_importable_stems() -> None:
    modules = available_modules()

    assert "brand_detector" in modules
    assert "material_classifier" in modules
    assert "confidence_engine" in modules
    assert "duplicate_detector" in modules
    assert "__init__" not in modules


def test_typed_accessors_resolve_to_real_modules() -> None:
    for accessor in (confidence_engine, duplicate_detector):
        module = accessor()

        assert module.__name__.startswith(f"{PACKAGE_ALIASES['ai-engine']}.")


def test_unknown_package_is_rejected() -> None:
    with pytest.raises(SiblingPackageError, match="unknown package"):
        load("anything", package="not-a-package")


def test_missing_module_reports_a_clear_error() -> None:
    with pytest.raises(SiblingPackageError, match="not found in 'ai-engine'"):
        load("does_not_exist")


def test_relative_imports_work_across_loaded_modules() -> None:
    """``description_parser`` imports its siblings relatively."""
    assert hasattr(description_parser(), "parse_description")


# ---------------------------------------------------------------------------
# brand detector
# ---------------------------------------------------------------------------


def test_multi_word_alias_beats_the_shorter_one() -> None:
    match = brand_detector().detect_in_text("SCHNEIDER ELECTRIC LC1D18 CONTACTOR")

    assert match is not None
    assert match.brand == "Schneider Electric"
    assert match.matched_on == "schneider electric"


def test_short_alias_still_matches_on_its_own() -> None:
    match = brand_detector().detect_in_text("Schneider LC1D18")

    assert match is not None
    assert match.brand == "Schneider Electric"
    assert match.confidence == 0.85


def test_aliases_are_matched_as_whole_words() -> None:
    """'abb' must not match inside 'abbott', and punctuation must not block it."""
    detector = brand_detector()

    assert detector.detect_in_text("Abbott analytical balance") is None
    assert detector.detect_in_text("ABB, S201-C16 MCB") is not None
    assert detector.detect_in_text("(ABB) MCB") is not None


def test_detector_scans_sources_in_order() -> None:
    """A brand embedded in the material code outranks a noisy description."""
    match = brand_detector().detect_brand("SKF6205-2RS", "bearing for conveyor")

    assert match is not None
    assert match.brand == "SKF"
    assert match.source == "code"
    assert match.confidence == 0.8


def test_whole_word_matching_cannot_see_a_glued_brand() -> None:
    """Documents why :meth:`detect_in_code` exists at all."""
    detector = brand_detector()

    assert detector.detect_in_text("SKF6205-2RS") is None
    assert detector.detect_in_code("SKF6205-2RS").brand == "SKF"


def test_code_prefix_requires_a_following_digit() -> None:
    detector = brand_detector()

    assert detector.detect_in_code("SK Frame") is None
    assert detector.detect_in_code("") is None
    assert detector.detect_in_code(None) is None


def test_detect_returns_none_when_nothing_matches() -> None:
    assert brand_detector().detect_brand("gibberish zzz", None, "") is None


def test_brand_detection_from_url_domain() -> None:
    detector = brand_detector()

    match = detector.detect_in_url("https://www.se.com/in/en/product/LC1D18")
    assert match is not None and match.brand == "Schneider Electric"
    assert detector.detect_in_url("https://se.com/x").matched_on == "se.com"
    assert detector.detect_in_url("https://example.com/x") is None
    assert detector.detect_in_url(None) is None


def test_host_label_fallback_handles_country_suffixes() -> None:
    """``abb.co.in`` has no ``abb.com`` suffix, so the label index resolves it."""
    detector = brand_detector()
    match = detector.detect_in_url("https://www.abb.co.in/products")

    assert match is not None
    assert match.brand == "ABB"
    assert match.confidence == 0.95


def test_hyphenated_hosts_are_not_mangled() -> None:
    """A host must be compared verbatim; collapsing punctuation breaks matching."""
    match = brand_detector().detect_in_url("https://www.rs-online.com/web/p/1234")

    assert match is not None
    assert match.matched_on == "rs-online.com"


def test_bare_domain_input_is_accepted() -> None:
    assert brand_detector().detect_in_url("se.com/in/en/x").brand == "Schneider Electric"


def test_domain_match_is_fully_confident() -> None:
    match = brand_detector().detect_in_url("https://se.com/x")

    assert match is not None
    assert match.confidence == 1.0
    assert match.is_confident is True


def test_normalise_brand_canonicalises_known_and_preserves_unknown() -> None:
    module = brand_detector()

    assert module.normalise_brand("schneider") == "Schneider Electric"
    assert module.normalise_brand("ACME TOOLING") == "Acme Tooling"
    assert module.normalise_brand("  ") is None
    assert module.normalise_brand(None) is None


def test_aliases_and_domains_lookup() -> None:
    detector = brand_detector().detector

    assert "telemecanique" in detector.aliases_for("schneider electric")
    assert detector.domains_for("SKF") == ("skf.com",)
    assert detector.aliases_for("nope") == ()


def test_brand_names_are_unique() -> None:
    names = brand_detector().brand_names()

    assert len(names) == len(set(names))
    assert "Schneider Electric" in names


def test_detect_brands_deduplicates() -> None:
    found = brand_detector().detect_brands(["SKF bearing", "SKF6205", "ABB MCB"])

    assert [match.brand for match in found] == ["SKF", "ABB"]


# ---------------------------------------------------------------------------
# material classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Schneider LC1D18 contactor 18A", "Electrical"),
        ("Hex bolt M8x40 SS304", "Mechanical"),
        ("SKF 6205-2RS ball bearing", "Bearings"),
        ("RJ45 plug cat6 shielded", "Connectors"),
        ("ESD wrist strap with cord", "ESD"),
        ("Nitrile gloves powder free", "Consumables"),
        ("Corrugated box 400x300x200", "Packaging"),
        ("Loctite 243 threadlocker 50ml", "Chemical"),
        ("Toggle clamp vertical handle", "Fixtures"),
        ("Crimping tool for ferrules", "Tools"),
    ],
)
def test_classifier_places_typical_materials(description: str, expected: str) -> None:
    assert material_classifier().category_for(description) == expected


def test_longest_phrase_decides_not_the_match_count() -> None:
    """'bearing grease' is a Chemical, even though 'bearing' scores Bearings."""
    assert material_classifier().category_for("SKF bearing grease LGMT2") == "Chemical"

def test_plural_forms_are_recognised() -> None:
    module = material_classifier()

    assert module.category_for("Cable ties 200mm black") == "Consumables"
    assert module.category_for("Hex bolts M10") == "Mechanical"


def test_unknown_text_is_uncategorised() -> None:
    match = material_classifier().classify("zzzz qqqq wwww")

    assert match.category == "Uncategorised"
    assert match.score == 0
    assert match.is_confident is False


def test_empty_input_is_uncategorised() -> None:
    match = material_classifier().classify("", None)

    assert match.category == "Uncategorised"
    assert match.matched_terms == ()


def test_ambiguous_match_reports_a_runner_up() -> None:
    """Two categories matching equally well is reported as ambiguous, not guessed.

    ``sensor`` (Electrical) and ``washer`` (Mechanical) are both six characters,
    so neither wins on specificity and the tie is surfaced instead of hidden.
    """
    match = material_classifier().classify("sensor washer")

    assert match.score == 6
    assert match.category == "Mechanical"  # declaration order breaks the tie
    assert match.runner_up == "Electrical"
    assert match.is_confident is False


def test_category_restriction_is_honoured() -> None:
    match = material_classifier().classify("bolt", categories=("Electrical",))

    assert match.category == "Uncategorised"


def test_known_categories_match_the_library_taxonomy() -> None:
    from app.config.constants import DEFAULT_MATERIAL_CATEGORIES

    categories = material_classifier().known_categories()

    assert set(categories) <= set(DEFAULT_MATERIAL_CATEGORIES)
    assert len(categories) == 10


def test_classifier_joins_multiple_sources() -> None:
    """A phrase split across columns must still be found."""
    match = material_classifier().classify("SKF", "LGMT 2 grease")

    assert match.category == "Chemical"