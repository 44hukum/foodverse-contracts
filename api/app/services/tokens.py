"""Signing tokens (SPEC.md §7 "Tokens", "Expiry").

A token is 32 bytes from the OS CSPRNG, encoded base64url without padding
(43 characters). Only ``sha256(token)`` is ever persisted or used as a lookup
or rate-limit key; the raw token exists in the send response, the email to the
signer, and the public URL path, nowhere else (CLAUDE.md rule 6).
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

from app.config import Settings

TOKEN_BYTES = 32
TOKEN_LENGTH = 43  # base64url of 32 bytes, padding stripped
TOKEN_PATTERN = r"^[A-Za-z0-9_-]{43}$"  # noqa: S105 - a shape, not a secret; mirrors openapi.yaml
_TOKEN_RE = re.compile(TOKEN_PATTERN)

MIN_LINK_TTL_DAYS = 1
MAX_LINK_TTL_DAYS = 30


def generate_token() -> str:
    token = base64.urlsafe_b64encode(secrets.token_bytes(TOKEN_BYTES)).rstrip(b"=").decode()
    assert len(token) == TOKEN_LENGTH
    return token


def hash_token(token: str) -> str:
    """The only form of a token that is stored, compared, or keyed on."""
    return hashlib.sha256(token.encode()).hexdigest()


def is_well_formed(token: str) -> bool:
    return _TOKEN_RE.match(token) is not None


def link_ttl_days(settings: Settings, requested: int | None) -> int:
    """The per-send override if given, else the configured default; always 1..30."""
    days = settings.signing_link_ttl_days if requested is None else requested
    if not MIN_LINK_TTL_DAYS <= days <= MAX_LINK_TTL_DAYS:
        raise ValueError(
            f"signing link ttl must be between {MIN_LINK_TTL_DAYS} and {MAX_LINK_TTL_DAYS} days"
        )
    return days


def expiry_for(days: int, now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + timedelta(days=days)


def signing_url(settings: Settings, token: str) -> str:
    """``{WEB_BASE_URL}/sign/{token}``: the link the admin shares and the email carries."""
    return f"{settings.web_base_url.rstrip('/')}/sign/{token}"
