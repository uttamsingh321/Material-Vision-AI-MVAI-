"""Configuration layer behaviour: defaults, validation and secret redaction."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config.constants import CANONICAL_MATERIAL_FIELDS
from app.config.settings import Settings, get_settings


def test_defaults_are_usable_without_any_environment() -> None:
    """A fresh clone must boot with no ``.env`` at all."""
    settings = get_settings()

    assert settings.environment == "local"
    assert settings.database_url.startswith("sqlite+aiosqlite")
    assert settings.storage_backend == "local"
    assert settings.queue_backend == "local"
    assert settings.api_v1_prefix.startswith("/")


def test_confidence_weights_are_normalised() -> None:
    settings = get_settings()
    weights = settings.confidence_weights

    assert set(weights) == {"ocr", "vision", "brand", "model", "text", "provider"}
    assert sum(weights.values()) == pytest.approx(1.0)


def test_column_aliases_cover_every_canonical_field() -> None:
    aliases = get_settings().column_aliases

    assert set(CANONICAL_MATERIAL_FIELDS) <= set(aliases)
    # Normalised headers are matched, so aliases must themselves be normalised.
    for aliases_for_field in aliases.values():
        for alias in aliases_for_field:
            assert alias == alias.lower().strip()


def test_column_alias_override_is_additive() -> None:
    settings = Settings(column_aliases_json='{"material_code": ["sap code"]}')
    aliases = settings.column_aliases

    assert "sap code" in aliases["material_code"]
    # Built-in aliases survive the override.
    assert "part number" in aliases["material_code"]


def test_column_alias_override_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="unknown logical field"):
        Settings(column_aliases_json='{"not_a_field": ["x"]}')


def test_column_alias_override_rejects_malformed_json() -> None:
    with pytest.raises(ValidationError, match="not valid JSON"):
        Settings(column_aliases_json="{not json")


def test_review_threshold_may_not_exceed_accept_threshold() -> None:
    with pytest.raises(ValidationError, match="must not exceed"):
        Settings(confidence_accept_threshold=0.5, confidence_review_threshold=0.9)


def test_weights_must_be_probabilities() -> None:
    with pytest.raises(ValidationError, match="between 0.0 and 1.0"):
        Settings(weight_ocr=1.5)


def test_production_environment_rejects_development_defaults() -> None:
    with pytest.raises(ValidationError, match="invalid configuration for production"):
        Settings(environment="production", secret_key="short")


def test_production_environment_accepts_hardened_configuration() -> None:
    settings = Settings(
        environment="production",
        secret_key="a-sufficiently-long-production-secret-key-0123456789",
        first_superuser_password="S3cure-Passphrase!",
        trusted_hosts="mvai.example.com",
        cors_origins="https://mvai.example.com",
    )

    assert settings.is_production is True
    assert settings.trusted_host_list == ("mvai.example.com",)


def test_redacted_masks_credentials_but_keeps_flags() -> None:
    settings = Settings(
        openai_api_key="sk-live-should-never-leak",
        s3_secret_access_key="super-secret",
    )
    redacted = settings.redacted()

    assert redacted["openai_api_key"] == "***configured***"
    assert redacted["s3_secret_access_key"] == "***configured***"
    assert redacted["environment"] == settings.environment


def test_redacted_leaves_unset_secrets_empty() -> None:
    assert Settings(google_api_key="").redacted()["google_api_key"] == ""


def test_csv_settings_expose_trimmed_lists() -> None:
    settings = Settings(
        cors_origins="http://a.test , http://b.test ,, ",
        search_providers="Google, BING",
    )

    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]
    assert settings.search_provider_list == ("google", "bing")


def test_ensure_directories_materialises_library_taxonomy() -> None:
    settings = get_settings()
    settings.ensure_directories()

    for category in settings.material_category_list:
        assert (settings.image_library_dir / category).is_dir()
