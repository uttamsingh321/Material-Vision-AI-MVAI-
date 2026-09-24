"""Authentication package: password hashing, tokens and dependencies."""

from __future__ import annotations

from app.auth.security import (
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_REFRESH,
    TokenError,
    TokenPayload,
    WeakPasswordError,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_secret_key,
    hash_password,
    needs_rehash,
    refresh_access_token,
    validate_password_strength,
    verify_password,
)

__all__ = [
    "TOKEN_TYPE_ACCESS",
    "TOKEN_TYPE_REFRESH",
    "TokenError",
    "TokenPayload",
    "WeakPasswordError",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "generate_secret_key",
    "hash_password",
    "needs_rehash",
    "refresh_access_token",
    "validate_password_strength",
    "verify_password",
]
