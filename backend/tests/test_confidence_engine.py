"""Confidence engine: weighted combination, thresholds and coverage rules."""

from __future__ import annotations

import pytest

from app.ai_engine import confidence_engine as load_confidence_engine
from app.config import get_settings
from app.models.enums import ConfidenceBand, Decision


@pytest.fixture()
def module():  # noqa: ANN201, ANN001
    """The ``ai-engine/confidence_engine.py`` module, loaded via the bridge."""
    return load_confidence_engine()


@pytest.fixture()
def engine(module):  # noqa: ANN001, ANN201
    """An engine with simple, hand-checkable weights summing to 2.0."""
    return module.ConfidenceEngine(
        weights={
            "ocr": 0.4,
            "vision": 0.4,
            "brand": 0.4,
            "model": 0.4,
            "text": 0.4,
            "provider": 0.4,
        },
        accept_threshold=0.8,
        review_threshold=0.45,
    )


ALL_ONES = {
    "ocr": 1.0,
    "vision": 1.0,
    "brand": 1.0,
    "model": 1.0,
    "text": 1.0,
    "provider": 1.0,
}


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def test_bridge_exposes_the_module(module) -> None:  # noqa: ANN001
    assert module.ConfidenceEngine is not None
    assert module.__name__.endswith("confidence_engine")
    assert "score_confidence" in module.__all__


def test_settings_configured_engine_is_available(module) -> None:  # noqa: ANN001
    engine = module.confidence_engine()

    assert engine.accept_threshold == get_settings().confidence_accept_threshold
    assert sum(engine.weights.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Thresholds and bands
# ---------------------------------------------------------------------------


def test_perfect_evidence_is_auto_accepted(engine, module) -> None:  # noqa: ANN001
    report = engine.score(**ALL_ONES)

    assert report.overall == pytest.approx(1.0)
    assert report.band is ConfidenceBand.HIGH
    assert report.decision is Decision.AUTO_ACCEPT
    assert report.coverage == pytest.approx(1.0)
    assert report.missing_signals == ()
    assert report.is_auto_accepted is True
    assert isinstance(report.band, ConfidenceBand)


def test_zero_evidence_is_rejected_not_absent(engine) -> None:  # noqa: ANN001
    report = engine.score(ocr=0.0, vision=0.0, brand=0.0, model=0.0, text=0.0)

    # Signals *were* observed, so this is a real (bad) score, not "no verdict".
    assert report.overall == pytest.approx(0.0)
    assert report.band is ConfidenceBand.LOW
    assert report.decision is Decision.REJECT
    assert report.has_evidence is True


def test_no_signals_at_all_issues_no_verdict(engine, module) -> None:  # noqa: ANN001
    report = engine.score()

    assert report.overall == 0.0
    assert report.band is ConfidenceBand.NONE
    assert report.decision is Decision.REVIEW
    assert report.has_evidence is False
    assert report.observed_count == 0
    assert report.missing_signals == module.SIGNALS
    assert "no verdict issued" in report.explanation


def test_mid_range_evidence_lands_in_review(engine) -> None:  # noqa: ANN001
    report = engine.score(**{name: 0.6 for name in ALL_ONES})

    assert report.overall == pytest.approx(0.6)
    assert report.band is ConfidenceBand.MEDIUM
    assert report.decision is Decision.REVIEW


def test_weak_evidence_is_rejected(engine) -> None:  # noqa: ANN001
    report = engine.score(**{name: 0.3 for name in ALL_ONES})

    assert report.band is ConfidenceBand.LOW
    assert report.decision is Decision.REJECT


def test_threshold_boundary_is_inclusive(engine) -> None:  # noqa: ANN001
    assert engine.score(**{name: 0.8 for name in ALL_ONES}).decision is (
        Decision.AUTO_ACCEPT
    )
    assert engine.score(**{name: 0.45 for name in ALL_ONES}).decision is Decision.REVIEW
    assert engine.score(**{name: 0.44 for name in ALL_ONES}).decision is Decision.REJECT


# ---------------------------------------------------------------------------
# Missing signals: excluded, not zeroed
# ---------------------------------------------------------------------------


def test_unobserved_signal_does_not_drag_the_score_down(module) -> None:  # noqa: ANN001
    engine = module.ConfidenceEngine(
        weights={"ocr": 1.0, "vision": 1.0, "brand": 1.0},
        min_auto_accept_coverage=0.3,
    )
    report = engine.score(ocr=1.0)

    # A missing OCR/vision pair must not read as 1/3 of a perfect match.
    assert report.overall == pytest.approx(1.0)
    assert report.coverage == pytest.approx(1 / 3)
    assert report.missing_signals == ("vision", "brand")
    assert report.decision is Decision.AUTO_ACCEPT
    assert report.observed_count == 1


def test_thin_evidence_is_capped_at_review(module) -> None:  # noqa: ANN001
    engine = module.ConfidenceEngine(
        weights={"ocr": 0.9, "provider": 0.1},
        min_auto_accept_coverage=0.5,
    )
    report = engine.score(provider=1.0)

    # Perfect score, but the only witness is a 10%-weight signal.
    assert report.overall == pytest.approx(1.0)
    assert report.band is ConfidenceBand.HIGH
    assert report.coverage == pytest.approx(0.1)
    assert report.decision is Decision.REVIEW
    assert "coverage" in report.explanation
    assert "below the" in report.explanation


def test_coverage_gate_does_not_block_a_well_observed_accept(module) -> None:  # noqa: ANN001
    engine = module.ConfidenceEngine(
        weights={"ocr": 0.4, "vision": 0.4, "provider": 0.2},
        min_auto_accept_coverage=0.7,
    )
    report = engine.score(ocr=1.0, vision=1.0)

    assert report.coverage == pytest.approx(0.8)
    assert report.decision is Decision.AUTO_ACCEPT


def test_min_signals_short_circuits_to_no_verdict(module) -> None:  # noqa: ANN001
    engine = module.ConfidenceEngine(
        weights={"ocr": 1.0, "vision": 1.0, "brand": 1.0}, min_signals=2
    )
    report = engine.score(ocr=1.0)

    assert report.band is ConfidenceBand.NONE
    assert report.decision is Decision.REVIEW
    assert report.observed_count == 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_unknown_signal_is_rejected_rather_than_ignored(engine, module) -> None:  # noqa: ANN001
    with pytest.raises(module.UnknownSignalError, match="colour"):
        engine.score(colour=0.5)  # type: ignore[call-arg]

    with pytest.raises(module.UnknownSignalError, match="colour"):
        engine.score_components({"colour": 0.5})

    with pytest.raises(module.UnknownSignalError, match="colour"):
        module.ConfidenceEngine(weights={"colour": 1.0})


def test_scores_are_clamped_into_range(engine) -> None:  # noqa: ANN001
    report = engine.score_components(
        {"ocr": 5.0, "vision": -3.0, "brand": True, "model": False}
    )

    assert report.components["ocr"] == 1.0
    assert report.components["vision"] == 0.0
    assert report.components["brand"] == 1.0
    assert report.components["model"] == 0.0


@pytest.mark.parametrize("bad", ["high", float("nan"), float("inf"), object()])
def test_non_finite_or_non_numeric_scores_are_refused(engine, bad) -> None:  # noqa: ANN001
    with pytest.raises(ValueError):
        engine.score(ocr=bad)  # type: ignore[arg-type]


def test_inverted_thresholds_are_refused(module) -> None:  # noqa: ANN001
    with pytest.raises(ValueError, match="must not exceed"):
        module.ConfidenceEngine(
            weights={"ocr": 1.0}, accept_threshold=0.4, review_threshold=0.9
        )


def test_coverage_gate_outside_unit_interval_is_refused(module) -> None:  # noqa: ANN001
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        module.ConfidenceEngine(weights={"ocr": 1.0}, min_auto_accept_coverage=1.5)


def test_weights_are_normalised_on_construction(module) -> None:  # noqa: ANN001
    engine = module.ConfidenceEngine(weights={"ocr": 3.0, "vision": 1.0})

    assert sum(engine.weights.values()) == pytest.approx(1.0)
    assert engine.weights["ocr"] == pytest.approx(0.75)


def test_all_zero_weights_issue_no_verdict(module) -> None:  # noqa: ANN001
    engine = module.ConfidenceEngine(weights={"ocr": 0.0, "vision": 0.0})
    report = engine.score(ocr=1.0, vision=1.0)

    assert report.band is ConfidenceBand.NONE
    assert report.decision is Decision.REVIEW
    assert report.coverage == 0.0
    assert "no verdict issued" in report.explanation


# ---------------------------------------------------------------------------
# Persistence shape and shortcuts
# ---------------------------------------------------------------------------


def test_report_maps_onto_the_confidence_score_columns(engine) -> None:  # noqa: ANN001
    report = engine.score(ocr=0.9, vision=0.8, brand=0.7, model=0.7, text=0.6)
    fields = report.as_score_fields()

    assert set(fields) == {
        "overall",
        "band",
        "decision",
        "weights",
        "contributions",
        "explanation",
        "strategy",
        "missing_signals",
        "ocr_score",
        "vision_score",
        "brand_score",
        "model_score",
        "text_score",
        "provider_score",
    }
    assert fields["ocr_score"] == 0.9
    assert fields["provider_score"] is None
    assert fields["band"] is report.band
    assert fields["strategy"] == "weighted-v1"
    assert fields["missing_signals"] == ["provider"]


def test_contributions_explain_where_the_total_came_from(engine) -> None:  # noqa: ANN001
    report = engine.score(ocr=1.0, vision=0.5)

    assert set(report.contributions) == {"ocr", "vision"}
    assert report.contributions["ocr"] == pytest.approx(engine.weights["ocr"])
    assert report.contributions["vision"] == pytest.approx(
        engine.weights["vision"] * 0.5
    )
    observed_weight = sum(engine.weights[name] for name in report.contributions)
    assert sum(report.contributions.values()) / observed_weight == pytest.approx(
        report.overall
    )


def test_explanation_is_a_readable_sentence(engine) -> None:  # noqa: ANN001
    explanation = engine.score(ocr=0.9, vision=0.9, brand=0.9, text=0.9).explanation

    assert "coverage" in explanation
    assert "review" in explanation
    assert "accept" in explanation


def test_shortcut_helpers_score_with_current_settings(module) -> None:  # noqa: ANN001
    settings = get_settings()
    report = module.score_confidence(ocr=1.0, vision=1.0, brand=1.0, model=1.0)

    assert isinstance(report, module.ConfidenceReport)
    assert report.strategy == module.STRATEGY
    assert report.weights == pytest.approx(settings.confidence_weights)
    assert module.engine().accept_threshold == settings.confidence_accept_threshold
