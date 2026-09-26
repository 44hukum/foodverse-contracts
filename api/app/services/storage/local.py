"""``local`` backend: a private folder plus an HMAC-signed, expiring download route.

Files live under ``LOCAL_STORAGE_DIR``; keys map to paths beneath it and may
not escape it. The download URL is ``{API_BASE_URL}/_storage/local/{key}?exp&sig``,
served by ``app.routers.local_storage`` (mounted only for this backend).
Nothing outside this package and that router may read the folder.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from app.services.storage.base import (
    InvalidKeyError,
    ObjectNotFoundError,
    validate_key,
    validate_ttl,
)


def local_signing_key(jwt_secret: str) -> bytes:
    return hashlib.sha256(b"local-storage" + jwt_secret.encode()).digest()


def local_signature(signing_key: bytes, key: str, exp: int) -> str:
    return hmac.new(signing_key, f"{key}|{exp}".encode(), hashlib.sha256).hexdigest()


class LocalStorage:
    def __init__(self, root: Path, api_base_url: str, jwt_secret: str) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._api_base_url = api_base_url.rstrip("/")
        self._signing_key = local_signing_key(jwt_secret)

    def _path_for(self, key: str) -> Path:
        validate_key(key)
        path = (self._root / key).resolve()
        if self._root not in path.parents:
            raise InvalidKeyError("storage key escapes the storage folder")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    async def get(self, key: str) -> bytes:
        path = self._path_for(key)
        if not path.is_file():
            raise ObjectNotFoundError(f"no object at key {key}")
        return path.read_bytes()

    async def delete(self, key: str) -> None:
        path = self._path_for(key)
        if path.is_file():
            path.unlink()

    async def exists(self, key: str) -> bool:
        return self._path_for(key).is_file()

    def signed_download_url(self, key: str, ttl_seconds: int, filename: str | None = None) -> str:
        validate_key(key)
        validate_ttl(ttl_seconds)
        exp = int((datetime.now(UTC) + timedelta(seconds=ttl_seconds)).timestamp())
        params: dict[str, str] = {
            "exp": str(exp),
            "sig": local_signature(self._signing_key, key, exp),
        }
        if filename:
            params["filename"] = filename
        return f"{self._api_base_url}/_storage/local/{key}?{urlencode(params)}"

    def verify(self, key: str, exp: str, sig: str) -> Path | None:
        """Return the file path for a valid, unexpired signature, else None.

        Only the backend's own download route calls this; it is the one place a
        path leaves the backend, and it never reaches an API response.
        """
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
            path = self._path_for(key)
        except InvalidKeyError:
            return None
        return path if path.is_file() else None
