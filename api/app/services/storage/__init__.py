"""File storage behind one interface (SPEC.md §6 "Storage backends").

``build_storage`` picks the backend from ``STORAGE_BACKEND``: ``local`` (a
private folder; dev and tests) or ``s3`` (a private bucket on any
S3-compatible service; production). Callers only ever see keys and
short-lived signed URLs, never paths or bucket locations.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.services.storage.base import (
    MAX_URL_TTL_SECONDS,
    ORIGINAL_PDF,
    SIGNATURE_PNG,
    SIGNED_PDF,
    InvalidKeyError,
    ObjectNotFoundError,
    StorageBackend,
    StorageError,
    contract_key,
    validate_key,
)
from app.services.storage.local import LocalStorage, local_signature, local_signing_key
from app.services.storage.s3 import S3Storage, make_s3_client

__all__ = [
    "MAX_URL_TTL_SECONDS",
    "ORIGINAL_PDF",
    "SIGNATURE_PNG",
    "SIGNED_PDF",
    "InvalidKeyError",
    "LocalStorage",
    "ObjectNotFoundError",
    "S3Storage",
    "StorageBackend",
    "StorageError",
    "build_storage",
    "contract_key",
    "local_signature",
    "local_signing_key",
    "make_s3_client",
    "validate_key",
]


def build_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "local":
        if settings.environment == "production":
            raise RuntimeError("STORAGE_BACKEND=local is not allowed when ENVIRONMENT=production")
        return LocalStorage(
            Path(settings.local_storage_dir), settings.api_base_url, settings.jwt_secret
        )
    client = make_s3_client(
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key,
        force_path_style=settings.s3_force_path_style,
    )
    return S3Storage(client, settings.s3_bucket)
