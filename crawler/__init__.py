"""Crawler package: provider adapters that locate candidate product images.

Every adapter returns the same :class:`ProviderResult` shape so the pipeline can
treat DigiKey, Mouser, a manufacturer site and a general image search
interchangeably.  Adding a source means adding one module and one registry
entry - no pipeline change.

Import through ``backend.app.ai_engine.crawler("google_search")``; the directory
is hyphen-free but intentionally kept out of the importable tree so providers
stay separable from the application.  See ADR-008.
"""

from __future__ import annotations

__all__ = ["base"]
