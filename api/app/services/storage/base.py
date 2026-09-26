"""Storage interface, key rules, and shared helpers (SPEC.md §6 "Storage backends").

Every backend satisfies ``StorageBackend``. Keys are the only handle callers
ever hold: no backend returns a filesystem path or a bucket URL, and the only
way to read an object from outside the backend is the short-lived signed URL
from ``signed_download_url`` (CLAUDE.md rule 7).

Key layout, identical in every backend::

    contracts/{contract_id}/original.pdf
    contracts/{contract_id}/signed.pdf
    contracts/{contract_id}/signature.png
"""

from __future__ import annotations

import re
import uuid
from typing import Protocol

# One object per key, always beneath the contract's folder. The file name is a
# single path segment: no slashes, no leading dot, no spaces.
_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

KEY_PREFIX = "contracts"
MAX_KEY_LENGTH = 512
# Signature Version 4 pre-signed URLs cannot outlive seven days; both
# backends apply the same ceiling so a caller cannot mint a long-lived link.
MAX_URL_TTL_SECONDS = 7 * 24 * 3600

ORIGINAL_PDF = "original.pdf"
SIGNED_PDF = "signed.pdf"
SIGNATURE_PNG = "signature.png"


class StorageError(RuntimeError):
    """Base class for everything a backend raises."""


class InvalidKeyError(StorageError):
    """The key does not follow the ``contracts/{contract_id}/{file}`` layout."""


class ObjectNotFoundError(StorageError):
    """``get`` was asked for a key that holds no object."""


class StorageBackend(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    def signed_download_url(
        self, key: str, ttl_seconds: int, filename: str | None = None
    ) -> str: ...


def contract_key(contract_id: uuid.UUID, file_name: str) -> str:
    """Build the key for one of a contract's files, e.g. ``contract_key(id, SIGNED_PDF)``."""
    return validate_key(f"{KEY_PREFIX}/{contract_id}/{file_name}")


def validate_key(key: str) -> str:
    """Return ``key`` if it is ``contracts/{uuid}/{file}``; raise ``InvalidKeyError`` otherwise."""
    if len(key) > MAX_KEY_LENGTH:
        raise InvalidKeyError("invalid storage key")
    parts = key.split("/")
    if len(parts) != 3:
        raise InvalidKeyError("invalid storage key")
    prefix, contract_id, file_name = parts
    well_formed = (
        prefix == KEY_PREFIX
        and _UUID_RE.match(contract_id) is not None
        and _FILE_NAME_RE.match(file_name) is not None
    )
    if not well_formed:
        raise InvalidKeyError("invalid storage key")
    return key


def validate_ttl(ttl_seconds: int) -> int:
    if not 0 < ttl_seconds <= MAX_URL_TTL_SECONDS:
        raise StorageError(f"download URL ttl must be between 1 and {MAX_URL_TTL_SECONDS} seconds")
    return ttl_seconds


def safe_filename(filename: str | None, fallback: str) -> str:
    """Reduce a caller-supplied download name to a header-safe ASCII token."""
    candidate = "".join(c for c in (filename or fallback) if c.isalnum() or c in "-_.")
    return candidate or "file"


def content_type_for(key: str) -> str:
    if key.endswith(".pdf"):
        return "application/pdf"
    if key.endswith(".png"):
        return "image/png"
    return "application/octet-stream"
