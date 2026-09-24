"""Provider contract shared by every search source.

One shape in, one shape out: a :class:`SearchQuery` goes to
:meth:`SearchProvider.search` and a :class:`ProviderResponse` full of
:class:`ProviderHit` records comes back, whether the source is a general image
engine, a distributor catalogue or the local mock.  The pipeline therefore
never branches on *which* provider answered - only the adapter knows its own
wire format.

This package is deliberately free of ``app.*`` imports (see ADR-008): the same
contract must be usable from a batch script that has never heard of FastAPI.
Type-agnostic enums are expressed as plain strings whose values match
``app.models.enums.ProviderKind`` exactly; the registry performs the mapping.

Fetching bytes is part of the contract too (:meth:`SearchProvider.fetch`).
Search and fetch are separate calls so the pipeline can rank and filter hits
*before* spending bandwidth, and so a provider may serve image bytes from a
different endpoint (CDN) than the one that returned the search results.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """A fully normalised query ready to hand to a provider."""

    #: Free text actually sent to the source (already cleaned by the caller).
    text: str
    brand: str | None = None
    model: str | None = None
    material_code: str | None = None
    category: str | None = None
    #: Upper bound the caller wants honoured; providers may return fewer.
    max_results: int = 15

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("SearchQuery.text must not be empty")
        if self.max_results < 1:
            raise ValueError("SearchQuery.max_results must be >= 1")


@dataclass(frozen=True, slots=True)
class ProviderHit:
    """One candidate image location returned by a provider."""

    #: Direct image URL.  ``mock://`` URLs are served by the mock provider's
    #: own ``fetch``; everything else is fetched over HTTP in Phase 2.
    image_url: str
    position: int
    title: str | None = None
    #: Landing page the image was found on.
    page_url: str | None = None
    thumbnail_url: str | None = None
    source_domain: str | None = None
    snippet: str | None = None
    #: Provider's own relevance score, when it exposes one (0-1 otherwise).
    score: float | None = None
    #: Unmodified provider payload, retained for replay and debugging.
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """Everything one ``search`` call produced, plus its provenance."""

    provider: str
    query: SearchQuery
    hits: tuple[ProviderHit, ...]
    latency_ms: int = 0
    #: Populated when the call itself failed but the pipeline should continue.
    error: str | None = None

    @property
    def ok(self) -> bool:
        """``True`` when the call completed (even if it found nothing)."""
        return self.error is None


class ProviderError(Exception):
    """Base class for provider failures; ``provider`` names the culprit."""

    def __init__(self, message: str, *, provider: str = "") -> None:
        super().__init__(message)
        self.provider = provider


class ProviderDisabledError(ProviderError):
    """The provider exists but is switched off in configuration."""


class ProviderTimeoutError(ProviderError):
    """The provider did not answer within its deadline."""


@runtime_checkable
class SearchProvider(Protocol):
    """Structural contract every provider satisfies."""

    #: Registry key, e.g. ``mock`` or ``digikey``.  Matches the value stored
    #: in ``search_results.provider``.
    id: str
    #: Value matching ``app.models.enums.ProviderKind`` (as a plain string).
    kind: str
    display_name: str
    enabled: bool

    async def search(self, query: SearchQuery) -> ProviderResponse: ...

    async def fetch(self, image_url: str) -> bytes: ...


class BaseSearchProvider(ABC):
    """Shared enable-check and error translation for concrete providers.

    Subclasses implement :meth:`_search` / :meth:`_fetch` and flip
    ``enabled`` when the operator turns them on.  While disabled every call
    fails with :class:`ProviderDisabledError` - the pipeline treats that as
    "this source did not participate", never as a job failure.
    """

    id: ClassVar[str] = ""
    kind: ClassVar[str] = "web_search"
    display_name: ClassVar[str] = ""
    enabled: ClassVar[bool] = False

    async def search(self, query: SearchQuery) -> ProviderResponse:
        self._require_enabled()
        try:
            return await self._search(query)
        except ProviderError:
            raise
        except TimeoutError as exc:
            raise ProviderTimeoutError(str(exc), provider=self.id) from exc

    async def fetch(self, image_url: str) -> bytes:
        self._require_enabled()
        if not image_url:
            raise ProviderError("image_url must not be empty", provider=self.id)
        return await self._fetch(image_url)

    def describe(self) -> dict[str, Any]:
        """Registry/serialiser view of this provider's identity and state."""
        return {
            "id": self.id,
            "kind": self.kind,
            "display_name": self.display_name,
            "enabled": self.enabled,
        }

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise ProviderDisabledError(
                f"provider {self.id!r} is disabled", provider=self.id
            )

    @abstractmethod
    async def _search(self, query: SearchQuery) -> ProviderResponse:
        """Perform the actual lookup.  Only called when enabled."""

    @abstractmethod
    async def _fetch(self, image_url: str) -> bytes:
        """Download image bytes.  Only called when enabled."""


__all__ = [
    "BaseSearchProvider",
    "ProviderDisabledError",
    "ProviderError",
    "ProviderHit",
    "ProviderRateLimitedError",
    "ProviderResponse",
    "ProviderTimeoutError",
    "SearchProvider",
    "SearchQuery",
]
