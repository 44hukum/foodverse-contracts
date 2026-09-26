"""Local storage backend: key safety, round trip, signed URLs, production refusal."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.services.storage import InvalidKeyError, LocalStorage, build_storage, validate_key


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "root", "http://testserver", "x" * 40)


@pytest.mark.parametrize(
    "key",
    [
        "../etc/passwd",
        "/abs/path",
        "contracts/../x.pdf",
        "a//b",
        "a/.hidden",
        "",
        "bad key",
        "x" * 600,
    ],
)
def test_invalid_keys_are_rejected(key: str) -> None:
    with pytest.raises(InvalidKeyError):
        validate_key(key)


async def test_round_trip_and_delete(storage: LocalStorage, tmp_path: Path) -> None:
    key = "contracts/abc/original.pdf"
    assert not await storage.exists(key)
    await storage.put(key, b"%PDF-1.4 data", "application/pdf")
    assert await storage.exists(key)
    assert await storage.get(key) == b"%PDF-1.4 data"
    assert (tmp_path / "root" / key).is_file()
    await storage.delete(key)
    assert not await storage.exists(key)
    await storage.delete(key)  # idempotent


async def test_signed_url_verifies_only_when_intact(storage: LocalStorage) -> None:
    key = "contracts/abc/original.pdf"
    await storage.put(key, b"%PDF-1.4", "application/pdf")
    url = storage.signed_download_url(key, 60, "file.pdf")
    query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
    assert storage.verify(key, query["exp"], query["sig"]) is not None
    assert storage.verify(key, query["exp"], "0" * 64) is None
    assert storage.verify(key, str(int(query["exp"]) + 1), query["sig"]) is None
    assert storage.verify(key, "1", query["sig"]) is None
    assert storage.verify("contracts/abc/other.pdf", query["exp"], query["sig"]) is None
    assert storage.verify(key, "not-a-number", query["sig"]) is None


def test_local_backend_refused_in_production(tmp_path: Path) -> None:
    settings = Settings(
        environment="production", storage_backend="local", local_storage_dir=str(tmp_path)
    )
    with pytest.raises(RuntimeError, match="production"):
        build_storage(settings)


def test_settings_require_long_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings()
