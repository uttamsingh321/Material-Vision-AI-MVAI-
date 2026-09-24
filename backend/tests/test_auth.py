"""Authentication layer tests: password hashing and JWT lifecycle."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.auth.security import (
    BCRYPT_MAX_PASSWORD_BYTES,
    TOKEN_TYPE_REFRESH,
    TokenError,
    WeakPasswordError,
    bcrypt_rounds_of,
    create_access_token,
    create_refresh_token,
    create_token,
    decode_token,
    generate_secret_key,
    hash_password,
    needs_rehash,
    refresh_access_token,
    validate_password_strength,
    verify_password,
)

PASSWORD = "Correct-Horse-Battery-Staple!"


def test_hash_is_verifiable_and_salted() -> None:
    first = hash_password(PASSWORD)
    second = hash_password(PASSWORD)

    assert first != second, "each hash must use a fresh salt"
    assert verify_password(PASSWORD, first) is True
    assert verify_password("wrong", first) is False


def test_verify_password_never_raises_on_malformed_hash() -> None:
    assert verify_password(PASSWORD, "not-a-bcrypt-hash") is False
    assert verify_password(PASSWORD, "") is False
    assert verify_password("", hash_password(PASSWORD)) is False


def test_long_passphrases_are_not_truncated() -> None:
    """A passphrase longer than bcrypt's 72-byte limit must stay distinguishable."""
    base = "x" * BCRYPT_MAX_PASSWORD_BYTES
    hashed = hash_password(f"{base}-AAAA")

    assert verify_password(f"{base}-AAAA", hashed) is True
    # Without the SHA-256 pre-hash this would also verify, because bcrypt
    # ignores everything past byte 72.
    assert verify_password(f"{base}-BBBB", hashed) is False


def test_password_policy_rejects_short_and_padded_passwords() -> None:
    with pytest.raises(WeakPasswordError, match="at least"):
        validate_password_strength("short")

    with pytest.raises(WeakPasswordError, match="whitespace"):
        validate_password_strength(" padded-password ")

    with pytest.raises(WeakPasswordError):
        hash_password("short")


def test_bcrypt_rounds_parsing() -> None:
    hashed = hash_password(PASSWORD)

    assert bcrypt_rounds_of(hashed) == 12
    assert bcrypt_rounds_of("garbage") is None
    assert needs_rehash("garbage") is True


def test_generate_secret_key_is_random_and_long() -> None:
    first, second = generate_secret_key(), generate_secret_key()

    assert first != second
    assert len(first) >= 48


def test_access_token_round_trip() -> None:
    token, expires_at = create_access_token(42, claims={"role": "admin"})
    payload = decode_token(token, expected_type="access")

    assert payload.user_id == 42
    assert payload.subject == "42"
    assert payload.token_type == "access"
    assert payload.jti
    assert payload.claims["role"] == "admin"
    assert payload.expires_at == expires_at.replace(microsecond=0)
    assert payload.is_expired is False


def test_refresh_token_is_rejected_where_access_is_expected() -> None:
    token, _ = create_refresh_token(7)

    with pytest.raises(TokenError, match="expected a access token"):
        decode_token(token, expected_type="access")

    assert decode_token(token).token_type == TOKEN_TYPE_REFRESH


def test_refresh_access_token_exchanges_credentials() -> None:
    refresh, _ = create_refresh_token(11)
    access, _ = refresh_access_token(refresh)

    assert decode_token(access, expected_type="access").user_id == 11


def test_expired_token_is_rejected() -> None:
    token, _ = create_token(1, expires_delta=timedelta(seconds=-5))

    with pytest.raises(TokenError, match="expired"):
        decode_token(token)


def test_tampered_token_is_rejected() -> None:
    token, _ = create_access_token(1)
    header, payload, signature = token.split(".")

    with pytest.raises(TokenError, match="invalid"):
        decode_token(f"{header}.{payload}.{signature[:-2]}xx")


def test_empty_token_is_rejected() -> None:
    with pytest.raises(TokenError, match="no token supplied"):
        decode_token("")


def test_reserved_claims_cannot_be_overridden() -> None:
    """A caller must not be able to forge ``sub`` or ``exp`` via ``claims``."""
    token, _ = create_access_token(5, claims={"sub": "999", "exp": 1, "role": "viewer"})
    payload = decode_token(token)

    assert payload.subject == "5"
    assert payload.claims["role"] == "viewer"


def test_token_payload_user_id_tolerates_non_numeric_subject() -> None:
    token, _ = create_token("not-a-number")
    assert decode_token(token).user_id is None
