"""URL inspection helpers used by the candidate filter and the downloader.

Everything here operates on *untrusted* strings coming from search providers,
so the functions are total - they return a sensible value for garbage input
rather than raising.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse, urlunparse

from app.config.constants import THUMBNAIL_URL_MARKERS
from app.utils.files import safe_filename

#: Query parameters that carry a real image behind a resizing/CDN wrapper.  When
#: one is present it is preserved - dropping it silently downgrades quality.
_IMAGE_HINTS = ("image", "img", "photo", "picture", "media", "product")


def normalise_url(url: str | None) -> str | None:
    """Strip fragments and default ports so equal URLs compare equal.

    Tracking parameters are *not* removed: some CDNs encode the real image in
    them, and a false negative here costs a needless download.
    """
    if not url or not isinstance(url, str):
        return None
    candidate = url.strip()
    if not candidate:
        return None
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"

    parsed = urlparse(candidate)
    if not parsed.scheme or not parsed.netloc:
        return None

    netloc = parsed.netloc.lower()
    if (parsed.scheme == "http" and netloc.endswith(":80")) or (
        parsed.scheme == "https" and netloc.endswith(":443")
    ):
        netloc = netloc.rsplit(":", 1)[0]

    return urlunparse(
        (parsed.scheme.lower(), netloc, parsed.path, parsed.params, parsed.query, "")
    )


def domain_of(url: str | None) -> str | None:
    """Registrable-ish host for display and grouping: ``www.se.com`` -> ``se.com``."""
    normalised = normalise_url(url)
    if normalised is None:
        return None
    host = urlparse(normalised).netloc
    # Strip an explicit port and the cosmetic ``www.`` prefix.
    host = host.rsplit(":", 1)[0] if ":" in host else host
    return host[4:] if host.startswith("www.") else host


def resolve_url(base: str | None, href: str | None) -> str | None:
    """Absolute URL for ``href``, resolving relative references against ``base``."""
    if not href:
        return None
    if base:
        return normalise_url(urljoin(base, href))
    return normalise_url(href)


def is_probable_image_url(
    url: str | None, *, allowed_suffixes: tuple[str, ...] | None = None
) -> bool:
    """Heuristic check that a URL points at an image file.

    When ``allowed_suffixes`` is given, a matching extension is required.  When
    it is ``None`` the URL is accepted if it either ends in a known image
    extension or contains an image-ish path segment (many APIs return
    extension-less CDN URLs).
    """
    if not url:
        return False
    path = unquote(urlparse(url).path).lower()
    suffix = Path(path).suffix

    if allowed_suffixes is not None:
        return suffix in {item.lower() for item in allowed_suffixes}

    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".tif", ".tiff"}:
        return True
    return any(hint in path for hint in _IMAGE_HINTS)


def is_thumbnail_url(url: str | None, *, markers: tuple[str, ...] = THUMBNAIL_URL_MARKERS) -> bool:
    """``True`` when the URL betrays a thumbnail, icon or placeholder asset."""
    if not url:
        return False
    haystack = unquote(url).lower()
    return any(marker in haystack for marker in markers)


def filename_from_url(url: str | None, *, fallback: str = "image") -> str:
    """Derive a safe file name from a URL path, ignoring query strings."""
    if not url:
        return fallback
    path = unquote(urlparse(url).path)
    name = Path(path).name
    return safe_filename(name, fallback=fallback) if name else fallback


def suffix_from_url(url: str | None, *, default: str = "") -> str:
    """Lower-case extension of a URL path, including the dot; ``""`` if absent."""
    if not url:
        return default
    return Path(unquote(urlparse(url).path)).suffix.lower() or default


def is_same_domain(left: str | None, right: str | None) -> bool:
    """Compare hosts, tolerating a ``www.`` prefix on either side."""
    left_domain, right_domain = domain_of(left), domain_of(right)
    return bool(left_domain) and left_domain == right_domain


def build_search_url(base: str, **params: str | int | None) -> str:
    """Attach non-empty query parameters to ``base``."""
    from urllib.parse import urlencode

    query = {key: value for key, value in params.items() if value not in (None, "")}
    return f"{base}?{urlencode(query)}" if query else base
