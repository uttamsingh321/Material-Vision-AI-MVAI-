"""Text normalisation and comparison helpers.

Deliberately dependency-free and deterministic: the Excel parser, the search
query builder and the confidence engine all normalise strings the same way, and
any divergence between them would silently degrade match quality.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

#: Runs of whitespace, collapsed everywhere.
_WHITESPACE_RE = re.compile(r"\s+")
#: Everything that is not a lower-case ASCII letter or digit.
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
#: Characters that carry no meaning when comparing part numbers.
_CODE_SEPARATORS_RE = re.compile(r"[\s\-_/\.]+")
#: A plausible model/part token: 3-32 chars with optional internal separators.
_MODEL_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-/\._]{2,31}$")
_UNITS_SUFFIX_RE = re.compile(
    r"\b(pcs?|pieces?|nos?|units?|each|ea|box|set|kit|pack|roll|mtr|meter|kg|gram"
    r"|litre|liter|ltr|ml)\b",
    re.IGNORECASE,
)
#: Ordered greedily so ``25.5`` never parses as ``25``.
_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)*")


def clean_text(value: object) -> str:
    """Coerce a spreadsheet cell to clean, single-spaced text.

    ``None`` and non-strings become ``""``; Unicode is NFKC-normalised so
    full-width digits and ligatures from an ERP export compare equal to their
    ASCII equivalents.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        # Spreadsheets yield int/float/datetime for numeric and date cells.
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFKC", value)).strip()


def normalise_header(value: object) -> str:
    """Comparison key for a column header: ``"Material No."`` -> ``"materialno"``."""
    return _NON_ALNUM_RE.sub("", clean_text(value).lower())


def normalise_code(value: object) -> str:
    """Normalise a part/material code for equality checks.

    Separators are *removed* rather than replaced, so ``"LC1-D18"``,
    ``"LC1 D18"`` and ``"lc1d18"`` all collapse to ``"lc1d18"``.
    """
    return _CODE_SEPARATORS_RE.sub("", clean_text(value).lower())


def slugify(value: object, *, max_length: int = 120, fallback: str = "unnamed") -> str:
    """Filesystem- and URL-safe slug.  Never returns an empty string."""
    slug = _NON_ALNUM_RE.sub("-", clean_text(value).lower()).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug or fallback


def tokenize(value: object) -> list[str]:
    """Split text into comparable tokens, preserving order and de-duplicating."""
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in _NON_ALNUM_RE.split(clean_text(value).lower()):
        if len(raw) < 2 or raw in seen:
            continue
        seen.add(raw)
        tokens.append(raw)
    return tokens


def token_set(value: object) -> set[str]:
    """Token set, for set-based similarity measures."""
    return set(tokenize(value))


def jaccard_similarity(left: object, right: object) -> float:
    """Jaccard index of the two token sets - 0.0 when either side is empty."""
    left_tokens, right_tokens = token_set(left), token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def sequence_similarity(left: object, right: object) -> float:
    """Character-level similarity in ``[0, 1]`` via ``difflib``.

    Catches near-miss part numbers (``LC1D18G7`` vs ``LC1D18G6``) that token
    overlap alone would score as a perfect match.
    """
    left_text, right_text = clean_text(left).lower(), clean_text(right).lower()
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    return SequenceMatcher(None, left_text, right_text).ratio()


def combined_similarity(left: object, right: object) -> float:
    """Blend of token overlap and character similarity.

    The character term is weighted higher because material codes differ by a
    single character far more often than descriptions differ by a single word.
    """
    return round(
        0.4 * jaccard_similarity(left, right) + 0.6 * sequence_similarity(left, right), 4
    )


def contains_normalised(haystack: object, needle: object) -> bool:
    """``True`` when ``needle`` occurs in ``haystack``, ignoring case/separators."""
    if not clean_text(needle):
        return False
    return normalise_code(needle) in normalise_code(haystack)


def parse_float(value: object) -> float | None:
    """Best-effort numeric parse of a spreadsheet cell.

    Handles thousands separators and trailing unit words
    (``"1,250.75 pcs"`` -> ``1250.75``).  Returns ``None`` when nothing numeric
    is present.  Booleans are rejected on purpose - ``True`` is not the number 1.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    match = _NUMBER_RE.search(clean_text(value).replace(",", ""))
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:  # pragma: no cover - the regex guarantees a numeral
        return None


def parse_int(value: object) -> int | None:
    """Integer variant of :func:`parse_float`."""
    number = parse_float(value)
    return None if number is None else int(number)


def strip_units(text: object) -> str:
    """Remove packaging/unit words so they do not pollute a search query."""
    return _WHITESPACE_RE.sub(" ", _UNITS_SUFFIX_RE.sub(" ", clean_text(text))).strip()


def truncate(value: object, limit: int, *, suffix: str = "…") -> str:
    """Shorten text to ``limit`` characters, appending ``suffix`` if cut."""
    text = clean_text(value)
    if limit <= 0 or len(text) <= limit:
        return text
    if limit <= len(suffix):
        return suffix[:limit]
    return text[: limit - len(suffix)].rstrip() + suffix


def extract_model_candidates(text: object, *, limit: int = 5) -> list[str]:
    """Pull part-number-looking tokens out of a free-text description.

    A token qualifies when it is 3-32 characters and mixes letters with digits
    (so bare measurements like ``230`` are skipped).  Candidates containing a
    separator rank first because catalogue numbers almost always do, and longer
    candidates outrank shorter ones.
    """
    candidates: list[str] = []
    seen: set[str] = set()

    for raw in clean_text(text).split(" "):
        token = raw.strip(".,;:()[]{}\"'")
        if not _MODEL_TOKEN_RE.match(token):
            continue
        if not any(char.isdigit() for char in token):
            continue
        if not any(char.isalpha() for char in token):
            continue
        key = normalise_code(token)
        if len(key) < 3 or key in seen:
            continue
        seen.add(key)
        candidates.append(token)

    candidates.sort(key=lambda token: (0 if "-" in token or "/" in token else 1, -len(token)))
    return candidates[:limit]


def first_non_empty(*values: object) -> str | None:
    """First value that normalises to a non-empty string, else ``None``."""
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return None
