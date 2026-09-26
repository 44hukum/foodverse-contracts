"""File storage behind one interface (SPEC.md §6 "Storage backends").

``StorageBackend`` is the contract every backend satisfies. This module ships
the ``local`` backend, which is the default for dev and tests: files live
under ``LOCAL_STORAGE_DIR`` and downloads go through an HMAC-signed, expiring
URL served by ``app.routers.local_storage``. The ``s3`` backend is delivered
by the storage issue (FVR-9) and is selected through ``build_storage``.

Nothing outside this module and its router may read from
``LOCAL_STORAGE_DIR`` (CLAUDE.md rule 7).
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

from app.config import Settings

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")


class StorageError(RuntimeError):
    pass


class InvalidKeyError(StorageError):
    pass


class StorageBackend(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    def signed_download_url(
        self, key: str, ttl_seconds: int, filename: str | None = None
    ) -> str: ...


def validate_key(key: str) -> str:
    if len(key) > 512 or not _KEY_RE.match(key) or ".." in key.split("/"):
        raise InvalidKeyError("invalid storage key")
    return key


def local_signing_key(jwt_secret: str) -> bytes:
    return hashlib.sha256(b"local-storage" + jwt_secret.encode()).digest()


def local_signature(signing_key: bytes, key: str, exp: int) -> str:
    return hmac.new(signing_key, f"{key}|{exp}".encode(), hashlib.sha256).hexdigest()


class LocalStorage:
    """Files under a private folder; keys map to paths beneath it and may not escape it."""

    def __init__(self, root: Path, api_base_url: str, jwt_secret: str) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._api_base_url = api_base_url.rstrip("/")
        self._signing_key = local_signing_key(jwt_secret)

    def path_for(self, key: str) -> Path:
        validate_key(key)
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise InvalidKeyError("storage key escapes the storage folder")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    async def get(self, key: str) -> bytes:
        path = self.path_for(key)
        if not path.is_file():
            raise StorageError(f"no object at key {key}")
        return path.read_bytes()

    async def delete(self, key: str) -> None:
        path = self.path_for(key)
        if path.is_file():
            path.unlink()

    async def exists(self, key: str) -> bool:
        return self.path_for(key).is_file()

    def signed_download_url(self, key: str, ttl_seconds: int, filename: str | None = None) -> str:
        validate_key(key)
        exp = int((datetime.now(UTC) + timedelta(seconds=ttl_seconds)).timestamp())
        params: dict[str, str] = {
            "exp": str(exp),
            "sig": local_signature(self._signing_key, key, exp),
        }
        if filename:
            params["filename"] = filename
        return f"{self._api_base_url}/_storage/local/{key}?{urlencode(params)}"

    def verify(self, key: str, exp: str, sig: str) -> Path | None:
        """Return the file path for a valid, unexpired signature, else None."""
        try:
            validate_key(key)
            exp_int = int(exp)
        except (InvalidKeyError, ValueError):
            return None
        if exp_int < int(datetime.now(UTC).timestamp()):
            return None
        expected = local_signature(self._signing_key, key, exp_int)
        if not hmac.compare_digest(expected, sig):
            return None
        try:
            path = self.path_for(key)
        except InvalidKeyError:
            return None
        return path if path.is_file() else None


def build_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "local":
        if settings.environment == "production":
            raise RuntimeError("STORAGE_BACKEND=local is not allowed when ENVIRONMENT=production")
        return LocalStorage(
            Path(settings.local_storage_dir), settings.api_base_url, settings.jwt_secret
        )
    raise RuntimeError(
        "STORAGE_BACKEND=s3 is not available in this build; the s3 backend ships with FVR-9"
    )
