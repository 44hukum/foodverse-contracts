"""contract_events cannot be changed: rejected in code and again by the database."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Admin, ContractEvent, ContractEventPii
from app.models.event import ActorType, AppendOnlyViolationError, EventType
from app.services.events import ClientInfo, ForbiddenMetadataError, check_metadata, record_event
from tests.conftest import insert_contract_rows, insert_event_row

# --- application-level guard --------------------------------------------------


async def test_orm_update_of_event_is_rejected_before_flush(
    session: AsyncSession, admin: Admin
) -> None:
    contract = await insert_contract_rows(session, admin)
    event = await insert_event_row(session, contract.id)
    event.event_type = "contract.cancelled"
    with pytest.raises(AppendOnlyViolationError):
        await session.flush()


async def test_orm_delete_of_event_is_rejected_before_flush(
    session: AsyncSession, admin: Admin
) -> None:
    contract = await insert_contract_rows(session, admin)
    event = await insert_event_row(session, contract.id)
    await session.delete(event)
    with pytest.raises(AppendOnlyViolationError):
        await session.flush()


async def test_bulk_update_statement_is_rejected(session: AsyncSession, admin: Admin) -> None:
    contract = await insert_contract_rows(session, admin)
    await insert_event_row(session, contract.id)
    with pytest.raises(AppendOnlyViolationError):
        await session.execute(update(ContractEvent).values(actor_type="system"))


async def test_bulk_delete_statement_is_rejected(session: AsyncSession, admin: Admin) -> None:
    contract = await insert_contract_rows(session, admin)
    await insert_event_row(session, contract.id)
    with pytest.raises(AppendOnlyViolationError):
        await session.execute(delete(ContractEvent))


async def test_pii_update_is_rejected_in_code(session: AsyncSession, admin: Admin) -> None:
    contract = await insert_contract_rows(session, admin)
    event = await record_event(
        session,
        contract_id=contract.id,
        event_type=EventType.contract_created,
        actor_type=ActorType.admin,
        actor_id=str(admin.id),
        client=ClientInfo(ip="203.0.113.7", user_agent="ua"),
    )
    pii = await session.get(ContractEventPii, event.id)
    assert pii is not None
    pii.user_agent = "changed"
    with pytest.raises(AppendOnlyViolationError):
        await session.flush()


def test_metadata_may_not_carry_personal_data() -> None:
    assert check_metadata({"from_status": "sent", "to_status": "viewed"}) == {
        "from_status": "sent",
        "to_status": "viewed",
    }
    for key in ("email", "signer_name", "ip", "user_agent", "token", "Signed_IP"):
        with pytest.raises(ForbiddenMetadataError):
            check_metadata({key: "x"})


# --- database-level trigger ---------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE contract_events SET event_type = 'contract.cancelled' WHERE id = :id",
        "DELETE FROM contract_events WHERE id = :id",
    ],
)
async def test_trigger_rejects_raw_update_and_delete(
    session: AsyncSession, admin: Admin, statement: str
) -> None:
    contract = await insert_contract_rows(session, admin)
    event_id = (await insert_event_row(session, contract.id)).id
    await session.commit()
    with pytest.raises(DBAPIError) as excinfo:
        await session.execute(text(statement), {"id": event_id})
    assert "append-only" in str(excinfo.value)
    await session.rollback()
    survivor = await session.get(ContractEvent, event_id)
    assert survivor is not None and survivor.event_type == "contract.created"


async def test_trigger_rejects_truncate(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError) as excinfo:
        await session.execute(text("TRUNCATE contract_events CASCADE"))
    assert "append-only" in str(excinfo.value)


async def test_trigger_rejects_pii_update_but_allows_delete(
    session: AsyncSession, admin: Admin
) -> None:
    contract = await insert_contract_rows(session, admin)
    event_id = (
        await record_event(
            session,
            contract_id=contract.id,
            event_type=EventType.contract_created,
            actor_type=ActorType.admin,
            actor_id=str(admin.id),
            client=ClientInfo(ip="203.0.113.7", user_agent="ua"),
        )
    ).id
    await session.commit()
    with pytest.raises(DBAPIError) as excinfo:
        await session.execute(
            text("UPDATE contract_event_pii SET ip = NULL WHERE event_id = :id"), {"id": event_id}
        )
    assert "append-only" in str(excinfo.value)
    await session.rollback()
    # the retention job's anonymisation path: delete the side row, event untouched
    await session.execute(
        text("DELETE FROM contract_event_pii WHERE event_id = :id"), {"id": event_id}
    )
    await session.commit()
    session.expire_all()
    survivor = await session.get(ContractEvent, event_id)
    assert survivor is not None and survivor.metadata_ == {}
    assert await session.get(ContractEventPii, event_id) is None
