"""Shared fixtures.

Tests run against the real Postgres named by TEST_DATABASE_URL. The schema is
migrated once per session; each test then runs inside one outer transaction
that is rolled back at the end, so tests never DELETE or TRUNCATE anything
(and never touch contract_events except by inserting). Storage uses the local
backend in a per-test temp folder. No network, no SMTP.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = Path(__file__).resolve().parents[1]

# Fill in anything the shell did not export (scripts/check.sh sources .env; a bare
# `uv run pytest` may not), then force the test-only values. Never override an
# explicit environment variable except the ones that must differ under test.
_env_file = REPO_ROOT / ".env"
if _env_file.exists():
    for key, value in dotenv_values(_env_file).items():
        # python-dotenv reads `KEY=    # comment` as the comment text where the
        # shell reads an empty value; treat such lines as empty, like `source` does.
        if value is not None and value.startswith("#"):
            value = ""
        if value is not None and key not in os.environ:
            os.environ[key] = value
os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://foodverse:foodverse@localhost:5432/foodverse_contracts_test",
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["ENVIRONMENT"] = "test"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["JWT_SECRET"] = "test-only-secret-not-a-real-key-0123456789abcdef"
os.environ["API_BASE_URL"] = "http://testserver"
os.environ["LOG_LEVEL"] = "WARNING"

import uuid  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from typing import Any  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from alembic import command  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Admin, Contract, ContractEvent, Signer  # noqa: E402
from app.security import create_admin_token, hash_password  # noqa: E402

TEST_DB_URL = os.environ["TEST_DATABASE_URL"]
PASSWORD = "correct-horse-battery-staple"  # test-only credential

# A minimal but real PDF header; the API validates magic bytes, not structure.
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


def alembic_config(url: str = TEST_DB_URL) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def migrated_db() -> None:
    """Bring the test database to head once. Migration tests re-run this themselves."""
    command.downgrade(alembic_config(), "base")
    command.upgrade(alembic_config(), "head")


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def db_conn(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            yield conn
        finally:
            if trans.is_active:
                await trans.rollback()


@pytest.fixture
def session_factory(db_conn: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


@pytest.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(local_storage_dir=str(tmp_path / "storage"))


@pytest.fixture
def app(settings: Settings, session_factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    application = create_app(settings)
    application.state.session_factory = session_factory
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver/api/v1",
        headers={"user-agent": "pytest-client/1.0"},
    ) as c:
        yield c


@pytest.fixture
async def admin(session: AsyncSession) -> Admin:
    row = Admin(
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        name="Test Admin",
        password_hash=hash_password(PASSWORD),
    )
    session.add(row)
    await session.commit()
    return row


@pytest.fixture
def auth_headers(settings: Settings, admin: Admin) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_admin_token(settings, admin.id)}"}


def multipart_contract(
    *,
    title: str = "Hotel Aurora Onboarding 2026",
    signer_name: str = "Maria Petrova",
    signer_email: str = "maria@hotel-aurora.example",
    term_end_date: str | None = None,
    pdf: bytes = PDF_BYTES,
    content_type: str = "application/pdf",
) -> dict[str, Any]:
    data: dict[str, str] = {
        "title": title,
        "signer_name": signer_name,
        "signer_email": signer_email,
    }
    if term_end_date is not None:
        data["term_end_date"] = term_end_date
    return {"data": data, "files": {"file": ("contract.pdf", pdf, content_type)}}


async def create_contract_via_api(
    client: httpx.AsyncClient, auth_headers: dict[str, str], **kwargs: Any
) -> dict[str, Any]:
    resp = await client.post(
        "/admin/contracts", headers=auth_headers, **multipart_contract(**kwargs)
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def set_status(session: AsyncSession, contract_id: str, status: str, **cols: Any) -> None:
    """Test helper: move a contract to a status the API under test cannot reach yet."""
    sets = ", ".join(["status = :status", *[f"{k} = :{k}" for k in cols]])
    await session.execute(
        text(f"UPDATE contracts SET {sets} WHERE id = :id"),  # noqa: S608
        {"status": status, "id": uuid.UUID(contract_id), **cols},
    )
    await session.commit()


async def insert_event_row(session: AsyncSession, contract_id: uuid.UUID) -> ContractEvent:
    row = ContractEvent(
        contract_id=contract_id,
        event_type="contract.created",
        actor_type="system",
        actor_id=None,
        occurred_at=datetime.now(UTC),
        metadata_={"to_status": "draft"},
    )
    session.add(row)
    await session.flush()
    return row


async def insert_contract_rows(session: AsyncSession, admin: Admin) -> Contract:
    contract = Contract(
        title="Direct insert",
        status="draft",
        created_by=admin.id,
        original_pdf_key="contracts/x/original.pdf",
        original_pdf_sha256="0" * 64,
        original_pdf_size=len(PDF_BYTES),
    )
    session.add(contract)
    await session.flush()
    session.add(Signer(contract_id=contract.id, name="Direct Signer", email="d@example.com"))
    await session.flush()
    return contract
