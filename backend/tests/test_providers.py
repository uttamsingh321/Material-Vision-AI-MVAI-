"""Provider contract tests: crawler adapters, mock source, registry, AI interfaces."""

from __future__ import annotations

import pytest

from app.ai_engine import (
    background_remover,
    crawler,
    image_similarity,
    ocr_reader,
    vision_validator,
)
from app.models.enums import ProviderKind
from app.services.provider_registry import (
    ProviderRegistry,
    UnknownProviderError,
    build_default_registry,
    get_provider_registry,
    reset_provider_registry,
)

base = crawler("base")
providers = crawler("providers")
mock_provider = crawler("mock_provider")

SearchQuery = base.SearchQuery
ProviderDisabledError = base.ProviderDisabledError
ProviderError = base.ProviderError
MockSearchProvider = mock_provider.MockSearchProvider


# ---------------------------------------------------------------------------
# SearchQuery contract
# ---------------------------------------------------------------------------


def test_search_query_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        SearchQuery(text="   ")


def test_search_query_rejects_zero_max_results() -> None:
    with pytest.raises(ValueError, match="max_results"):
        SearchQuery(text="bearing", max_results=0)


def test_search_query_defaults_are_pipeline_friendly() -> None:
    query = SearchQuery(text="SKF 6205-2RS bearing")

    assert query.max_results == 15
    assert query.brand is None
    assert query.text == "SKF 6205-2RS bearing"


# ---------------------------------------------------------------------------
# The nine planned providers
# ---------------------------------------------------------------------------


def test_all_nine_planned_providers_exist() -> None:
    assert len(providers.PLANNED_PROVIDERS) == 9


def test_planned_providers_are_registered_but_disabled() -> None:
    for provider in providers.planned_provider_instances():
        assert provider.enabled is False, f"{provider.id} must ship disabled"
        assert provider.id, "every provider needs an id"
        assert provider.display_name


def test_planned_provider_ids_are_unique_and_stable() -> None:
    ids = [provider.id for provider in providers.planned_provider_instances()]

    assert len(ids) == len(set(ids))
    assert set(ids) == {
        "google_images",
        "bing_images",
        "manufacturer_search",
        "digikey",
        "mouser",
        "rs_components",
        "grainger",
        "misumi",
        "amazon_business",
    }


async def test_disabled_provider_raises_typed_error_on_search() -> None:
    provider = providers.DigikeyProvider()

    with pytest.raises(ProviderDisabledError, match="digikey"):
        await provider.search(SearchQuery(text="ATTEND connector"))


async def test_disabled_provider_raises_typed_error_on_fetch() -> None:
    provider = providers.MouserProvider()

    with pytest.raises(ProviderDisabledError, match="mouser"):
        await provider.fetch("https://example.test/a.png")


def test_planned_provider_describe_shape() -> None:
    described = providers.GraingerProvider().describe()

    assert described == {
        "id": "grainger",
        "kind": "distributor",
        "display_name": "Grainger",
        "enabled": False,
    }


def test_every_planned_kind_maps_to_persisted_enum() -> None:
    for provider in providers.planned_provider_instances():
        ProviderKind(provider.kind), f"unknown kind {provider.kind!r}"


# ---------------------------------------------------------------------------
# Mock provider - the Phase 1 workhorse
# ---------------------------------------------------------------------------


async def test_mock_provider_is_enabled_by_default() -> None:
    response = await MockSearchProvider().search(SearchQuery(text="contactor 18A"))

    assert response.ok
    assert response.provider == "mock"
    assert len(response.hits) == MockSearchProvider.DEFAULT_HITS


async def test_mock_search_is_deterministic() -> None:
    provider = MockSearchProvider()
    first = await provider.search(SearchQuery(text="SKF 6205 bearing"))
    second = await provider.search(SearchQuery(text="SKF 6205 bearing"))

    assert [hit.image_url for hit in first.hits] == [hit.image_url for hit in second.hits]
    assert [hit.score for hit in first.hits] == [hit.score for hit in second.hits]


async def test_mock_search_differs_per_query() -> None:
    provider = MockSearchProvider()
    left = await provider.search(SearchQuery(text="bearing 6205"))
    right = await provider.search(SearchQuery(text="hex bolt M8"))

    assert left.hits[0].image_url != right.hits[0].image_url


async def test_mock_hits_carry_full_provenance() -> None:
    response = await MockSearchProvider().search(SearchQuery(text="ESD wrist strap"))
    hit = response.hits[0]

    assert hit.image_url.startswith(mock_provider.MOCK_SCHEME)
    assert hit.source_domain == mock_provider.MOCK_DOMAIN
    assert hit.page_url and hit.page_url.startswith("https://")
    assert hit.title
    assert 0.0 <= (hit.score or 0) <= 1.0


async def test_mock_mixes_in_unusable_hits_for_the_filter() -> None:
    """Positions 2 and 3 of every response must be filter fodder."""
    response = await MockSearchProvider().search(SearchQuery(text="threadlocker"))

    assert response.hits[2].image_url.endswith(".gif"), "non-image suffix expected"
    assert "/thumb/" in response.hits[3].image_url, "thumbnail marker expected"


async def test_mock_fetch_returns_valid_png_bytes() -> None:
    provider = MockSearchProvider()
    response = await provider.search(SearchQuery(text="bearing"))
    payload = await provider.fetch(response.hits[0].image_url)

    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(payload) > 60


async def test_mock_fetch_bytes_differ_per_url() -> None:
    provider = MockSearchProvider()
    response = await provider.search(SearchQuery(text="bearing"))

    first = await provider.fetch(response.hits[0].image_url)
    second = await provider.fetch(response.hits[1].image_url)

    assert first != second, "distinct URLs must yield distinct bytes (dedup realism)"


async def test_mock_fetch_rejects_non_mock_urls() -> None:
    with pytest.raises(ProviderError, match="non-mock"):
        await MockSearchProvider().fetch("https://example.test/a.png")


async def test_mock_fetch_rejects_empty_url() -> None:
    with pytest.raises(ProviderError, match="must not be empty"):
        await MockSearchProvider().fetch("")


async def test_mock_respects_smaller_max_results() -> None:
    response = await MockSearchProvider().search(SearchQuery(text="bolt", max_results=2))

    assert len(response.hits) == 2



# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_default_registry_contains_mock_and_all_planned() -> None:
    registry = build_default_registry()

    assert set(registry.ids()) == {
        "mock",
        "google_images",
        "bing_images",
        "manufacturer_search",
        "digikey",
        "mouser",
        "rs_components",
        "grainger",
        "misumi",
        "amazon_business",
    }


def test_registry_enables_only_configured_providers() -> None:
    """conftest leaves ``enabled_providers`` at its Phase-1 default: mock."""
    registry = build_default_registry()

    enabled_ids = [provider.id for provider in registry.enabled()]
    assert enabled_ids == ["mock"]


def test_registry_get_unknown_provider_raises() -> None:
    registry = build_default_registry()

    with pytest.raises(UnknownProviderError, match="yahoo"):
        registry.get("yahoo")


def test_registry_register_requires_id() -> None:
    registry = ProviderRegistry()

    with pytest.raises(ValueError, match="non-empty 'id'"):
        registry.register(object())


def test_registry_kind_mapping_uses_enum() -> None:
    registry = build_default_registry()

    assert registry.kind_of("mock") is ProviderKind.IMAGE_SEARCH
    assert registry.kind_of("digikey") is ProviderKind.DISTRIBUTOR
    assert registry.kind_of("amazon_business") is ProviderKind.MARKETPLACE
    assert registry.kind_of("manufacturer_search") is ProviderKind.MANUFACTURER


def test_registry_sync_enabled_flags_applies_settings() -> None:
    registry = build_default_registry()
    registry.get("mock").enabled = False

    registry.sync_enabled_flags()

    assert registry.get("mock").enabled is True, "settings say mock is allowed"
    assert registry.get("digikey").enabled is False


def test_registry_describe_all_is_serialisable_snapshot() -> None:
    snapshot = build_default_registry().describe_all()

    assert len(snapshot) == 10
    assert all(set(entry) == {"id", "kind", "display_name", "enabled"} for entry in snapshot)


def test_get_provider_registry_is_a_singleton() -> None:
    reset_provider_registry()
    try:
        assert get_provider_registry() is get_provider_registry()
    finally:
        reset_provider_registry()


# ---------------------------------------------------------------------------
# AI interface-only modules
# ---------------------------------------------------------------------------


def test_ocr_reader_is_interface_only() -> None:
    module = ocr_reader()

    assert module.OcrReader.__abstractmethods__ == frozenset({"available", "read"})
    with pytest.raises(TypeError):
        module.OcrReader()  # type: ignore[abstract]


def test_ocr_result_tokens_are_lower_cased_words() -> None:
    module = ocr_reader()
    result = module.OcrResult(text="Schneider  LC1D18", engine="tesseract")

    assert result.tokens == ["schneider", "lc1d18"]
    assert result.is_empty is False
    assert module.OcrResult(text="   ").is_empty is True


def test_image_similarity_is_interface_only_and_validates_score() -> None:
    module = image_similarity()

    assert module.ImageSimilarity.__abstractmethods__ == frozenset({"available", "compare"})
    with pytest.raises(TypeError):
        module.ImageSimilarity()  # type: ignore[abstract]

    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        module.SimilarityResult(score=1.5)


def test_vision_verdict_is_tri_state() -> None:
    module = vision_validator()

    assert module.VisionValidator.__abstractmethods__ == frozenset({"available", "verify"})
    with pytest.raises(TypeError):
        module.VisionValidator()  # type: ignore[abstract]

    assert module.VisionVerdict(verified=None).is_refuted is False
    assert module.VisionVerdict(verified=False).is_refuted is True
    assert module.VisionVerdict(verified=True).is_refuted is False


def test_background_remover_is_interface_only() -> None:
    module = background_remover()

    assert module.BackgroundRemover.__abstractmethods__ == frozenset({"available", "remove"})
    with pytest.raises(TypeError):
        module.BackgroundRemover()  # type: ignore[abstract]

