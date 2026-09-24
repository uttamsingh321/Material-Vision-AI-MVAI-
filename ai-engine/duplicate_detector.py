"""Duplicate image detection over three independent signals.

The three signals mirror ``Duplicate``/``DuplicateMethod``:

``sha256``           byte-identical file - certain
``perceptual_hash``  visually identical, e.g. a re-encoded or resized copy
``source_url``       the same asset URL was crawled twice

When several signals fire at once, the recorded method is the strongest one,
in the order the ``Duplicate`` docstring lists them: exact content hash, then
perceptual hash, then repeated source URL.  A match is reported rather than
silently swallowed, so the caller decides whether to persist the relationship
and discard the copy - this module only ever says *what* is a duplicate of
*what*.

Detection is index-based: :meth:`DuplicateDetector.scan` keeps the first
occurrence of an image as the canonical copy and reports every later
occurrence as its duplicate, which is exactly the "which material already owns
this image?" question the image cache needs answered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable
from urllib.parse import urlsplit, urlunsplit

from app.models.enums import DuplicateMethod
from app.utils.hashing import hamming_distance, hamming_similarity
from app.utils.urls import normalise_url

#: Fallback Hamming distance for perceptual matches; matches the settings
#: default ``perceptual_duplicate_distance``.
DEFAULT_MAX_DISTANCE: Final[int] = 6

#: Detail strings are persisted in a ``String(500)`` column.
MAX_DETAIL_LENGTH: Final[int] = 500


def _truncate(detail: str) -> str:
    return detail[:MAX_DETAIL_LENGTH]


def _url_key(url: object) -> str:
    """Canonical form of a source URL, so trivial variants still collide.

    :func:`app.utils.urls.normalise_url` already strips fragments and default
    ports; this adds the host-side conventions that make two crawl results
    compare equal - lower-casing and dropping a leading ``www.``.  Anything it
    rejects (a relative path, plain garbage) falls back to a case-insensitive
    literal rather than being ignored, so a bad URL can still collide.
    """
    raw = str(url).strip() if url else ""
    normalised = normalise_url(raw or None)
    if not normalised:
        return raw.lower()
    parts = urlsplit(normalised)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return urlunsplit((parts.scheme.lower(), host, parts.path, parts.query, ""))


@dataclass(frozen=True, slots=True)
class ImageFingerprint:
    """Everything this module knows about one image.

    Args:
        key: opaque caller identifier (image id, cache file name, ...).
        sha256: hex digest of the exact bytes, when already computed.
        perceptual_hash: binary string from ``app.utils.hashing.perceptual_hash``.
        source_url: where the image was crawled from.
    """

    key: str
    sha256: str = ""
    perceptual_hash: str = ""
    source_url: str = ""

    @property
    def has_signal(self) -> bool:
        """``True`` when at least one of the three signals is populated."""
        return bool(
            self.sha256.strip()
            or self.perceptual_hash.strip()
            or _url_key(self.source_url)
        )


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    """``key`` duplicates ``canonical_key`` under ``method``."""

    key: str
    canonical_key: str
    method: DuplicateMethod
    similarity: float
    detail: str


class DuplicateDetector:
    """Indexes fingerprints and reports which of them describe the same image.

    Args:
        max_distance: Hamming distance at or below which two perceptual hashes
            count as the same picture.  Defaults to the settings default (6).
    """

    def __init__(self, *, max_distance: int = DEFAULT_MAX_DISTANCE) -> None:
        if max_distance < 0:
            raise ValueError("max_distance must not be negative")
        self.max_distance = max_distance
        self._by_sha: dict[str, str] = {}
        self._by_url: dict[str, str] = {}
        self._perceptual: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def registered_count(self) -> int:
        """How many distinct keys are held in the index."""
        keys = {*self._by_sha.values(), *self._by_url.values(), *self._perceptual.values()}
        return len(keys)

    def clear(self) -> None:
        """Empty the index - used between batches and between tests."""
        self._by_sha.clear()
        self._by_url.clear()
        self._perceptual.clear()

    def __len__(self) -> int:
        return self.registered_count

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------
    def register(self, item: ImageFingerprint) -> None:
        """Add ``item`` to the index as a canonical (retained) image.

        Re-registering the same key is a no-op, so a retried batch cannot
        shadow its own earlier result.
        """
        if not item.has_signal:
            return
        digest = item.sha256.strip().lower()
        if digest:
            self._by_sha.setdefault(digest, item.key)
        url = _url_key(item.source_url)
        if url:
            self._by_url.setdefault(url, item.key)
        phash = item.perceptual_hash.strip()
        if phash:
            self._perceptual.setdefault(phash, item.key)

    def check(self, item: ImageFingerprint) -> DuplicateMatch | None:
        """Return how ``item`` duplicates something already indexed, if at all.

        Signals are tried strongest-first, so the recorded method is the best
        evidence available rather than whichever lookup ran first.
        """
        if not item.has_signal:
            return None

        digest = item.sha256.strip().lower()
        canonical = self._by_sha.get(digest) if digest else None
        if canonical is not None and canonical != item.key:
            return DuplicateMatch(
                key=item.key,
                canonical_key=canonical,
                method=DuplicateMethod.SHA256,
                similarity=1.0,
                detail=_truncate(f"sha256 {digest}"),
            )

        phash_match = self._perceptual_match(item)
        if phash_match is not None:
            return phash_match

        url = _url_key(item.source_url)
        canonical = self._by_url.get(url) if url else None
        if canonical is not None and canonical != item.key:
            return DuplicateMatch(
                key=item.key,
                canonical_key=canonical,
                method=DuplicateMethod.SOURCE_URL,
                similarity=1.0,
                detail=_truncate(f"source url {url}"),
            )
        return None

    def add(self, item: ImageFingerprint) -> DuplicateMatch | None:
        """Check then register: the one call a streaming pipeline needs."""
        match = self.check(item)
        if match is None:
            self.register(item)
        return match

    def scan(self, items: Iterable[ImageFingerprint]) -> list[DuplicateMatch]:
        """Classify a batch, keeping the first occurrence of each image.

        Every item that is *not* a duplicate of an earlier one becomes
        canonical, so a later item may legitimately match it.
        """
        return [match for item in items if (match := self.add(item)) is not None]

    # ------------------------------------------------------------------
    # Perceptual signal
    # ------------------------------------------------------------------
    def _perceptual_match(self, item: ImageFingerprint) -> DuplicateMatch | None:
        phash = item.perceptual_hash.strip()
        if not phash:
            return None
        for other_hash, canonical in self._perceptual.items():
            if canonical == item.key:
                continue
            distance = hamming_distance(phash, other_hash)
            # -1 means "not comparable" (different lengths, empty), never a hit.
            if 0 <= distance <= self.max_distance:
                return DuplicateMatch(
                    key=item.key,
                    canonical_key=canonical,
                    method=DuplicateMethod.PERCEPTUAL_HASH,
                    similarity=round(hamming_similarity(distance, len(phash)), 6),
                    detail=_truncate(
                        f"hamming distance {distance} of {len(phash)} bits"
                    ),
                )
        return None


# ---------------------------------------------------------------------------
# Module-level shortcuts
# ---------------------------------------------------------------------------


def duplicate_detector() -> DuplicateDetector:
    """A detector with default settings."""
    return DuplicateDetector()


def find_duplicates(items: Iterable[ImageFingerprint]) -> list[DuplicateMatch]:
    """One-shot duplicate detection over a batch."""
    return DuplicateDetector().scan(items)


__all__ = [
    "DEFAULT_MAX_DISTANCE",
    "DuplicateDetector",
    "DuplicateMatch",
    "ImageFingerprint",
    "duplicate_detector",
    "find_duplicates",
]
