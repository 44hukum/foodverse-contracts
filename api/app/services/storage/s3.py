"""``s3`` backend: a private bucket on any S3-compatible service, via boto3.

Objects are written without an ACL so the bucket's private default applies
(SPEC.md §6: no public-read ACLs, ever). Downloads are Signature Version 4
pre-signed GET URLs with the TTL the caller passes. boto3 is synchronous, so
every network call runs in a worker thread.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from app.services.storage.base import (
    ObjectNotFoundError,
    StorageError,
    content_type_for,
    safe_filename,
    validate_key,
    validate_ttl,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_MISSING = {"404", "NoSuchKey", "NotFound"}


def _is_missing(error: ClientError) -> bool:
    code = str(error.response.get("Error", {}).get("Code", ""))
    return code in _MISSING


def make_s3_client(
    *,
    endpoint_url: str,
    region: str,
    access_key_id: str,
    secret_access_key: str,
    force_path_style: bool,
) -> S3Client:
    """Build the boto3 client. Empty credentials defer to boto3's default chain (IAM role)."""
    config = BotoConfig(
        signature_version="s3v4",
        s3={"addressing_style": "path" if force_path_style else "auto"},
        retries={"max_attempts": 3, "mode": "standard"},
    )
    kwargs: dict[str, Any] = {"region_name": region, "config": config}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    if access_key_id and secret_access_key:
        kwargs["aws_access_key_id"] = access_key_id
        kwargs["aws_secret_access_key"] = secret_access_key
    return boto3.client("s3", **kwargs)


class S3Storage:
    def __init__(self, client: S3Client, bucket: str) -> None:
        if not bucket:
            raise StorageError("S3_BUCKET must be set when STORAGE_BACKEND=s3")
        self._client = client
        self._bucket = bucket

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        validate_key(key)
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    async def get(self, key: str) -> bytes:
        validate_key(key)
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
        except ClientError as exc:
            if _is_missing(exc):
                raise ObjectNotFoundError(f"no object at key {key}") from exc
            raise StorageError("s3 get_object failed") from exc
        body: bytes = await asyncio.to_thread(response["Body"].read)
        return body

    async def delete(self, key: str) -> None:
        validate_key(key)
        # S3 treats deleting a missing key as success, which keeps delete idempotent.
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def exists(self, key: str) -> bool:
        validate_key(key)
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_missing(exc):
                return False
            raise StorageError("s3 head_object failed") from exc
        return True

    def signed_download_url(self, key: str, ttl_seconds: int, filename: str | None = None) -> str:
        validate_key(key)
        validate_ttl(ttl_seconds)
        name = safe_filename(filename, key.rsplit("/", 1)[-1])
        url: str = self._client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ResponseContentType": content_type_for(key),
                "ResponseContentDisposition": f'attachment; filename="{name}"',
                "ResponseCacheControl": "private, no-store",
            },
            ExpiresIn=ttl_seconds,
            HttpMethod="GET",
        )
        return url
