"""Password hashing (argon2id) and admin JWTs (HS256)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from app.config import Settings

# argon2-cffi defaults are the RFC 9106 low-memory profile or stronger; never lower them.
_hasher = PasswordHasher()

# Verified against when the email is unknown so the response time does not
# reveal whether an account exists.
_DUMMY_HASH = _hasher.hash("not-a-real-password-just-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError):
        return False


def create_admin_token(settings: Settings, admin_id: uuid.UUID, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    claims = {
        "sub": str(admin_id),
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(minutes=settings.admin_jwt_ttl_minutes)).timestamp()),
        "iss": settings.jwt_issuer,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def decode_admin_token(settings: Settings, token: str) -> uuid.UUID | None:
    """Return the admin id from a valid token, or None for any failure."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "iat", "exp", "iss"]},
        )
        return uuid.UUID(str(claims["sub"]))
    except (jwt.PyJWTError, ValueError):
        return None
