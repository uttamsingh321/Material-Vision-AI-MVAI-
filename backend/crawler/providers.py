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
    SearchQuery, ProviderHit
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


class DigikeyProvider(BaseSearchProvider):
    id = "digikey"
    kind = "distributor"
    display_name = "DigiKey"
    enabled = False

    def __init__(self):
        super().__init__()
        import os
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        self.client_id = os.getenv("DIGIKEY_CLIENT_ID")
        self.client_secret = os.getenv("DIGIKEY_CLIENT_SECRET")
        # The registry is the single source of truth for runtime enablement.
        # Planned providers ship disabled until the operator explicitly opts in.
        self.enabled = False
        self._token = None

    async def _get_token(self) -> str:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.digikey.com/v1/oauth2/token",
                data={"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "client_credentials"}
            )
            resp.raise_for_status()
            self._token = resp.json()["access_token"]
        return self._token

    async def _search(self, query: SearchQuery) -> ProviderResponse:
        if not self.enabled:
            return ProviderResponse(provider=self.id, query=query, hits=())
        if not self._token:
            await self._get_token()
        import httpx
        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-DIGIKEY-Client-Id": self.client_id,
            "Content-Type": "application/json",
            "X-DIGIKEY-Locale-Site": "US",
            "X-DIGIKEY-Locale-Language": "en",
            "X-DIGIKEY-Locale-Currency": "USD",
        }
        hits = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.digikey.com/products/v4/search/keyword",
                headers=headers,
                json={"keywords": query.text, "limit": 1}
            )
            if resp.status_code == 401:
                # Token expired - refresh once and retry
                await self._get_token()
                headers["Authorization"] = f"Bearer {self._token}"
                resp = await client.post(
                    "https://api.digikey.com/products/v4/search/keyword",
                    headers=headers,
                    json={"keywords": query.text, "limit": 1}
                )
            if resp.status_code == 200:
                products = resp.json().get("Products", [])
                if products:
                    photo_url = products[0].get("PhotoUrl")
                    if photo_url:
                        hits.append(ProviderHit(image_url=photo_url, position=0, source_domain="digikey.com"))
        return ProviderResponse(provider=self.id, query=query, hits=tuple(hits))

    async def _fetch(self, image_url: str) -> bytes:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(image_url, follow_redirects=True)
            resp.raise_for_status()
            return resp.content


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


class PlaywrightBingImagesProvider(BaseSearchProvider):
    id = "bing_stealth"
    kind = "image_search"
    display_name = "Bing Stealth Images"
    enabled = False

    async def _fetch(self, image_url: str) -> bytes:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(image_url, follow_redirects=True)
            resp.raise_for_status()
            return resp.content

    async def _search(self, query: SearchQuery) -> ProviderResponse:
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
        import urllib.parse
        import json
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await Stealth().apply_stealth_async(page)
            
            # Using exact original query format + strict negative keywords for manufacturing rule
            negative_keywords = "-person -people -human -worker -man -woman -face -stock"
            search_query = urllib.parse.quote_plus(f"{query.text} industrial component {negative_keywords}")
            await page.goto(f"https://www.bing.com/images/search?q={search_query}")
            await page.wait_for_timeout(2000)
            
            hits = []
            murls = await page.evaluate("() => Array.from(document.querySelectorAll('a.iusc')).map(a => {try {return JSON.parse(a.getAttribute('m')).murl} catch(e) {return null}}).filter(Boolean)")
            
            for idx, murl in enumerate(murls):
                if murl and murl.startswith("http"):
                    hits.append(ProviderHit(image_url=murl, position=idx, source_domain="bing.com"))
            
            await browser.close()
            
        return ProviderResponse(provider=self.id, query=query, hits=tuple(hits))
