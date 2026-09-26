"""Storage interface and ``local`` backend: key layout, round trip, signed URLs, refusals."""

from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import Settings
from app.services.storage import (
    MAX_URL_TTL_SECONDS,
    ORIGINAL_PDF,
    SIGNATURE_PNG,
    SIGNED_PDF,
    InvalidKeyError,
    LocalStorage,
    ObjectNotFoundError,
    StorageError,
    build_storage,
    contract_key,
    validate_key,
)

CONTRACT_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")
KEY = f"contracts/{CONTRACT_ID}/original.pdf"


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "root", "http://testserver", "x" * 40)


# --- key layout (shared by every backend) ----------------------------------------


def test_contract_key_builds_the_spec_layout() -> None:
    assert contract_key(CONTRACT_ID, ORIGINAL_PDF) == KEY
    assert contract_key(CONTRACT_ID, SIGNED_PDF) == f"contracts/{CONTRACT_ID}/signed.pdf"
    assert contract_key(CONTRACT_ID, SIGNATURE_PNG) == f"contracts/{CONTRACT_ID}/signature.png"
    assert validate_key(KEY) == KEY


@pytest.mark.parametrize(
    "key",
    [
        "../etc/passwd",
        "/abs/path",
        f"contracts/../{CONTRACT_ID}/x.pdf",
        f"contracts/{CONTRACT_ID}/../x.pdf",
        f"contracts//{CONTRACT_ID}/x.pdf",
        f"contracts/{CONTRACT_ID}/.hidden",
        f"contracts/{CONTRACT_ID}/",
        f"contracts/{CONTRACT_ID}",
        f"contracts/{CONTRACT_ID}/a/b.pdf",
        f"contracts/{CONTRACT_ID}/bad name.pdf",
        "contracts/abc/original.pdf",  # not a uuid
        "contracts/not-a-uuid-at-all/original.pdf",
        f"other/{CONTRACT_ID}/original.pdf",
        f"Contracts/{CONTRACT_ID}/original.pdf",
        f"contracts/{CONTRACT_ID}/{'x' * 200}.pdf",
        "",
        "x" * 600,
    ],
)
def test_invalid_keys_are_rejected(key: str) -> None:
    with pytest.raises(InvalidKeyError):
        validate_key(key)


def test_contract_key_rejects_bad_file_names() -> None:
    with pytest.raises(InvalidKeyError):
        contract_key(CONTRACT_ID, "../../escape.pdf")


# --- local backend ----------------------------------------------------------------


async def test_round_trip_and_delete(storage: LocalStorage, tmp_path: Path) -> None:
    assert not await storage.exists(KEY)
    await storage.put(KEY, b"%PDF-1.4 data", "application/pdf")
    assert await storage.exists(KEY)
    assert await storage.get(KEY) == b"%PDF-1.4 data"
    assert (tmp_path / "root" / KEY).is_file()
    await storage.delete(KEY)
    assert not await storage.exists(KEY)
    await storage.delete(KEY)  # idempotent


async def test_get_missing_object_raises(storage: LocalStorage) -> None:
    with pytest.raises(ObjectNotFoundError):
        await storage.get(KEY)


async def test_invalid_key_never_touches_the_folder(storage: LocalStorage, tmp_path: Path) -> None:
    for bad in ("../escape.pdf", "contracts/abc/original.pdf"):
        with pytest.raises(InvalidKeyError):
            await storage.put(bad, b"x", "application/pdf")
        with pytest.raises(InvalidKeyError):
            await storage.get(bad)
        with pytest.raises(InvalidKeyError):
            await storage.exists(bad)
        with pytest.raises(InvalidKeyError):
            await storage.delete(bad)
        with pytest.raises(InvalidKeyError):
            storage.signed_download_url(bad, 60)
    assert not (tmp_path / "escape.pdf").exists()
    assert list((tmp_path / "root").iterdir()) == []


async def test_signed_url_verifies_only_when_intact(storage: LocalStorage) -> None:
    await storage.put(KEY, b"%PDF-1.4", "application/pdf")
    url = storage.signed_download_url(KEY, 60, "file.pdf")
    parts = urlsplit(url)
    assert parts.path == f"/_storage/local/{KEY}"
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert storage.verify(KEY, query["exp"], query["sig"]) is not None
    assert storage.verify(KEY, query["exp"], "0" * 64) is None
    assert storage.verify(KEY, str(int(query["exp"]) + 1), query["sig"]) is None
    assert storage.verify(KEY, "1", query["sig"]) is None
    other = contract_key(CONTRACT_ID, SIGNED_PDF)
    assert storage.verify(other, query["exp"], query["sig"]) is None
    assert storage.verify(KEY, "not-a-number", query["sig"]) is None


def test_signed_url_never_exposes_a_path(storage: LocalStorage, tmp_path: Path) -> None:
    url = storage.signed_download_url(KEY, 300)
    assert str(tmp_path) not in url
    assert url.startswith("http://testserver/_storage/local/contracts/")


@pytest.mark.parametrize("ttl", [0, -1, MAX_URL_TTL_SECONDS + 1])
def test_signed_url_rejects_out_of_range_ttl(storage: LocalStorage, ttl: int) -> None:
    with pytest.raises(StorageError, match="ttl"):
        storage.signed_download_url(KEY, ttl)


def test_local_backend_refused_in_production(tmp_path: Path) -> None:
    settings = Settings(
        environment="production", storage_backend="local", local_storage_dir=str(tmp_path)
    )
    with pytest.raises(RuntimeError, match="production"):
        build_storage(settings)


def test_build_storage_local_uses_the_configured_folder(tmp_path: Path) -> None:
    settings = Settings(storage_backend="local", local_storage_dir=str(tmp_path / "files"))
    backend = build_storage(settings)
    assert isinstance(backend, LocalStorage)
    assert (tmp_path / "files").is_dir()


def test_settings_require_long_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings()
