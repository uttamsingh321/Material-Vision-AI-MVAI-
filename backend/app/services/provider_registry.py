"""Provider registry: the single place provider identities are resolved.

Business logic never instantiates a provider class directly - it asks the
registry for an id.  The registry owns:

* **registration** of every known source (the nine planned providers plus the
  local mock), so discovery and status endpoints have a canonical list;
* **enablement**, driven by ``Settings.enabled_providers``: a registered
  provider whose id is not enabled is reported as disabled and refuses calls
  through its own ``enabled`` flag - one source of truth, no hidden bypass;
* **kind mapping** from the crawler's plain strings to
  :class:`app.models.enums.ProviderKind`, keeping the crawler package free of
  application imports (ADR-008).

The registry is a process-wide singleton built lazily, mirroring
``get_settings``.  Tests reset it with :func:`reset_provider_registry`.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.ai_engine import crawler
from app.config import get_settings
from app.config.logging import get_logger
from app.models.enums import ProviderKind

logger = get_logger(__name__)

#: Fallback when a provider declares a kind string the enum does not know.
_DEFAULT_KIND = ProviderKind.WEB_SEARCH


class UnknownProviderError(KeyError):
    """The requested provider id was never registered."""


def _coerce_kind(raw: str) -> ProviderKind:
    """Map a crawler kind string onto the persisted enum, safely."""
    try:
        return ProviderKind(raw)
    except ValueError:
        logger.warning("provider.unknown_kind", raw=raw)
        return _DEFAULT_KIND


class ProviderRegistry:
    """Holds every known provider and decides which ones may run."""

    def __init__(self, providers: Iterable[Any] = ()) -> None:
        self._providers: dict[str, Any] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: Any) -> None:
        """Add (or replace) a provider keyed by its ``id``."""
        if not getattr(provider, "id", ""):
            raise ValueError("provider must expose a non-empty 'id'")
        self._providers[provider.id] = provider

    def get(self, provider_id: str) -> Any:
        """Return the provider registered under ``provider_id``.

        Raises:
            UnknownProviderError: when no provider carries that id.
        """
        try:
            return self._providers[provider_id]
        except KeyError:
            raise UnknownProviderError(
                f"unknown provider {provider_id!r}; known: {sorted(self._providers)}"
            ) from None

    def ids(self) -> tuple[str, ...]:
        """Every registered id, in registration order."""
        return tuple(self._providers)

    def describe_all(self) -> list[dict[str, Any]]:
        """Serialisable snapshot for the providers API endpoint."""
        return [provider.describe() for provider in self._providers.values()]

    def enabled(self) -> tuple[Any, ...]:
        """Providers that are both registered *and* configuration-enabled."""
        allowed = set(get_settings().enabled_provider_list)
        return tuple(
            provider
            for pid, provider in self._providers.items()
            if pid in allowed and provider.enabled
        )

    def kind_of(self, provider_id: str) -> ProviderKind:
        """Persisted :class:`ProviderKind` for a registered provider."""
        return _coerce_kind(self.get(provider_id).kind)

    def sync_enabled_flags(self) -> None:
        """Re-apply ``Settings.enabled_providers`` onto every registered id.

        Called at start-up and whenever settings change, so the flag on the
        provider object (what the contract exposes) and the CSV in settings
        (what the operator edits) can never disagree.
        """
        allowed = set(get_settings().enabled_provider_list)
        for pid, provider in self._providers.items():
            # The mock provider is the Phase-1 workhorse: it stays governed by
            # the same list as everyone else - no special case.
            provider.enabled = pid in allowed


def build_default_registry() -> ProviderRegistry:
    """A registry containing the mock and all nine planned providers."""
    registry = ProviderRegistry()
    mock_module = crawler("mock_provider")
    registry.register(mock_module.MockSearchProvider())
    providers_module = crawler("providers")
    for provider in providers_module.planned_provider_instances():
        registry.register(provider)
    registry.sync_enabled_flags()
    logger.debug("provider.registry_built", providers=registry.ids())
    return registry


_registry: ProviderRegistry | None = None


def get_provider_registry() -> ProviderRegistry:
    """Process-wide registry singleton."""
    global _registry
    if _registry is None:
        _registry = build_default_registry()
    return _registry


def reset_provider_registry() -> None:
    """Drop the singleton so the next access rebuilds it (used by tests)."""
    global _registry
    _registry = None


__all__ = [
    "ProviderRegistry",
    "UnknownProviderError",
    "build_default_registry",
    "get_provider_registry",
    "reset_provider_registry",
]
