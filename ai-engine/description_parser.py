"""Turn a raw ERP material description into structured, searchable signals.

Input is whatever the operator's workbook contains - for example
``"SCHNEIDER ELECTRIC LC1D18 CONTACTOR 18A 230VAC COIL 5 PCS"`` - and the output
is a :class:`MaterialDescriptor` carrying the brand, the model, a library
category and a search query a provider can actually use.

Everything is deterministic and side-effect free, so the same row always yields
the same signals and the pipeline stays reproducible across retries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.config.constants import UNCATEGORISED
from app.utils.text import (
    clean_text,
    extract_model_candidates,
    normalise_code,
    strip_units,
    truncate,
)

from .brand_detector import BrandDetector
from .material_classifier import MaterialClassifier

#: Parenthesised/bracketed asides rarely help a search engine.
_PARENTHETICAL_RE: Final = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
#: Words that carry no discriminating power in a product query.
_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "and",
        "any",
        "are",
        "assorted",
        "brand",
        "code",
        "each",
        "for",
        "from",
        "genuine",
        "grade",
        "item",
        "make",
        "material",
        "model",
        "new",
        "no",
        "number",
        "of",
        "original",
        "pack",
        "part",
        "piece",
        "purpose",
        "size",
        "spare",
        "standard",
        "the",
        "this",
        "type",
        "use",
        "used",
        "various",
        "with",
    }
)


def _strip_parentheticals(text: str) -> str:
    """Remove ``(...)``, ``[...]`` and ``{...}`` asides."""
    return re.sub(r"\s+", " ", _PARENTHETICAL_RE.sub(" ", text)).strip()


def _dedupe_words(text: str) -> str:
    """Drop repeated words, comparing them with separators removed.

    ``"LC1D18 LC1-D18"`` collapses to ``"LC1D18"``, which matters because the
    same catalogue number is frequently written both ways in one description.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for word in text.split(" "):
        key = normalise_code(word)
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(word)
    return " ".join(kept)


def _significant_keywords(text: str, *, limit: int) -> tuple[str, ...]:
    """Discriminating words from ``text``: long enough, and not a stopword."""
    keywords: list[str] = []
    seen: set[str] = set()
    for word in re.split(r"[^A-Za-z0-9\-/\.]+", text):
        token = word.strip("-/.")
        lowered = token.lower()
        if len(lowered) < 3 or lowered in _STOPWORDS or lowered in seen:
            continue
        seen.add(lowered)
        keywords.append(token)
        if len(keywords) >= limit:
            break
    return tuple(keywords)


@dataclass(frozen=True, slots=True)
class MaterialDescriptor:
    """Structured interpretation of one material description."""

    description: str
    brand: str | None
    brand_source: str
    brand_confidence: float
    model: str | None
    model_source: str
    model_candidates: tuple[str, ...]
    category: str
    category_source: str
    category_confidence: float
    keywords: tuple[str, ...]
    search_query: str

    @property
    def has_brand(self) -> bool:
        return bool(self.brand)

    @property
    def has_model(self) -> bool:
        """A model is what makes a manufacturer-scoped search precise."""
        return bool(self.model)

    @property
    def search_readiness(self) -> str:
        """How well-equipped the pipeline is to search for this material.

        ``"high"``   brand + model  - a manufacturer query will be precise
        ``"medium"`` brand or model - a general web query is needed
        ``"low"``    neither        - expect a review-queue item
        """
        if self.brand and self.model:
            return "high"
        if self.brand or self.model:
            return "medium"
        return "low"


@dataclass(frozen=True, slots=True)
class DescriptionParser:
    """Extracts structured signals from a free-text material description.

    Args:
        max_query_length: Hard ceiling on the generated search query, so a
            provider never receives a multi-kilobyte string.
        max_keywords: How many discriminating keywords to retain.
        brand_detector: Injectable for testing or for a custom dictionary.
        classifier: Injectable material classifier.
    """

    max_query_length: int = 200
    max_keywords: int = 12
    brand_detector: BrandDetector = BrandDetector()
    classifier: MaterialClassifier = MaterialClassifier()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def parse(
        self,
        description: object,
        *,
        brand: object = None,
        model: object = None,
        material_code: object = None,
        category: object = None,
        remarks: object = None,
        search_hint: object = None,
    ) -> MaterialDescriptor:
        """Interpret a material row.

        Explicit spreadsheet columns always win over inference: if the workbook
        says the brand is ``"Siemens"``, that is the brand, whatever the
        description looks like.
        """
        text = clean_text(description)
        code = clean_text(material_code)
        explicit_brand = clean_text(brand)
        explicit_model = clean_text(model)
        explicit_category = clean_text(category)

        resolved_brand, brand_source, brand_confidence = self._resolve_brand(
            explicit_brand, code, text
        )
        resolved_model, model_source, candidates = self._resolve_model(
            explicit_model, text, resolved_brand
        )
        resolved_category, category_source, category_confidence = self._resolve_category(
            explicit_category, text, code, remarks
        )

        return MaterialDescriptor(
            description=text,
            brand=resolved_brand,
            brand_source=brand_source,
            brand_confidence=brand_confidence,
            model=resolved_model,
            model_source=model_source,
            model_candidates=candidates,
            category=resolved_category,
            category_source=category_source,
            category_confidence=category_confidence,
            keywords=_significant_keywords(text, limit=self.max_keywords),
            search_query=self.build_search_query(
                text, brand=resolved_brand, model=resolved_model, extra=search_hint
            ),
        )

    # ------------------------------------------------------------------
    # Brand
    # ------------------------------------------------------------------
    def _resolve_brand(
        self, explicit: str, material_code: str, description: str
    ) -> tuple[str | None, str, float]:
        """Return ``(brand, source, confidence)``.

        Preference order: explicit column, then the material code (a code often
        embeds the vendor, e.g. ``SKF6205``), then the description.
        """
        if explicit:
            match = self.brand_detector.detect_in_text(explicit)
            canonical = match.brand if match else explicit
            return canonical, "explicit", 1.0

        for source_name, text in (("material_code", material_code), ("text", description)):
            detector_match = self.brand_detector.detect_in_text(text)
            if detector_match is None and source_name == "material_code":
                # Part codes often glue the vendor to the model: "SKF6205-2RS".
                detector_match = self.brand_detector.detect_in_code(text)
            if detector_match is not None:
                return detector_match.brand, source_name, detector_match.confidence

        return None, "none", 0.0

    # ------------------------------------------------------------------
    # Model
    # ------------------------------------------------------------------
    def _resolve_model(
        self, explicit: str, description: str, brand: str | None
    ) -> tuple[str | None, str, tuple[str, ...]]:
        """Return ``(model, source, all_candidates)``.

        The candidate list is returned in full so the pipeline can retry with
        the runner-up when the first choice finds nothing - a description like
        ``"18A 230VAC LC1D18"`` yields several plausible tokens.
        """
        candidates = extract_model_candidates(description)
        brand_key = normalise_code(brand) if brand else ""
        if brand_key:
            # A brand alias embedded in the description must not become the model.
            candidates = tuple(item for item in candidates if normalise_code(item) != brand_key)

        if explicit:
            return explicit, "explicit", candidates
        if candidates:
            return candidates[0], "text", candidates
        return None, "none", candidates

    # ------------------------------------------------------------------
    # Category
    # ------------------------------------------------------------------
    def _resolve_category(
        self, explicit: str, description: str, material_code: str, remarks: str
    ) -> tuple[str, str, float]:
        """Return ``(category, source, confidence)``.

        The classifier sees the code and remarks too, because a phrase is
        sometimes split across columns.
        """
        if explicit:
            return explicit, "explicit", 1.0

        match = self.classifier.classify(description, material_code, remarks)
        if match.category == UNCATEGORISED:
            return UNCATEGORISED, "default", 0.0

        # A decisive winner is trusted; an ambiguous one is recorded as such so
        # the confidence engine can discount it.
        return match.category, "classified", 0.8 if match.is_confident else 0.5

    # ------------------------------------------------------------------
    # Search query
    # ------------------------------------------------------------------
    def build_search_query(
        self,
        description: object,
        *,
        brand: object = None,
        model: object = None,
        extra: object = None,
    ) -> str:
        """Compose the query the providers will receive.

        Brand and model lead, because search engines weight the first terms most
        heavily; the descriptive tail then narrows the result set.  Packaging
        units and parenthetical asides are removed, and repeated words collapsed.
        """
        parts: list[str] = []
        for value in (brand, model):
            cleaned = clean_text(value)
            if cleaned:
                parts.append(cleaned)

        body = _strip_parentheticals(strip_units(clean_text(description)))
        if body:
            parts.append(body)

        cleaned_extra = clean_text(extra)
        if cleaned_extra:
            parts.append(_strip_parentheticals(cleaned_extra))

        joined = re.sub(r"\s+", " ", " ".join(parts)).strip()
        return truncate(_dedupe_words(joined), self.max_query_length)


#: Shared parser using the built-in dictionary and taxonomy.
parser = DescriptionParser()


def parse_description(description: object, **kwargs: object) -> MaterialDescriptor:
    """Module-level shortcut for :meth:`DescriptionParser.parse`."""
    return parser.parse(description, **kwargs)


def build_search_query(description: object, **kwargs: object) -> str:
    """Module-level shortcut for :meth:`DescriptionParser.build_search_query`."""
    return parser.build_search_query(description, **kwargs)


__all__ = [
    "DescriptionParser",
    "MaterialDescriptor",
    "build_search_query",
    "parse_description",
    "parser",
]
