"""Model and constraint behaviour against the real schema."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Admin, Contract, Signer
from app.security import hash_password
from tests.conftest import PASSWORD, insert_contract_rows


async def test_admin_email_is_unique_case_insensitively(session: AsyncSession) -> None:
    session.add(Admin(email="Ops@Example.com", name="A", password_hash=hash_password(PASSWORD)))
    await session.commit()
    session.add(Admin(email="ops@example.com", name="B", password_hash=hash_password(PASSWORD)))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_contract_status_is_constrained(session: AsyncSession, admin: Admin) -> None:
    contract = await insert_contract_rows(session, admin)
    contract.status = "bogus"
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_one_signer_per_contract(session: AsyncSession, admin: Admin) -> None:
    contract = await insert_contract_rows(session, admin)
    session.add(Signer(contract_id=contract.id, name="Second", email="s@example.com"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_timestamps_are_timezone_aware(session: AsyncSession, admin: Admin) -> None:
    contract = await insert_contract_rows(session, admin)
    contract_id = contract.id
    await session.commit()
    session.expire_all()
    fresh = (await session.execute(select(Contract).where(Contract.id == contract_id))).scalar_one()
    assert fresh.created_at.tzinfo is not None
    assert fresh.updated_at.tzinfo is not None
    assert fresh.status == "draft"
