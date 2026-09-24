"""Password hashing and JWT issuing/verification.

Security choices worth recording:

* **bcrypt directly, not passlib.**  passlib 1.7 is unmaintained and emits
  breakage warnings against bcrypt 4+/5+; a thin wrapper over the reference
  library is less code and less risk.
* **SHA-256 pre-hash before bcrypt.**  bcrypt silently ignores everything past
  its 72nd input byte and rejects NUL bytes, so a long passphrase would be
  weakened and some inputs would raise.  ``base64(sha256(password))`` is a
  constant 44 bytes with no NUL, preserving the full entropy.
* **``jti`` on every token.**  Gives refresh-token rotation and revocation a
  stable identifier to work with without a schema change.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError

from app.config import get_settings

TOKEN_TYPE_ACCESS: Literal["access"] = "access"
TOKEN_TYPE_REFRESH: Literal["refresh"] = "refresh"
TokenType = Literal["access", "refresh"]

#: bcrypt's hard input limit.  Only used for documentation and tests.
BCRYPT_MAX_PASSWORD_BYTES = 72


class TokenError(Exception):
    """A token was missing, malformed, expired or of the wrong type."""


class WeakPasswordError(ValueError):
    """The supplied password does not satisfy the configured policy."""


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """Decoded, verified token contents."""

    subject: str
    token_type: TokenType
    jti: str
    issued_at: datetime
    expires_at: datetime
    claims: dict[str, Any]

    @property
    def user_id(self) -> int | None:
        """Numeric user id, or ``None`` when ``sub`` is not an integer."""
        try:
            return int(self.subject)
        except (TypeError, ValueError):
            return None

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= datetime.now(timezone.utc)


def generate_secret_key(length: int = 48) -> str:
    """Cryptographically random key suitable for ``MVAI_SECRET_KEY``."""
    return secrets.token_urlsafe(length)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def _password_bytecode(password: str) -> bytes:
    """Constant-length, NUL-free byte code fed to bcrypt (see module docstring)."""
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def validate_password_strength(password: str, *, min_length: int | None = None) -> None:
    """Raise :class:`WeakPasswordError` when the policy is not met.

    The rule is deliberately simple (length only).  Composition rules push users
    towards predictable substitutions, which is the opposite of what we want.
    """
    settings = get_settings()
    required = min_length if min_length is not None else settings.password_min_length
    if len(password) < required:
        raise WeakPasswordError(f"password must be at least {required} characters")
    if password.strip() != password:
        raise WeakPasswordError("password must not start or end with whitespace")


def hash_password(password: str) -> str:
    """Hash a password with bcrypt at the configured cost factor."""
    settings = get_settings()
    validate_password_strength(password, min_length=settings.password_min_length)
    digest = bcrypt.hashpw(
        _password_bytecode(password), bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    )
    return digest.decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time password check.

    Never raises: a malformed or legacy hash simply fails to verify, so a
    corrupt row cannot turn a login attempt into a 500.
    """
    if not password or not hashed:
        return False
    try:
        return bcrypt.checkpw(_password_bytecode(password), hashed.encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        return False


def bcrypt_rounds_of(hashed: str) -> int | None:
    """Extract the cost factor from a bcrypt hash, or ``None`` if unparseable."""
    parts = hashed.split("$")
    if len(parts) < 4 or not parts[2].isdigit():
        return None
    return int(parts[2])


def needs_rehash(hashed: str) -> bool:
    """``True`` when a stored hash uses fewer rounds than currently configured.

    Callers should transparently re-hash on the next successful login.
    """
    rounds = bcrypt_rounds_of(hashed)
    if rounds is None:
        return True
    return rounds != get_settings().bcrypt_rounds


# ---------------------------------------------------------------------------
# JSON Web Tokens
# ---------------------------------------------------------------------------


def create_token(
    subject: str | int,
    *,
    token_type: TokenType = TOKEN_TYPE_ACCESS,
    expires_delta: timedelta | None = None,
    claims: dict[str, Any] | None = None,
) -> tuple[str, datetime]:
    """Sign a token for ``subject``.

    Returns:
        A ``(token, expires_at)`` pair - the expiry is returned rather than
        recomputed by the caller, so it can be sent to the client verbatim.
    """
    settings = get_settings()
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + (expires_delta or _default_lifetime(token_type))

    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "jti": secrets.token_urlsafe(16),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": settings.app_name,
    }
    if claims:
        # Reserved keys are never overridable by a caller-supplied claim.
        payload.update({k: v for k, v in claims.items() if k not in payload})

    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_at


def _default_lifetime(token_type: TokenType) -> timedelta:
    settings = get_settings()
    if token_type == TOKEN_TYPE_REFRESH:
        return timedelta(days=settings.refresh_token_expire_days)
    return timedelta(minutes=settings.access_token_expire_minutes)


def create_access_token(
    subject: str | int, *, claims: dict[str, Any] | None = None
) -> tuple[str, datetime]:
    """Short-lived token used to authorise API calls."""
    return create_token(subject, token_type=TOKEN_TYPE_ACCESS, claims=claims)


def create_refresh_token(
    subject: str | int, *, claims: dict[str, Any] | None = None
) -> tuple[str, datetime]:
    """Long-lived token used only to mint new access tokens."""
    return create_token(subject, token_type=TOKEN_TYPE_REFRESH, claims=claims)


def decode_token(token: str, *, expected_type: TokenType | None = None) -> TokenPayload:
    """Verify a token's signature and lifetime, and return its payload.

    Raises:
        TokenError: for any failure.  The distinct PyJWT exception types are
            collapsed on purpose - which precise thing was wrong about a token
            is useful to an attacker and not to a legitimate client.
    """
    settings = get_settings()
    if not token:
        raise TokenError("no token supplied")

    try:
        raw = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.app_name,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token has expired") from exc
    except InvalidTokenError as exc:
        raise TokenError("token is invalid") from exc

    token_type = raw.get("type", TOKEN_TYPE_ACCESS)
    if expected_type is not None and token_type != expected_type:
        raise TokenError(f"expected a {expected_type} token, received {token_type!r}")

    try:
        issued_at = datetime.fromtimestamp(raw["iat"], tz=timezone.utc)
        expires_at = datetime.fromtimestamp(raw["exp"], tz=timezone.utc)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise TokenError("token timestamps are malformed") from exc

    return TokenPayload(
        subject=str(raw.get("sub", "")),
        token_type=token_type,
        jti=str(raw.get("jti", "")),
        issued_at=issued_at,
        expires_at=expires_at,
        claims=raw,
    )


def refresh_access_token(refresh_token: str) -> tuple[str, datetime]:
    """Exchange a valid refresh token for a new access token."""
    payload = decode_token(refresh_token, expected_type=TOKEN_TYPE_REFRESH)
    if not payload.subject:
        raise TokenError("refresh token has no subject")
    return create_access_token(payload.subject)

