"""Duplicate detector: the three signals, their priority and batch scanning."""

from __future__ import annotations

import pytest

from app.ai_engine import duplicate_detector as load_duplicate_detector
from app.models.enums import DuplicateMethod


@pytest.fixture()
def module():  # noqa: ANN201, ANN001
    """The ``ai-engine/duplicate_detector.py`` module, loaded via the bridge."""
    return load_duplicate_detector()


@pytest.fixture()
def detector(module):  # noqa: ANN001, ANN201
    return module.DuplicateDetector()


SHA_A = "a" * 64
SHA_B = "b" * 64
URL_A = "https://images.example.com/widget.png"
HASH_A = "1" * 64
#: Four bits away from HASH_A - inside the default distance of 6.
HASH_NEAR = "11110000" + "1" * 56


def test_bridge_exposes_the_module(module) -> None:  # noqa: ANN001
    assert module.__name__.endswith("duplicate_detector")
    assert "DuplicateDetector" in module.__all__
    assert module.duplicate_detector() is not None


# ---------------------------------------------------------------------------
# The three signals
# ---------------------------------------------------------------------------


def test_identical_bytes_are_a_duplicate(detector, module) -> None:  # noqa: ANN001
    detector.register(module.ImageFingerprint("a", sha256=SHA_A))
    match = detector.check(module.ImageFingerprint("b", sha256=SHA_A.lower()))

    assert match is not None
    assert match.method is DuplicateMethod.SHA256
    assert match.canonical_key == "a"
    assert match.key == "b"
    assert match.similarity == 1.0
    assert SHA_A[:16] in match.detail or SHA_A[:16].upper() in match.detail


def test_digest_case_is_ignored(detector, module) -> None:  # noqa: ANN001
    detector.register(module.ImageFingerprint("a", sha256=SHA_A.upper()))
    match = detector.check(module.ImageFingerprint("b", sha256=SHA_A.lower()))

    assert match is not None
    assert match.method is DuplicateMethod.SHA256


def test_equivalent_source_urls_collide(detector, module) -> None:  # noqa: ANN001
    detector.register(
        module.ImageFingerprint("a", source_url="https://www.Example.com/img.png#top")
    )
    match = detector.check(
        module.ImageFingerprint("b", source_url="https://example.com/img.png")
    )

    assert match is not None
    assert match.method is DuplicateMethod.SOURCE_URL
    assert match.similarity == 1.0


def test_different_paths_are_not_duplicates(detector, module) -> None:  # noqa: ANN001
    detector.register(module.ImageFingerprint("a", source_url=URL_A))
    match = detector.check(
        module.ImageFingerprint("b", source_url="https://images.example.com/other.png")
    )

    assert match is None


def test_near_identical_perceptual_hashes_match(detector, module) -> None:  # noqa: ANN001
    detector.register(module.ImageFingerprint("a", perceptual_hash=HASH_A))
    match = detector.check(module.ImageFingerprint("b", perceptual_hash=HASH_NEAR))

    assert match is not None
    assert match.method is DuplicateMethod.PERCEPTUAL_HASH
    assert match.similarity == pytest.approx(1 - 4 / 64)
    assert "distance 4 of 64 bits" in match.detail


def test_perceptual_hash_beyond_the_threshold_is_not_a_duplicate(
    detector, module
) -> None:  # noqa: ANN001
    detector.register(module.ImageFingerprint("a", perceptual_hash=HASH_A))
    far = "0" * 64

    assert detector.check(module.ImageFingerprint("b", perceptual_hash=far)) is None


def test_perceptual_hashes_of_different_lengths_are_incomparable(
    detector, module
) -> None:  # noqa: ANN001
    detector.register(module.ImageFingerprint("a", perceptual_hash="1" * 64))
    match = detector.check(module.ImageFingerprint("b", perceptual_hash="1" * 16))

    assert match is None


def test_max_distance_may_be_tuned(module) -> None:  # noqa: ANN001
    detector = module.DuplicateDetector(max_distance=0)
    detector.register(module.ImageFingerprint("a", perceptual_hash=HASH_A))

    assert detector.check(module.ImageFingerprint("b", perceptual_hash=HASH_NEAR)) is None

    with pytest.raises(ValueError, match="negative"):
        module.DuplicateDetector(max_distance=-1)


# ---------------------------------------------------------------------------
# Signal priority
# ---------------------------------------------------------------------------


def test_sha256_outranks_the_other_signals(detector, module) -> None:  # noqa: ANN001
    detector.register(
        module.ImageFingerprint("a", sha256=SHA_A, source_url=URL_A)
    )
    match = detector.check(
        module.ImageFingerprint("b", sha256=SHA_A, source_url=URL_A)
    )

    assert match is not None
    assert match.method is DuplicateMethod.SHA256


def test_perceptual_outranks_the_source_url(detector, module) -> None:  # noqa: ANN001
    detector.register(module.ImageFingerprint("a", perceptual_hash=HASH_A))
    # A different image hosted at a URL already seen: the visual evidence wins.
    detector.register(
        module.ImageFingerprint("c", perceptual_hash="0" * 64, source_url=URL_A)
    )
    match = detector.check(
        module.ImageFingerprint("b", perceptual_hash=HASH_NEAR, source_url=URL_A)
    )

    assert match is not None
    assert match.method is DuplicateMethod.PERCEPTUAL_HASH
    assert match.canonical_key == "a"


def test_a_fingerprint_with_no_signals_never_matches(detector, module) -> None:  # noqa: ANN001
    detector.register(module.ImageFingerprint("a", sha256=SHA_A))
    empty = module.ImageFingerprint("b")

    assert empty.has_signal is False
    assert detector.check(empty) is None
    # ...and it is not indexed either, so it cannot become a canonical copy.
    detector.register(module.ImageFingerprint("blank"))
    assert detector.registered_count == 1


# ---------------------------------------------------------------------------
# Batch scanning
# ---------------------------------------------------------------------------


def test_scan_keeps_the_first_occurrence_as_canonical(detector, module) -> None:  # noqa: ANN001
    matches = detector.scan(
        [
            module.ImageFingerprint("first", sha256=SHA_A),
            module.ImageFingerprint("dup-1", sha256=SHA_A),
            module.ImageFingerprint("unique", sha256=SHA_B),
            module.ImageFingerprint("dup-2", sha256=SHA_A),
        ]
    )

    assert [match.key for match in matches] == ["dup-1", "dup-2"]
    assert {match.canonical_key for match in matches} == {"first"}
    # Duplicates are reported, never indexed in their own right.
    assert detector.registered_count == 2
    assert len(detector) == 2


def test_scan_of_distinct_images_reports_nothing(detector, module) -> None:  # noqa: ANN001
    matches = detector.scan(
        [
            module.ImageFingerprint("a", sha256=SHA_A, perceptual_hash=HASH_A),
            module.ImageFingerprint(
                "b", sha256=SHA_B, perceptual_hash="0" * 64, source_url=URL_A
            ),
        ]
    )

    assert matches == []
    assert detector.registered_count == 2


def test_reregistering_the_same_key_is_idempotent(detector, module) -> None:  # noqa: ANN001
    item = module.ImageFingerprint("a", sha256=SHA_A, source_url=URL_A)
    detector.register(item)
    detector.register(item)

    assert detector.registered_count == 1


def test_clear_empties_every_index(detector, module) -> None:  # noqa: ANN001
    detector.register(
        module.ImageFingerprint(
            "a", sha256=SHA_A, perceptual_hash=HASH_A, source_url=URL_A
        )
    )
    detector.clear()

    assert detector.registered_count == 0
    assert detector.check(module.ImageFingerprint("b", sha256=SHA_A)) is None


def test_find_duplicates_is_a_one_shot_shortcut(module) -> None:  # noqa: ANN001
    matches = module.find_duplicates(
        [
            module.ImageFingerprint("a", sha256=SHA_A),
            module.ImageFingerprint("b", sha256=SHA_A),
        ]
    )

    assert len(matches) == 1
    assert matches[0].method is DuplicateMethod.SHA256


def test_detail_fits_the_persisted_column(detector, module) -> None:  # noqa: ANN001
    detector.register(
        module.ImageFingerprint("a", source_url="https://example.com/" + "x" * 900)
    )
    match = detector.check(
        module.ImageFingerprint("b", source_url="https://example.com/" + "x" * 900)
    )

    assert match is not None
    assert len(match.detail) <= module.MAX_DETAIL_LENGTH


def test_relative_urls_still_collide(detector, module) -> None:  # noqa: ANN001
    """``normalise_url`` rejects these - the detector must not lose them."""
    detector.register(module.ImageFingerprint("a", source_url="/images/bolt.png"))
    match = detector.check(module.ImageFingerprint("b", source_url="/IMAGES/bolt.png"))

    assert match is not None
    assert match.method is DuplicateMethod.SOURCE_URL
