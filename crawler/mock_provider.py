"""Deterministic local provider that powers Phase 1 end-to-end runs.

``MockSearchProvider`` is a *real* implementation of the provider contract:
it answers :meth:`search` with a stable, query-derived set of hits and serves
image bytes from :meth:`fetch`, so the entire pipeline - ranking, filtering,
download, hashing, de-duplication, confidence scoring, review-queue routing,
export - executes its production code path with no network access and no
external API.

Determinism matters: the same query always yields the same hits (URLs, titles,
scores), which makes pipeline behaviour reproducible in tests and demos alike.

The image URL scheme is ``mock://<domain>/<slug>-<n>.png``.  ``fetch``
recognises the scheme and returns real PNG bytes (a valid 1x1 image), so
downstream code that inspects magic numbers still sees a genuine PNG.  The
returned bytes vary with the URL, so per-hit SHA-256 de-duplication exercises
its "different content" branch rather than collapsing every hit.

A fraction of hits are deliberately *bad* - thumbnail-marked URLs and
non-image extensions - so the candidate filter has something to reject and the
review/provenance trail can show rejections happening for the right reasons.
"""

from __future__ import annotations

import hashlib
from typing import ClassVar

from .base import (
    BaseSearchProvider,
    ProviderError,
    ProviderHit,
    ProviderResponse,
    SearchQuery,
)

#: Marker scheme served exclusively by this provider's ``fetch``.
MOCK_SCHEME = "mock://"

#: Fixed domain used in mock URLs; also the ``source_domain`` of every hit.
MOCK_DOMAIN = "mock.local"

#: Suffixes the mock mixes in to exercise the candidate filter.
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

#: 1x1 transparent PNG (67 bytes) - a complete, spec-valid image file.
_PNG_HEADER = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _digest(*parts: str) -> str:
    """Stable hex digest of the joined parts (SHA-256)."""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


class MockSearchProvider(BaseSearchProvider):
    """The only provider enabled out of the box."""

    id: ClassVar[str] = "mock"
    kind: ClassVar[str] = "image_search"
    display_name: ClassVar[str] = "Mock Image Search"
    enabled: ClassVar[bool] = True

    #: Hits produced per query unless ``max_results`` is smaller.
    DEFAULT_HITS: ClassVar[int] = 6

    async def _search(self, query: SearchQuery) -> ProviderResponse:
        wanted = min(query.max_results, self.DEFAULT_HITS)
        slug = _digest("slug", query.text)[:12]
        hits: list[ProviderHit] = []
        for position in range(wanted):
            token = _digest("hit", query.text, str(position))
            # Every 4th hit is deliberately unusable so the candidate filter
            # and the rejection trail are exercised on every run.
            if position % 4 == 3:
                image_url = f"{MOCK_SCHEME}{MOCK_DOMAIN}/thumb/{slug}-{position}.png"
            elif position % 4 == 2:
                image_url = f"{MOCK_SCHEME}{MOCK_DOMAIN}/{slug}-{position}.gif"
            else:
                suffix = _IMAGE_SUFFIXES[position % 2]
                image_url = f"{MOCK_SCHEME}{MOCK_DOMAIN}/{slug}-{position}{suffix}"
            hits.append(
                ProviderHit(
                    image_url=image_url,
                    position=position,
                    title=f"{query.text} product image {position + 1}",
                    page_url=f"https://{MOCK_DOMAIN}/products/{slug}?view={position}",
                    thumbnail_url=f"{MOCK_SCHEME}{MOCK_DOMAIN}/thumb/{slug}-{position}.png",
                    source_domain=MOCK_DOMAIN,
                    snippet=f"Mock catalogue result {position + 1} for {query.text!r}.",
                    score=round(1.0 - position * 0.1, 2),
                    raw={"token": token, "provider": self.id},
                )
            )
        return ProviderResponse(provider=self.id, query=query, hits=tuple(hits), latency_ms=0)

    async def _fetch(self, image_url: str) -> bytes:
        if not image_url.startswith(MOCK_SCHEME):
            raise ProviderError(
                f"mock provider cannot fetch non-mock URL {image_url!r}",
                provider=self.id,
            )
        # Vary the payload with the URL so SHA-256 de-duplication sees
        # distinct content per hit while every response stays a valid PNG.
        variation = _digest("payload", image_url)
        return _PNG_HEADER + bytes.fromhex(variation[:14])


__all__ = ["MOCK_DOMAIN", "MOCK_SCHEME", "MockSearchProvider"]
