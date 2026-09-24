"""Weighted confidence scoring: six signals in, one verdict out.

The signals match the columns persisted on ``ConfidenceScore``:

==========  =========================================================
``ocr``      text read from the image agrees with the material
``vision``   the vision model recognised the correct product
``brand``    the brand rendered on the image matches the parsed brand
``model``     the part number on the image matches the parsed model
``text``      the page title/snippet matches the description
``provider``  the source is a trusted manufacturer or distributor
==========  =========================================================

Two rules keep the number honest:

1. **A missing signal is excluded, not scored zero.**  A page with no OCR
   layer is not evidence that the *image* is wrong, so the weighted mean is
   taken over the signals that were actually observed, and ``coverage`` records
   how much of the total weight that observation carried.
2. **Thin evidence cannot auto-accept.**  Even a perfect score is held for
   review when the observed signals carry less than
   ``min_auto_accept_coverage`` of the total weight - otherwise a lone
   ``provider`` hit (10% of the weight) would be enough to accept an image
   without a human ever seeing it.

The output is deliberately shaped like the ``ConfidenceScore`` row, so
persisting a report is a straight ``ConfidenceScore(**report.as_score_fields())``.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Final, Mapping

from app.config import get_settings
from app.models.enums import ConfidenceBand, Decision

#: Signal names, in weight order.  Mirrors ``Settings.confidence_weights``.
SIGNALS: Final[tuple[str, ...]] = (
    "ocr",
    "vision",
    "brand",
    "model",
    "text",
    "provider",
)

#: Stored in ``ConfidenceScore.strategy`` so a retuned run can be told apart.
STRATEGY: Final[str] = "weighted-v1"

#: Signal -> ``ConfidenceScore`` column.
_COLUMNS: Final[Mapping[str, str]] = {name: f"{name}_score" for name in SIGNALS}


class UnknownSignalError(ValueError):
    """A component score was supplied for a signal this engine does not know."""


def _coerce(name: str, value: object) -> float | None:
    """Clamp one component score into ``[0, 1]``; ``None`` means unobserved."""
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        numeric = float(value)
        if not isfinite(numeric):
            raise ValueError(f"signal {name!r} must be finite, got {value!r}")
        return min(1.0, max(0.0, numeric))
    raise ValueError(f"signal {name!r} must be a number or None, got {value!r}")


@dataclass(frozen=True, slots=True)
class ConfidenceReport:
    """The auditable result of one scoring pass."""

    overall: float
    band: ConfidenceBand
    decision: Decision
    #: Every signal, with ``None`` where the source provided nothing.
    components: dict[str, float | None]
    #: The weights that were in force, for reproducibility after a retune.
    weights: dict[str, float]
    #: ``score x weight`` for each observed signal - the explanation.
    contributions: dict[str, float]
    #: Signals with no observation, in :data:`SIGNALS` order.
    missing_signals: tuple[str, ...]
    #: Share of the total weight that was actually observed, in ``[0, 1]``.
    coverage: float
    explanation: str
    strategy: str = STRATEGY

    @property
    def observed_count(self) -> int:
        """How many signals were observed."""
        return len(self.components) - len(self.missing_signals)

    @property
    def has_evidence(self) -> bool:
        """``False`` only when nothing at all was observed."""
        return self.observed_count > 0

    @property
    def is_auto_accepted(self) -> bool:
        """Convenience mirror of ``decision is AUTO_ACCEPT``."""
        return self.decision is Decision.AUTO_ACCEPT

    def as_score_fields(self) -> dict[str, Any]:
        """Keyword arguments for constructing a ``ConfidenceScore`` row."""
        fields: dict[str, Any] = {
            "overall": self.overall,
            "band": self.band,
            "decision": self.decision,
            "weights": dict(self.weights),
            "contributions": dict(self.contributions),
            "explanation": self.explanation,
            "strategy": self.strategy,
            "missing_signals": list(self.missing_signals),
        }
        for signal, column in _COLUMNS.items():
            fields[column] = self.components.get(signal)
        return fields


@dataclass(frozen=True, slots=True)
class ConfidenceEngine:
    """Combines component scores into an overall score, band and decision.

    Args:
        weights: signal -> weight.  Normalised automatically, so callers may
            pass either raw or already-normalised values.
        accept_threshold: overall at or above this is auto-accepted.
        review_threshold: overall at or above this (and below accept) is
            escalated to a human; below it the candidate is rejected.
        min_signals: observations required before any verdict is issued.
        min_auto_accept_coverage: fraction of total weight that must have been
            observed before ``AUTO_ACCEPT`` is permitted.
    """

    weights: Mapping[str, float]
    accept_threshold: float = 0.80
    review_threshold: float = 0.45
    min_signals: int = 1
    min_auto_accept_coverage: float = 0.5

    def __post_init__(self) -> None:
        unknown = set(self.weights) - set(SIGNALS)
        if unknown:
            raise UnknownSignalError(
                f"unknown signal(s) {sorted(unknown)}; expected a subset of {list(SIGNALS)}"
            )
        if self.review_threshold > self.accept_threshold:
            raise ValueError(
                "review_threshold must not exceed accept_threshold, got "
                f"{self.review_threshold} > {self.accept_threshold}"
            )
        if not 0.0 <= self.min_auto_accept_coverage <= 1.0:
            raise ValueError("min_auto_accept_coverage must be within [0, 1]")

        total = sum(float(value) for value in self.weights.values())
        # Frozen dataclass: object.__setattr__ is the supported way to normalise.
        if total > 0:
            object.__setattr__(
                self,
                "weights",
                {name: float(value) / total for name, value in self.weights.items()},
            )
        else:
            object.__setattr__(
                self, "weights", {name: 0.0 for name in self.weights}
            )

    @classmethod
    def from_settings(cls, settings: object = None) -> "ConfidenceEngine":
        """Build an engine from :func:`app.config.get_settings`."""
        resolved = settings if settings is not None else get_settings()
        return cls(
            weights=resolved.confidence_weights,
            accept_threshold=resolved.confidence_accept_threshold,
            review_threshold=resolved.confidence_review_threshold,
        )

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------
    def score(self, **signals: float | None) -> ConfidenceReport:
        """Score by keyword argument, e.g. ``score(ocr=0.9, text=0.7)``."""
        return self.score_components(signals)

    def score_components(
        self, components: Mapping[str, float | None]
    ) -> ConfidenceReport:
        """Score a mapping of signal -> value; ``None`` (or absent) = unobserved.

        Raises:
            UnknownSignalError: for a key outside :data:`SIGNALS`, so a typo
                cannot silently turn into "no evidence".
            ValueError: for a non-numeric or non-finite value.
        """
        unknown = set(components) - set(SIGNALS)
        if unknown:
            raise UnknownSignalError(
                f"unknown signal(s) {sorted(unknown)}; expected a subset of {list(SIGNALS)}"
            )

        coerced: dict[str, float | None] = {
            name: _coerce(name, components.get(name)) for name in SIGNALS
        }
        present = {
            name: value for name, value in coerced.items() if value is not None
        }
        missing = tuple(name for name in SIGNALS if name not in present)

        total_weight = sum(self.weights.values())
        observed_weight = sum(self.weights.get(name, 0.0) for name in present)
        coverage = observed_weight / total_weight if total_weight > 0 else 0.0
        contributions = {
            name: value * self.weights.get(name, 0.0)
            for name, value in present.items()
        }

        if len(present) < self.min_signals or observed_weight <= 0:
            # Not enough evidence to judge: say so rather than invent a number.
            return ConfidenceReport(
                overall=0.0,
                band=ConfidenceBand.NONE,
                decision=Decision.REVIEW,
                components=coerced,
                weights=dict(self.weights),
                contributions=contributions,
                missing_signals=missing,
                coverage=coverage,
                explanation=(
                    f"Only {len(present)} of {len(SIGNALS)} signals observed "
                    f"(coverage {coverage:.0%}); no verdict issued, held for review."
                ),
            )

        overall = sum(contributions.values()) / observed_weight
        band = self._band(overall)
        decision = self._decision(overall)

        # Rule 2: perfect score on almost no evidence is still not auto-safe.
        capped = (
            decision is Decision.AUTO_ACCEPT
            and coverage < self.min_auto_accept_coverage
        )
        if capped:
            decision = Decision.REVIEW

        return ConfidenceReport(
            overall=overall,
            band=band,
            decision=decision,
            components=coerced,
            weights=dict(self.weights),
            contributions=contributions,
            missing_signals=missing,
            coverage=coverage,
            explanation=self._explain(
                overall, band, decision, len(present), coverage, capped
            ),
        )

    # ------------------------------------------------------------------
    # Thresholds
    # ------------------------------------------------------------------
    def _band(self, overall: float) -> ConfidenceBand:
        if overall >= self.accept_threshold:
            return ConfidenceBand.HIGH
        if overall >= self.review_threshold:
            return ConfidenceBand.MEDIUM
        return ConfidenceBand.LOW

    def _decision(self, overall: float) -> Decision:
        if overall >= self.accept_threshold:
            return Decision.AUTO_ACCEPT
        if overall >= self.review_threshold:
            return Decision.REVIEW
        return Decision.REJECT

    def _explain(
        self,
        overall: float,
        band: ConfidenceBand,
        decision: Decision,
        observed: int,
        coverage: float,
        capped: bool,
    ) -> str:
        """One sentence a reviewer can read without opening the components."""
        if capped:
            return (
                f"Overall {overall:.2f} ({band.value}) from {observed} of "
                f"{len(SIGNALS)} signals, but coverage {coverage:.0%} is below the "
                f"{self.min_auto_accept_coverage:.0%} needed to auto-accept; "
                "held for human review."
            )
        if decision is Decision.AUTO_ACCEPT:
            action = "auto-accepted"
        elif decision is Decision.REVIEW:
            action = "held for human review"
        else:
            action = "rejected"
        return (
            f"Overall {overall:.2f} ({band.value}) from {observed} of "
            f"{len(SIGNALS)} signals, coverage {coverage:.0%}; {action} at "
            f"thresholds review {self.review_threshold:.2f} / "
            f"accept {self.accept_threshold:.2f}."
        )


# ---------------------------------------------------------------------------
# Module-level shortcuts
# ---------------------------------------------------------------------------


def confidence_engine() -> ConfidenceEngine:
    """An engine built from the current settings."""
    return ConfidenceEngine.from_settings()


def score_confidence(**signals: float | None) -> ConfidenceReport:
    """Score with a settings-configured engine."""
    return confidence_engine().score(**signals)


engine = confidence_engine


__all__ = [
    "ConfidenceEngine",
    "ConfidenceReport",
    "SIGNALS",
    "STRATEGY",
    "UnknownSignalError",
    "confidence_engine",
    "engine",
    "score_confidence",
]

