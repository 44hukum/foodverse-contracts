"""``s3`` backend against moto's in-process S3, never a real bucket.

moto intercepts botocore at the HTTP layer, so these tests exercise the real
boto3 client code path (put/get/head/delete, pre-signing) without a network.
A tiny hand-written stub covers the error branches moto does not raise.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from app.config import Settings
from app.services.storage import (
    MAX_URL_TTL_SECONDS,
    ORIGINAL_PDF,
    SIGNED_PDF,
    InvalidKeyError,
    ObjectNotFoundError,
    S3Storage,
    StorageError,
    build_storage,
    contract_key,
    make_s3_client,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

BUCKET = "foodverse-contracts-test"
CONTRACT_ID = uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
KEY = contract_key(CONTRACT_ID, ORIGINAL_PDF)
PDF = b"%PDF-1.4 fake body"


@pytest.fixture
def s3_client() -> Iterator[S3Client]:
    with mock_aws():
        client = make_s3_client(
            endpoint_url="",
            region="us-east-1",
            access_key_id="testing",  # moto accepts any credentials
            secret_access_key="testing",
            force_path_style=False,
        )
        client.create_bucket(Bucket=BUCKET)
        yield client


@pytest.fixture
def storage(s3_client: S3Client) -> S3Storage:
    return S3Storage(s3_client, BUCKET)


# --- object lifecycle ------------------------------------------------------------


async def test_round_trip_and_delete(storage: S3Storage, s3_client: S3Client) -> None:
    assert not await storage.exists(KEY)
    await storage.put(KEY, PDF, "application/pdf")
    assert await storage.exists(KEY)
    assert await storage.get(KEY) == PDF
    head = s3_client.head_object(Bucket=BUCKET, Key=KEY)
    assert head["ContentType"] == "application/pdf"
    assert head["ContentLength"] == len(PDF)
    await storage.delete(KEY)
    assert not await storage.exists(KEY)
    await storage.delete(KEY)  # idempotent, like the local backend


async def test_objects_live_under_the_contract_prefix(
    storage: S3Storage, s3_client: S3Client
) -> None:
    await storage.put(KEY, PDF, "application/pdf")
    await storage.put(contract_key(CONTRACT_ID, SIGNED_PDF), PDF, "application/pdf")
    listed = s3_client.list_objects_v2(Bucket=BUCKET, Prefix=f"contracts/{CONTRACT_ID}/")
    assert sorted(o["Key"] for o in listed["Contents"]) == [
        f"contracts/{CONTRACT_ID}/original.pdf",
        f"contracts/{CONTRACT_ID}/signed.pdf",
    ]


async def test_get_missing_object_raises(storage: S3Storage) -> None:
    with pytest.raises(ObjectNotFoundError):
        await storage.get(KEY)


async def test_put_overwrites_in_place(storage: S3Storage) -> None:
    await storage.put(KEY, b"v1", "application/pdf")
    await storage.put(KEY, b"v2", "application/pdf")
    assert await storage.get(KEY) == b"v2"


async def test_objects_are_private(storage: S3Storage, s3_client: S3Client) -> None:
    await storage.put(KEY, PDF, "application/pdf")
    grants = s3_client.get_object_acl(Bucket=BUCKET, Key=KEY)["Grants"]
    assert grants, "owner grant expected"
    for grant in grants:
        assert grant["Grantee"]["Type"] == "CanonicalUser"
        assert "URI" not in grant["Grantee"]  # no AllUsers / AuthenticatedUsers


async def test_invalid_keys_never_reach_the_bucket(storage: S3Storage, s3_client: S3Client) -> None:
    for bad in ("../escape.pdf", "contracts/abc/original.pdf", f"other/{CONTRACT_ID}/x.pdf"):
        with pytest.raises(InvalidKeyError):
            await storage.put(bad, PDF, "application/pdf")
        with pytest.raises(InvalidKeyError):
            await storage.get(bad)
        with pytest.raises(InvalidKeyError):
            await storage.exists(bad)
        with pytest.raises(InvalidKeyError):
            await storage.delete(bad)
        with pytest.raises(InvalidKeyError):
            storage.signed_download_url(bad, 60)
    assert "Contents" not in s3_client.list_objects_v2(Bucket=BUCKET)


# --- signed download URLs --------------------------------------------------------


async def test_signed_url_is_presigned_get_with_ttl(storage: S3Storage) -> None:
    await storage.put(KEY, PDF, "application/pdf")
    url = storage.signed_download_url(KEY, 300, "hotel-aurora-original.pdf")
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert parts.scheme == "https"
    assert BUCKET in url
    assert parts.path.endswith(f"/contracts/{CONTRACT_ID}/original.pdf")
    assert query["X-Amz-Algorithm"] == "AWS4-HMAC-SHA256"
    assert query["X-Amz-Expires"] == "300"
    assert query["X-Amz-Signature"]
    assert query["X-Amz-SignedHeaders"] == "host"
    disposition = 'attachment; filename="hotel-aurora-original.pdf"'
    assert query["response-content-disposition"] == disposition
    assert query["response-content-type"] == "application/pdf"
    assert query["response-cache-control"] == "private, no-store"


def test_signed_url_sanitises_filename_and_defaults_it(storage: S3Storage) -> None:
    url = storage.signed_download_url(KEY, 60, 'evil"; rm -rf /.pdf')
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert query["response-content-disposition"] == 'attachment; filename="evilrm-rf.pdf"'
    url = storage.signed_download_url(KEY, 60)
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert query["response-content-disposition"] == 'attachment; filename="original.pdf"'


def test_signed_url_needs_no_object_and_no_network(storage: S3Storage) -> None:
    # Pre-signing is a local computation; it must not require the object to exist.
    assert "X-Amz-Signature" in storage.signed_download_url(KEY, 60)


@pytest.mark.parametrize("ttl", [0, -5, MAX_URL_TTL_SECONDS + 1])
def test_signed_url_rejects_out_of_range_ttl(storage: S3Storage, ttl: int) -> None:
    with pytest.raises(StorageError, match="ttl"):
        storage.signed_download_url(KEY, ttl)


def test_default_download_ttl_is_five_minutes(storage: S3Storage) -> None:
    settings = Settings()
    assert settings.download_url_ttl_seconds == 300
    url = storage.signed_download_url(KEY, settings.download_url_ttl_seconds)
    assert parse_qs(urlsplit(url).query)["X-Amz-Expires"] == ["300"]


# --- wiring ------------------------------------------------------------------------


def test_build_storage_selects_s3_in_production() -> None:
    with mock_aws():
        settings = Settings(
            environment="production",
            storage_backend="s3",
            s3_endpoint_url="",
            s3_bucket=BUCKET,
            s3_region="eu-central-1",
            s3_access_key_id="testing",
            s3_secret_access_key="testing",
        )
        backend = build_storage(settings)
    assert isinstance(backend, S3Storage)
    assert "eu-central-1" in backend.signed_download_url(KEY, 60)


def test_build_storage_s3_requires_bucket() -> None:
    settings = Settings(storage_backend="s3", s3_endpoint_url="", s3_bucket="")
    with pytest.raises(StorageError, match="S3_BUCKET"):
        build_storage(settings)


def test_make_s3_client_honours_endpoint_and_path_style() -> None:
    with mock_aws():
        client = make_s3_client(
            endpoint_url="http://localhost:9000",
            region="us-east-1",
            access_key_id="testing",
            secret_access_key="testing",
            force_path_style=True,
        )
        url = S3Storage(client, BUCKET).signed_download_url(KEY, 60)
    assert url.startswith(f"http://localhost:9000/{BUCKET}/contracts/")


# --- error mapping (branches moto cannot produce) ----------------------------------


class _FailingClient:
    """Minimal stub: every call raises the configured ClientError."""

    def __init__(self, code: str) -> None:
        self._error = ClientError({"Error": {"Code": code, "Message": code}}, "op")

    def _raise(self, **_: Any) -> Any:
        raise self._error

    put_object = get_object = head_object = delete_object = _raise


async def test_non_missing_errors_surface_as_storage_error() -> None:
    storage = S3Storage(_FailingClient("AccessDenied"), BUCKET)  # type: ignore[arg-type]
    with pytest.raises(StorageError):
        await storage.get(KEY)
    with pytest.raises(StorageError):
        await storage.exists(KEY)
    with pytest.raises(ClientError):
        await storage.put(KEY, PDF, "application/pdf")


async def test_missing_errors_map_to_not_found_and_false() -> None:
    storage = S3Storage(_FailingClient("NoSuchKey"), BUCKET)  # type: ignore[arg-type]
    with pytest.raises(ObjectNotFoundError):
        await storage.get(KEY)
    storage = S3Storage(_FailingClient("404"), BUCKET)  # type: ignore[arg-type]
    assert await storage.exists(KEY) is False
