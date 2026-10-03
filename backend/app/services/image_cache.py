"""Local, content-addressed image cache with SHA-256 duplicate prevention.

Layout under ``image-cache/``::

    image-cache/<ab>/<sha256><ext>

The first two hex characters shard the directory so a six-figure library does
not become one flat folder.  Because the file name *is* the content hash:

* storing the same bytes twice reuses the first file (``reused=True``) - no
  duplicate I/O, no duplicate disk;
* looking up an image is a pure path computation - no index needed;
* a corrupt/truncated file cannot silently replace a good one, because writes
  go through :func:`app.utils.files.atomic_write_bytes`.

The cache stores bytes only.  Everything else about an image - which material
it belongs to, its source URL, its verdict - lives in the ``images`` table.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.config.logging import get_logger
from app.utils.files import atomic_write_bytes, ensure_within, relative_posix
from app.utils.hashing import sha256_bytes

logger = get_logger(__name__)

#: Extension-less URL / unknown type still needs a suffix on disk.
DEFAULT_EXTENSION = ".bin"

#: Minimal MIME map - only what the Phase-1 pipeline can produce or accept.
MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bin": "application/octet-stream",
}


@dataclass(frozen=True, slots=True)
class CachedImage:
    """Where a byte string landed in the cache."""

    sha256: str
    #: Absolute path on this host (server-side only).
    path: Path
    #: POSIX path relative to ``image-cache/`` - safe to store/serialise.
    relative_path: str
    byte_size: int
    extension: str
    mime_type: str
    #: ``True`` when identical bytes were already present.
    reused: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "relative_path": self.relative_path,
            "byte_size": self.byte_size,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "reused": self.reused,
        }


def guess_mime(extension: str) -> str:
    """MIME type for a lower-cased extension (with dot), else octet-stream."""
    return MIME_TYPES.get(extension.lower(), "application/octet-stream")


class ImageCache:
    """Content-addressed local storage for candidate images."""

    def __init__(self, root: str | Path | None = None) -> None:
        settings = get_settings()
        self.root = Path(root) if root is not None else settings.image_cache_dir
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------
    def path_for_sha(self, sha256: str, extension: str = DEFAULT_EXTENSION) -> Path:
        """Canonical on-disk path for a digest (no I/O)."""
        digest = sha256.lower()
        return self.root / digest[:2] / f"{digest}{extension}"

    def lookup(self, sha256: str, extensions: tuple[str, ...] | None = None) -> Path | None:
        """Existing file for ``sha256``, or ``None``.

        By default the sharded directory is scanned for any extension, because
        the digest covers the bytes only - the suffix is cosmetic.
        """
        directory = self.root / sha256.lower()[:2]
        if not directory.is_dir():
            return None
        if extensions is None:
            matches = list(directory.glob(f"{sha256.lower()}.*"))
        else:
            matches = [
                directory / f"{sha256.lower()}{ext}" for ext in extensions
            ]
            matches = [path for path in matches if path.is_file()]
        return matches[0] if matches else None

    # ------------------------------------------------------------------
    # Store / read
    # ------------------------------------------------------------------
    def store(self, payload: bytes, *, extension: str = DEFAULT_EXTENSION) -> CachedImage:
        """Persist ``payload``; reuses the existing file when bytes match."""
        if not payload:
            raise ValueError("cannot cache an empty image payload")
        digest = sha256_bytes(payload)
        suffix = extension if extension.startswith(".") else f".{extension}"
        target = self.path_for_sha(digest, suffix)
        reused = target.exists()
        if not reused:
            atomic_write_bytes(target, payload)
            logger.debug("image_cache.stored", sha256=digest, bytes=len(payload))
        return CachedImage(
            sha256=digest,
            path=target,
            relative_path=relative_posix(target, self.root),
            byte_size=len(payload),
            extension=suffix,
            mime_type=guess_mime(suffix),
            reused=reused,
        )

    def read(self, relative_path: str) -> bytes:
        """Read a cached file back, guarding against path traversal."""
        return self.resolve(relative_path).read_bytes()

    def resolve(self, relative_path: str) -> Path:
        """Absolute path for a stored ``relative_path``, inside the root."""
        return ensure_within(self.root, relative_path)

    def exists(self, relative_path: str) -> bool:
        try:
            return self.resolve(relative_path).is_file()
        except ValueError:
            return False


def image_cache() -> ImageCache:
    """The process-wide cache root from settings."""
    return ImageCache()


__all__ = ["CachedImage", "ImageCache", "guess_mime", "image_cache"]
