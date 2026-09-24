"""Rule-based placement of a material into the ``image-library`` taxonomy.

The taxonomy mirrors the folder tree (Electrical, Mechanical, Chemical, ...) and
every material must land in exactly one folder, so the decision must be
deterministic and explainable.

Scoring rule: a category's score is the length of its **longest matching
phrase**, not the number of matches.  That makes ``"bearing grease"`` resolve to
Chemical (the 15-character phrase) rather than to Bearings (the 7-character
``bearing``), which counting alone would get wrong.  Declaration order only
breaks ties, so the table is ordered most-specific-first.

The keyword table is data: extend ``_CATEGORY_KEYWORDS`` to teach MVAI a term.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from app.config.constants import DEFAULT_MATERIAL_CATEGORIES, UNCATEGORISED

#: Ordered by specificity: the *first* category wins a score tie.
_CATEGORY_KEYWORDS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "Bearings",
        (
            "ball bearing",
            "roller bearing",
            "tapered roller",
            "spherical roller",
            "needle roller",
            "thrust bearing",
            "pillow block",
            "plummer block",
            "bearing housing",
            "linear guide",
            "linear rail",
            "linear bearing",
            "slewing ring",
            "deep groove",
            "bearing",
            "bushing",
        ),
    ),
    (
        "Connectors",
        (
            "terminal block",
            "circular connector",
            "heavy duty connector",
            "pin header",
            "contact pin",
            "patch cord",
            "d sub",
            "dsub",
            "rj45",
            "backshell",
            "connector",
            "receptacle",
            "header",
            "crimp",
            "ferrule",
            "pigtail",
            "coupler",
            "plug",
            "socket",
            "jack",
            "usb",
            "hdmi",
        ),
    ),
    (
        "ESD",
        (
            "static dissipative",
            "anti static",
            "antistatic",
            "wrist strap",
            "heel strap",
            "esd mat",
            "esd bag",
            "shielding bag",
            "conductive bag",
            "grounding cord",
            "pink poly",
            "ioniser",
            "ionizer",
            "electrostatic",
            "esd",
        ),
    ),
    (
        "Tools",
        (
            "torque wrench",
            "crimping tool",
            "stripping tool",
            "tape measure",
            "tap and die",
            "drill bit",
            "hex key",
            "allen key",
            "socket set",
            "micrometer",
            "caliper",
            "wrench",
            "spanner",
            "screwdriver",
            "pliers",
            "nipper",
            "hammer",
            "chisel",
            "tweezers",
            "ratchet",
            "reamer",
            "hacksaw",
            "punch",
            "blade",
        ),
    ),
    (
        "Consumables",
        (
            "cutting wheel",
            "grinding disc",
            "welding rod",
            "cotton swab",
            "cable tie",
            "tie wrap",
            "heat shrink",
            "shrink tube",
            "insulation tape",
            "teflon tape",
            "paper towel",
            "ear plug",
            "earplug",
            "sand paper",
            "sandpaper",
            "gloves",
            "glove",
            "wipe",
            "cloth",
            "rag",
            "mask",
            "respirator",
            "apron",
            "sleeve",
            "tissue",
            "swab",
            "desiccant",
            "abrasive",
        ),
    ),
    (
        "Packaging",
        (
            "stretch film",
            "stretch wrap",
            "shrink film",
            "bubble wrap",
            "air pillow",
            "corner board",
            "edge protector",
            "void fill",
            "foam insert",
            "euro pallet",
            "corrugated",
            "poly bag",
            "strapping",
            "carton",
            "pallet",
            "pouch",
            "crate",
            "tray",
            "label",
            "box",
            "tape",
        ),
    ),
    (
        "Chemical",
        (
            "isopropyl alcohol",
            "bearing grease",
            "rust preventive",
            "cutting fluid",
            "thread locking",
            "threadlocker",
            "anti seize",
            "cyanoacrylate",
            "solder paste",
            "adhesive",
            "sealant",
            "lubricant",
            "degreaser",
            "anaerobic",
            "silicone",
            "solvent",
            "thinner",
            "cleaner",
            "primer",
            "coating",
            "loctite",
            "acetone",
            "coolant",
            "grease",
            "flux",
            "paint",
            "epoxy",
            "glue",
            "oil",
        ),
    ),
    (
        "Fixtures",
        (
            "toggle clamp",
            "angle plate",
            "magnetic base",
            "work holding",
            "face plate",
            "v block",
            "sine bar",
            "tooling",
            "locator",
            "mandrel",
            "collet",
            "fixture",
            "clamp",
            "vise",
            "chuck",
            "standoff",
            "jig",
        ),
    ),
    (
        "Mechanical",
        (
            "retaining ring",
            "solenoid valve",
            "pneumatic cylinder",
            "mounting bracket",
            "oil seal",
            "shaft seal",
            "o ring",
            "circlip",
            "coupling",
            "sprocket",
            "cylinder",
            "gasket",
            "flange",
            "pulley",
            "sheave",
            "pinion",
            "spring",
            "washer",
            "rivet",
            "screw",
            "valve",
            "elbow",
            "reducer",
            "fitting",
            "bracket",
            "chain",
            "shaft",
            "plate",
            "bolt",
            "nut",
            "stud",
            "gear",
            "rack",
            "pipe",
            "belt",
            "rod",
            "key",
            "pin",
        ),
    ),
    (
        "Electrical",
        (
            "overload relay",
            "push button",
            "selector switch",
            "indicator lamp",
            "cable gland",
            "power supply",
            "fuse holder",
            "bus bar",
            "din rail",
            "contactor",
            "transformer",
            "thermostat",
            "capacitor",
            "resistor",
            "inductor",
            "rectifier",
            "transistor",
            "inverter",
            "starter",
            "encoder",
            "breaker",
            "buzzer",
            "heater",
            "ballast",
            "driver",
            "sensor",
            "counter",
            "smps",
            "cable",
            "motor",
            "drive",
            "relay",
            "switch",
            "timer",
            "fuse",
            "lamp",
            "wire",
            "diode",
            "plc",
            "hmi",
            "pcb",
            "led",
            "fan",
            "lug",
        ),
    ),
)

#: ``category -> ((phrase, compiled pattern), ...)``.
_COMPILED: Final[MappingProxyType] = MappingProxyType(
    {
        category: tuple(
            (
                phrase,
                # A trailing ``s?`` handles the plural of the final word
                # ("cable tie" -> "cable ties") without matching inside a longer
                # word: "pin" must not match "pine".
                re.compile(rf"(?<![a-z0-9]){re.escape(phrase)}s?(?![a-z0-9])"),
            )
            for phrase in phrases
        )
        for category, phrases in _CATEGORY_KEYWORDS
    }
)

_NORMALISE_RE = re.compile(r"[^a-z0-9+\s]+")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalise(value: object) -> str:
    """Lower-case, replace punctuation with spaces, collapse whitespace."""
    if value is None:
        return ""
    text = _NORMALISE_RE.sub(" ", str(value).lower())
    return _WHITESPACE_RE.sub(" ", text).strip()


@dataclass(frozen=True, slots=True)
class CategoryMatch:
    """The winning category plus the evidence behind it."""

    category: str
    score: int
    matched_terms: tuple[str, ...] = ()
    runner_up: str | None = None

    @property
    def is_confident(self) -> bool:
        """``True`` when one category won decisively.

        A tie (or a single weak hit) is not decisive, and the caller may prefer
        to leave the material in ``Uncategorised`` rather than guess.
        """
        return self.category != UNCATEGORISED and self.runner_up is None


@dataclass(frozen=True, slots=True)
class MaterialClassifier:
    """Deterministic category assignment.

    ``categories`` restricts the search to a caller-supplied taxonomy; anything
    outside it is ignored.  ``min_score`` is the length of the shortest phrase
    that counts, which lets a caller demand more specificity.
    """

    categories: tuple[str, ...] = DEFAULT_MATERIAL_CATEGORIES
    min_score: int = 3

    def classify(self, *sources: object) -> CategoryMatch:
        """Classify from one or more text fragments (description, code, ...).

        Sources are joined so that a phrase split across the description and the
        remarks column is still found.
        """
        haystack = _normalise(" ".join(str(source) for source in sources if source))
        if not haystack:
            return CategoryMatch(category=UNCATEGORISED, score=0)

        allowed = {category.lower() for category in self.categories}
        scored: list[tuple[int, int, str, tuple[str, ...]]] = []

        for order, (category, entries) in enumerate(_COMPILED.items()):
            if category.lower() not in allowed:
                continue
            hits = tuple(phrase for phrase, pattern in entries if pattern.search(haystack))
            if not hits:
                continue
            # Longest phrase decides - see the module docstring.
            best = max(len(phrase) for phrase in hits)
            if best < self.min_score:
                continue
            scored.append((best, order, category, hits))

        if not scored:
            return CategoryMatch(category=UNCATEGORISED, score=0)

        # Highest score wins; declaration order (most specific first) breaks ties.
        scored.sort(key=lambda row: (-row[0], row[1]))
        score, _order, category, hits = scored[0]
        runner_up = scored[1][2] if len(scored) > 1 and scored[1][0] == score else None

        return CategoryMatch(
            category=category,
            score=score,
            matched_terms=tuple(sorted(hits, key=len, reverse=True)),
            runner_up=runner_up,
        )

    def available_categories(self) -> tuple[str, ...]:
        """The taxonomy this instance classifies into."""
        return tuple(self.categories)


#: Shared instance using the default taxonomy.
classifier = MaterialClassifier()


def classify(*sources: object, categories: tuple[str, ...] | None = None) -> CategoryMatch:
    """Classify text into one of the image-library categories."""
    if categories is None:
        return classifier.classify(*sources)
    return MaterialClassifier(categories=categories).classify(*sources)


def category_for(*sources: object) -> str:
    """Category name only - the common case for folder placement."""
    return classify(*sources).category


def known_categories() -> tuple[str, ...]:
    """Every category the classifier can emit (excluding ``Uncategorised``)."""
    return tuple(category for category, _phrases in _CATEGORY_KEYWORDS)


__all__ = [
    "CategoryMatch",
    "MaterialClassifier",
    "category_for",
    "classify",
    "classifier",
    "known_categories",
]

