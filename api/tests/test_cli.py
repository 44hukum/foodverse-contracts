"""Operator CLI: admins are created only here, password read interactively."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app import cli
from app.config import Settings
from app.models import Admin
from app.security import verify_password
from tests.conftest import TEST_DB_URL


@pytest.fixture
def cli_email() -> Iterator[str]:
    email = f"cli-{uuid.uuid4().hex[:8]}@example.com"
    yield email

    async def _cleanup() -> None:
        engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(delete(Admin).where(func.lower(Admin.email) == email.lower()))
        finally:
            await engine.dispose()

    asyncio.run(_cleanup())


async def _load(email: str) -> Admin | None:
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(select(Admin).where(func.lower(Admin.email) == email.lower()))
            ).one_or_none()
            return Admin(**row._mapping) if row else None
    finally:
        await engine.dispose()


def _prompts(monkeypatch: pytest.MonkeyPatch, *answers: str) -> None:
    it = iter(answers)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(it))


def test_create_reset_and_deactivate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], cli_email: str
) -> None:
    settings = Settings()
    _prompts(monkeypatch, "first-password-12", "first-password-12")
    assert cli.main(["create-admin", "--email", cli_email, "--name", "Ops"], settings) == 0
    assert "created admin" in capsys.readouterr().out
    admin = asyncio.run(_load(cli_email))
    assert admin is not None and admin.is_active
    assert admin.password_hash.startswith("$argon2id$")
    assert verify_password(admin.password_hash, "first-password-12")

    _prompts(monkeypatch, "first-password-12", "first-password-12")
    assert cli.main(["create-admin", "--email", cli_email.upper(), "--name", "Dup"], settings) == 1
    assert "already exists" in capsys.readouterr().err

    _prompts(monkeypatch, "second-password-12", "second-password-12")
    assert cli.main(["reset-admin-password", "--email", cli_email], settings) == 0
    admin = asyncio.run(_load(cli_email))
    assert admin is not None and verify_password(admin.password_hash, "second-password-12")
    assert not verify_password(admin.password_hash, "first-password-12")

    assert cli.main(["deactivate-admin", "--email", cli_email], settings) == 0
    admin = asyncio.run(_load(cli_email))
    assert admin is not None and not admin.is_active


def test_password_rules_enforced(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], cli_email: str
) -> None:
    settings = Settings()
    _prompts(monkeypatch, "short", "short")
    assert cli.main(["create-admin", "--email", cli_email, "--name", "Ops"], settings) == 1
    assert "at least 12" in capsys.readouterr().err
    _prompts(monkeypatch, "first-password-12", "different-password-12")
    assert cli.main(["create-admin", "--email", cli_email, "--name", "Ops"], settings) == 1
    assert "do not match" in capsys.readouterr().err
    assert asyncio.run(_load(cli_email)) is None


def test_password_cannot_be_passed_as_flag() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["create-admin", "--email", "a@b.co", "--name", "A", "--password", "x"])
