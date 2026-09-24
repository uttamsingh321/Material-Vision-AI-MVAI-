"""The nine catalogue/search providers, defined but disabled.

Each class is a complete registered adapter implementing the
:class:`crawler.base.SearchProvider` contract; all of them ship with
``enabled = False`` and ``_search``/``_fetch`` raising
:class:`crawler.base.ProviderDisabledError` until a real implementation lands
in Phase 2.  Enabling a source is therefore *config + one class body*, never a
pipeline change - the contract is the only thing the business logic sees.

Keeping every provider in one module keeps the family resemblance obvious: the
identity fields differ, the behaviour contract never does.
"""

from __future__ import annotations

from .base import (
    BaseSearchProvider,
    ProviderDisabledError,
    ProviderResponse,
    SearchQuery,
)


class _PlannedProvider(BaseSearchProvider):
    """Common behaviour for providers whose HTTP implementation is Phase 2.

    The overrides exist so a disabled provider fails *loudly with a typed
    error* rather than silently returning an empty result set - an empty set
    would be indistinguishable from "searched and found nothing", which would
    poison provider-health reporting.
    """

    async def _search(self, query: SearchQuery) -> ProviderResponse:  # noqa: ARG002
        raise ProviderDisabledError(
            f"provider {self.id!r} has no live implementation yet", provider=self.id
        )

    async def _fetch(self, image_url: str) -> bytes:  # noqa: ARG002
        raise ProviderDisabledError(
            f"provider {self.id!r} has no live implementation yet", provider=self.id
        )


class GoogleImagesProvider(_PlannedProvider):
    id = "google_images"
    kind = "image_search"
    display_name = "Google Images"
    enabled = False


class BingImagesProvider(_PlannedProvider):
    id = "bing_images"
    kind = "image_search"
    display_name = "Bing Images"
    enabled = False


class ManufacturerSearchProvider(_PlannedProvider):
    id = "manufacturer_search"
    kind = "manufacturer"
    display_name = "Manufacturer Search"
    enabled = False


class DigikeyProvider(_PlannedProvider):
    id = "digikey"
    kind = "distributor"
    display_name = "DigiKey"
    enabled = False


class MouserProvider(_PlannedProvider):
    id = "mouser"
    kind = "distributor"
    display_name = "Mouser"
    enabled = False


class RsComponentsProvider(_PlannedProvider):
    id = "rs_components"
    kind = "distributor"
    display_name = "RS Components"
    enabled = False


class GraingerProvider(_PlannedProvider):
    id = "grainger"
    kind = "distributor"
    display_name = "Grainger"
    enabled = False


class MisumiProvider(_PlannedProvider):
    id = "misumi"
    kind = "distributor"
    display_name = "MISUMI"
    enabled = False


class AmazonBusinessProvider(_PlannedProvider):
    id = "amazon_business"
    kind = "marketplace"
    display_name = "Amazon Business"
    enabled = False


#: Canonical registration order - general engines first, then manufacturer,
#: then distributors by catalogue coverage, marketplace last.
PLANNED_PROVIDERS: tuple[type[BaseSearchProvider], ...] = (
    GoogleImagesProvider,
    BingImagesProvider,
    ManufacturerSearchProvider,
    DigikeyProvider,
    MouserProvider,
    RsComponentsProvider,
    GraingerProvider,
    MisumiProvider,
    AmazonBusinessProvider,
)


def planned_provider_instances() -> tuple[BaseSearchProvider, ...]:
    """One instance of every planned provider, in registration order."""
    return tuple(provider() for provider in PLANNED_PROVIDERS)


__all__ = [
    "PLANNED_PROVIDERS",
    "AmazonBusinessProvider",
    "BingImagesProvider",
    "DigikeyProvider",
    "GoogleImagesProvider",
    "GraingerProvider",
    "ManufacturerSearchProvider",
    "MisumiProvider",
    "MouserProvider",
    "RsComponentsProvider",
    "planned_provider_instances",
]
