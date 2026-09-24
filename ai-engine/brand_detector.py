"""Brand detection from free-text descriptions, part codes and source domains.

Pure Python and dependency-free on purpose: this runs for every row of every
upload, and a heavy NLP stack would cost more than the accuracy it buys.  The
dictionary is data, not code - extend ``_BRAND_TABLE`` to teach MVAI a vendor.

Matching is *phrase* based on a normalised haystack, so
``"Schneider Electric LC1D18"`` resolves to ``Schneider Electric`` rather than
to the shorter ``Schneider`` alias: longest alias wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Iterable
from urllib.parse import urlsplit

#: ``(canonical name, aliases, domains)``.  Aliases match as whole words on a
#: normalised haystack; domains match against a URL host.
_BRAND_TABLE: Final[tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]] = (
    ("3M", ("3m", "scotch", "scotchlok", "scotch-brite"), ("3m.com",)),
    ("ABB", ("abb",), ("abb.com",)),
    ("Amphenol", ("amphenol",), ("amphenol.com",)),
    ("Bahco", ("bahco",), ("bahco.com",)),
    ("Balluff", ("balluff",), ("balluff.com",)),
    ("Banner Engineering", ("banner engineering", "banner"), ("bannerengineering.com",)),
    ("Bosch Rexroth", ("bosch rexroth", "rexroth"), ("boschrexroth.com",)),
    ("Bussmann", ("bussmann", "cooper bussmann"), ("eaton.com",)),
    ("Datalogic", ("datalogic",), ("datalogic.com",)),
    ("Delta Electronics", ("delta electronics", "deltaww"), ("deltaww.com",)),
    ("Desco", ("desco",), ("desco.com",)),
    ("Digi-Key", ("digikey", "digi-key"), ("digikey.com", "digikey.in")),
    ("Eaton", ("eaton", "moeller"), ("eaton.com",)),
    ("Extech", ("extech",), ("extech.com",)),
    ("Festo", ("festo",), ("festo.com",)),
    ("Fluke", ("fluke",), ("fluke.com",)),
    ("Gedore", ("gedore",), ("gedore.com",)),
    ("Grainger", ("grainger",), ("grainger.com",)),
    ("Hager", ("hager",), ("hager.com",)),
    ("Henkel", ("henkel", "loctite"), ("henkel.com", "loctite.com")),
    ("Honeywell", ("honeywell",), ("honeywell.com",)),
    ("JST", ("jst",), ("jst.com",)),
    ("Keyence", ("keyence",), ("keyence.com",)),
    ("Knipex", ("knipex",), ("knipex.com",)),
    ("Legrand", ("legrand",), ("legrand.com",)),
    ("Littelfuse", ("littelfuse",), ("littelfuse.com",)),
    ("Mean Well", ("mean well", "meanwell"), ("meanwell.com",)),
    ("Misumi", ("misumi",), ("misumi.com", "in.misumi-ec.com")),
    (
        "Mitsubishi Electric",
        ("mitsubishi electric", "mitsubishi"),
        ("mitsubishielectric.com",),
    ),
    ("Mitutoyo", ("mitutoyo",), ("mitutoyo.com",)),
    ("Molex", ("molex",), ("molex.com",)),
    ("Mouser", ("mouser", "mouser electronics"), ("mouser.com", "mouser.in")),
    ("Murata", ("murata",), ("murata.com",)),
    ("NSK", ("nsk",), ("nsk.com",)),
    ("NTN", ("ntn",), ("ntn.co.jp",)),
    ("Nitto", ("nitto",), ("nitto.com",)),
    ("Omron", ("omron",), ("omron.com", "ia.omron.com")),
    ("Panasonic", ("panasonic",), ("panasonic.com", "industrial.panasonic.com")),
    ("Parker Hannifin", ("parker hannifin", "parker"), ("parker.com",)),
    (
        "Pepperl+Fuchs",
        ("pepperl+fuchs", "pepperl fuchs", "pepperl"),
        ("pepperl-fuchs.com",),
    ),
    ("Phoenix Contact", ("phoenix contact", "phoenixcontact"), ("phoenixcontact.com",)),
    ("RS PRO", ("rs pro", "rs components", "rspro"), ("rs-online.com", "in.rsdelivers.com")),
    (
        "Rockwell Automation",
        ("rockwell automation", "allen bradley", "allen-bradley"),
        ("rockwellautomation.com",),
    ),
    ("SICK", ("sick ag", "sick"), ("sick.com",)),
    ("SKF", ("skf",), ("skf.com",)),
    ("SMC", ("smc corporation", "smc pneumatics"), ("smcworld.com",)),
    ("Schaeffler", ("schaeffler", "ina", "fag"), ("schaeffler.com",)),
    (
        "Schneider Electric",
        ("schneider electric", "schneider", "telemecanique", "square d", "apc"),
        ("se.com", "schneider-electric.com"),
    ),
    ("Schurter", ("schurter",), ("schurter.com",)),
    ("Sealed Air", ("sealed air",), ("sealedair.com",)),
    ("Shin-Etsu", ("shin-etsu", "shin etsu"), ("shinetsu.com",)),
    ("Siemens", ("siemens",), ("siemens.com", "mall.industry.siemens.com")),
    ("Stanley", ("stanley", "stanley tools"), ("stanleytools.com",)),
    ("Starrett", ("starrett",), ("starrett.com",)),
    ("Staticide", ("staticide", "acl staticide"), ("aclstaticide.com",)),
    ("TDK", ("tdk", "epcos"), ("tdk.com", "product.tdk.com")),
    ("TE Connectivity", ("te connectivity", "tyco electronics", "tyco"), ("te.com",)),
    ("Tesa", ("tesa",), ("tesa.com",)),
    ("Timken", ("timken",), ("timken.com",)),
    ("Toshiba", ("toshiba",), ("toshiba.com",)),
    ("Turck", ("turck", "hans turck"), ("turck.com",)),
    ("Uline", ("uline",), ("uline.com",)),
    ("Vishay", ("vishay",), ("vishay.com",)),
    ("Wago", ("wago",), ("wago.com",)),
    ("Weidmuller", ("weidmuller", "weidmüller"), ("weidmueller.com",)),
    ("Wera", ("wera",), ("wera.de",)),
    ("Wiha", ("wiha",), ("wiha.com",)),
    ("Wurth Elektronik", ("wurth elektronik", "würth elektronik"), ("we-online.com",)),
    ("Yageo", ("yageo",), ("yageo.com",)),
    ("ifm electronic", ("ifm electronic", "ifm"), ("ifm.com",)),
)

#: Anything that is not a letter, digit, ``+`` or whitespace becomes a space, so
#: ``"Pepperl+Fuchs,"`` and ``"pepperl fuchs"`` normalise identically.
_NORMALISE_RE = re.compile(r"[^a-z0-9+\s]+")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalise(value: object) -> str:
    """Lower-case, strip punctuation (keeping ``+``), collapse whitespace."""
    if value is None:
        return ""
    text = _NORMALISE_RE.sub(" ", str(value).lower())
    return _WHITESPACE_RE.sub(" ", text).strip()


def _host_of(url: object) -> str:
    """Lower-case host of ``url``, tolerating bare domains such as ``se.com/x``."""
    if not url:
        return ""
    text = str(url).strip().lower()
    if not text:
        return ""
    candidate = text if "://" in text or text.startswith("//") else f"https://{text}"
    try:
        host = urlsplit(candidate).hostname or ""
    except ValueError:
        return ""
    return host.strip().strip(".")


#: ``alias -> canonical`` for every alias, and ``domain -> canonical``.
_ALIAS_INDEX: Final[dict[str, str]] = {
    _normalise(alias): canonical
    for canonical, aliases, _domains in _BRAND_TABLE
    for alias in aliases
}
#: Hosts are compared verbatim apart from case, so hyphens and dots must survive
#: (``rs-online.com`` must not collapse to ``rsonlinecom``).
_DOMAIN_INDEX: Final[dict[str, str]] = {
    str(domain).strip().lower(): canonical
    for canonical, _aliases, domains in _BRAND_TABLE
    for domain in domains
}
#: Brand label inside a domain - the label immediately before the TLD, so
#: ``in.misumi-ec.com`` yields ``misumi-ec`` and ``mall.industry.siemens.com``
#: yields ``siemens``.  Labels shorter than three characters are skipped; those
#: brands (``se``, ``3m``, ``te``) are still resolved, but only by the exact
#: host check above, which cannot collide with a generic host label.
_LABEL_INDEX: Final[dict[str, str]] = {
    labels[-2]: canonical
    for domain, canonical in _DOMAIN_INDEX.items()
    if len(labels := domain.split(".")) >= 2 and len(labels[-2]) >= 3
}
#: Aliases longest-first, so the most specific phrase is tested first.
_SORTED_ALIASES: Final[tuple[str, ...]] = tuple(sorted(_ALIAS_INDEX, key=len, reverse=True))

#: One boundary-anchored pattern per alias, compiled once at import time.
#: The lookarounds avoid false hits such as "abb" inside "abbott".
_ALIAS_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (alias, re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"))
    for alias in _SORTED_ALIASES
)

#: Brand glued to the front of a part code: ``skf6205`` -> ``skf``.
#: Whole-word patterns cannot see this, because the alias is immediately
#: followed by a digit rather than a boundary.
_CODE_PREFIX_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (alias, re.compile(rf"^{re.escape(alias)}(?=[0-9])"))
    for alias in _SORTED_ALIASES
    if len(alias) >= 2
)


@dataclass(frozen=True, slots=True)
class BrandMatch:
    """A resolved brand plus the evidence that produced it."""

    brand: str
    matched_on: str
    source: str
    confidence: float

    @property
    def is_confident(self) -> bool:
        """``True`` when the match is strong enough to trust without review."""
        return self.confidence >= 0.8


@dataclass(frozen=True, slots=True)
class BrandDetector:
    """Resolves brands from text and from URLs.

    Stateless and cheap to construct: the indices and patterns are built once at
    import time, so constructing an instance per material costs nothing.
    """

    min_confidence: float = 0.5

    def detect(self, *sources: object) -> BrandMatch | None:
        """Scan ``sources`` in order and return the first confident match.

        Each source is tested for a whole-word alias first, then for a brand
        glued to the front of a part code.  Passing the material code before the
        description therefore lets a code-embedded brand (``"SKF6205-2RS"``) win
        over a noisy free-text description.
        """
        for source in sources:
            match = self.detect_in_text(source) or self.detect_in_code(source)
            if match is not None and match.confidence >= self.min_confidence:
                return match
        return None

    def detect_in_text(self, text: object) -> BrandMatch | None:
        """Longest-alias whole-word match, or ``None``."""
        haystack = _normalise(text)
        if not haystack:
            return None

        for alias, pattern in _ALIAS_PATTERNS:
            if pattern.search(haystack):
                return BrandMatch(
                    brand=_ALIAS_INDEX[alias],
                    matched_on=alias,
                    source="text",
                    # Multi-word aliases are far less likely to be false hits.
                    confidence=0.9 if " " in alias else 0.85,
                )
        return None

    def detect_in_code(self, code: object) -> BrandMatch | None:
        """Detect a brand glued to the front of a part code.

        ``"SKF6205-2RS"`` carries its vendor in the first token, and whole-word
        matching cannot see it because ``skf`` is followed by a digit rather than
        a boundary.  A brand immediately followed by digits is unambiguous, so it
        is accepted at slightly reduced confidence.
        """
        haystack = _normalise(code)
        if not haystack:
            return None

        for alias, pattern in _CODE_PREFIX_PATTERNS:
            if pattern.match(haystack):
                return BrandMatch(
                    brand=_ALIAS_INDEX[alias],
                    matched_on=alias,
                    source="code",
                    confidence=0.8,
                )
        return None

    def detect_in_url(self, url: object) -> BrandMatch | None:
        """Match a brand against a URL host (``www.se.com`` -> Schneider Electric).

        The host is extracted with :func:`urllib.parse.urlsplit` rather than by
        string surgery: collapsing a URL to letters-only destroys the very
        boundaries (dots, hyphens) that host matching depends on.
        """
        host = _host_of(url)
        if not host:
            return None

        for domain, canonical in _DOMAIN_INDEX.items():
            if host == domain or host.endswith(f".{domain}"):
                return BrandMatch(
                    brand=canonical, matched_on=domain, source="domain", confidence=1.0
                )

        # Fall back to the brand label inside the host, so ``www.abb.co.in`` and
        # ``in.misumi-ec.com`` still resolve.
        for label in reversed(host.split(".")):
            if label in _LABEL_INDEX:
                return BrandMatch(
                    brand=_LABEL_INDEX[label],
                    matched_on=label,
                    source="domain",
                    confidence=0.95,
                )
        return None

    def known_brands(self) -> tuple[str, ...]:
        """Canonical brand names, in declaration order."""
        return tuple(canonical for canonical, _aliases, _domains in _BRAND_TABLE)

    def aliases_for(self, brand: str) -> tuple[str, ...]:
        """Every alias registered for ``brand`` (case-insensitive lookup)."""
        target = brand.strip().lower()
        for canonical, aliases, _domains in _BRAND_TABLE:
            if canonical.lower() == target:
                return aliases
        return ()

    def domains_for(self, brand: str) -> tuple[str, ...]:
        """Manufacturer domains registered for ``brand``."""
        target = brand.strip().lower()
        for canonical, _aliases, domains in _BRAND_TABLE:
            if canonical.lower() == target:
                return domains
        return ()


#: Shared instance - the detector is immutable, so sharing is safe.
detector = BrandDetector()


def detect_brand(*sources: object) -> BrandMatch | None:
    """Module-level shortcut for :meth:`BrandDetector.detect`."""
    return detector.detect(*sources)


def detect_in_text(text: object) -> BrandMatch | None:
    """Module-level shortcut for :meth:`BrandDetector.detect_in_text`."""
    return detector.detect_in_text(text)


def detect_in_url(url: object) -> BrandMatch | None:
    """Module-level shortcut for :meth:`BrandDetector.detect_in_url`."""
    return detector.detect_in_url(url)


def detect_in_code(code: object) -> BrandMatch | None:
    """Module-level shortcut for :meth:`BrandDetector.detect_in_code`."""
    return detector.detect_in_code(code)


def brand_names() -> tuple[str, ...]:
    """All known canonical brand names."""
    return detector.known_brands()


def detect_brands(texts: Iterable[object]) -> list[BrandMatch]:
    """Every distinct brand found across ``texts``, in encounter order."""
    found: list[BrandMatch] = []
    seen: set[str] = set()
    for text in texts:
        match = detector.detect_in_text(text)
        if match is not None and match.brand not in seen:
            seen.add(match.brand)
            found.append(match)
    return found


def normalise_brand(value: object) -> str | None:
    """Best-effort canonicalisation of a brand string.

    Falls back to a lightly cleaned version of the input when the brand is not
    in the dictionary - an unknown vendor must never be silently discarded.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    match = detector.detect_in_text(text)
    if match is not None:
        return match.brand

    cleaned = _WHITESPACE_RE.sub(" ", text)
    return cleaned.title() if cleaned.islower() or cleaned.isupper() else cleaned


__all__ = [
    "BrandDetector",
    "BrandMatch",
    "brand_names",
    "detect_brand",
    "detect_brands",
    "detect_in_code",
    "detect_in_text",
    "detect_in_url",
    "detector",
    "normalise_brand",
]


#: Guard against accidental use as a script, which would bypass the loader in
#: ``backend.app.ai_engine`` and therefore see a different module identity.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(
        "brand_detector is a library module; import it via "
        "backend.app.ai_engine.brand_detector()."
    )
