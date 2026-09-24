"""Crawler package: provider adapters that locate candidate product images.

Every adapter returns the same :class:`~crawler.base.ProviderResponse` shape
so the pipeline can treat DigiKey, Mouser, a manufacturer site and a general
image search interchangeably.  Adding a source means adding one class and one
registry entry - no pipeline change.

Modules
-------
``base``
    The provider contract (:class:`SearchQuery`, :class:`ProviderHit`,
    :class:`ProviderResponse`, :class:`SearchProvider`).
``providers``
    The nine catalogue/search providers, all shipped **disabled**.
``mock_provider``
    The deterministic local provider that powers Phase 1 runs.

Import through ``backend.app.ai_engine.crawler("providers")``; the directory
is hyphen-free but intentionally kept out of the importable tree so providers
stay separable from the application.  See ADR-008.
"""

from __future__ import annotations

__all__ = ["base", "mock_provider", "providers"]

