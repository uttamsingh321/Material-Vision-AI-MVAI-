"""Hashing helpers used for caching, deduplication and file naming.

Three distinct hashes are used across the platform and confusing them is easy,
so they get dedicated names:

* :func:`sha256_text` - cache keys and query fingerprints.
* :func:`sha256_bytes` / :func:`sha256_file` - exact image identity.
* :func:`perceptual_hash` - near-duplicate detection (needs Pillow, hence the
  guarded import so the core stack keeps working without imaging extras).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

#: Chunk size for streaming file hashing - large enough to be fast, small
#: enough to keep memory flat on multi-megabyte product photos.
HASH_CHUNK_SIZE = 1024 * 256


def sha256_text(value: str) -> str:
    """Hex SHA-256 of a UTF-8 string."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    """Hex SHA-256 of a byte string."""
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Hex SHA-256 of a file, read in streaming chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def build_cache_key(*parts: object, namespace: str = "mvai") -> str:
    """Stable, collision-resistant cache key from arbitrary parts.

    ``None`` and empty parts are dropped so ``key("a", None, "b")`` and
    ``key("a", "b")`` agree - important because the same logical request can
    arrive with optional fields either absent or empty.
    """
    material = "|".join(str(part) for part in parts if part not in (None, ""))
    return f"{namespace}:{sha256_text(material)}"


def hamming_distance(left: str, right: str) -> int:
    """Bit distance between two same-length binary strings.

    Returns ``-1`` when the strings are not comparable, which callers treat as
    "not a duplicate" rather than raising mid-pipeline.
    """
    if not left or not right or len(left) != len(right):
        return -1
    return sum(1 for a, b in zip(left, right, strict=True) if a != b)


def perceptual_hash(image_path: str | Path, *, hash_size: int = 8) -> str | None:
    """Average-hash (aHash) fingerprint of an image, as a binary string.

    Implemented with Pillow's built-in image ops rather than ``imagehash`` so
    no extra native dependency is required.  Returns ``None`` when Pillow is
    unavailable or the file cannot be decoded - the caller then falls back to
    SHA-256-only deduplication.
    """
    try:  # pragma: no cover - exercised only when Pillow is installed
        from PIL import Image
    except ImportError:  # pragma: no cover
        return None

    try:  # pragma: no cover - decoding depends on the file
        with Image.open(image_path) as image:
            # ``Image.Resampling`` exists from Pillow 9.1; ``LANCZOS`` is the
            # legacy alias kept for older releases.
            resampling = getattr(Image, "Resampling", Image)
            resample_filter = getattr(resampling, "LANCZOS", 1)
            grey = image.convert("L").resize(
                (hash_size, hash_size), resample_filter
            )
            pixels = list(grey.getdata())
    except Exception:  # noqa: BLE001 - a corrupt candidate must not crash the job
        return None

    if not pixels:
        return None

    average = sum(pixels) / len(pixels)
    return "".join("1" if value > average else "0" for value in pixels)


def hamming_similarity(distance: int, hash_length: int) -> float:
    """Convert a Hamming distance into a ``[0, 1]`` similarity score."""
    if distance < 0 or hash_length <= 0:
        return 0.0
    return max(0.0, 1.0 - (distance / hash_length))


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    """De-duplicate strings without losing their original ordering."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
