"""Writing audit events. The only way application code adds to ``contract_events``."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import ActorType, ContractEvent, ContractEventPii, EventType

# Keys that would put personal data or secrets into the immutable log (rule 1, 6).
FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "name",
        "email",
        "signer_name",
        "signer_email",
        "typed_name",
        "ip",
        "signed_ip",
        "user_agent",
        "signed_user_agent",
        "token",
        "signing_link",
        "url",
        "password",
        "signature_image",
    }
)


class ForbiddenMetadataError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ClientInfo:
    """Request origin, stored beside the event in ``contract_event_pii``."""

    ip: str | None = None
    user_agent: str | None = None


def check_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    bad = FORBIDDEN_METADATA_KEYS.intersection(k.lower() for k in metadata)
    if bad:
        raise ForbiddenMetadataError(f"metadata must not contain personal data: {sorted(bad)}")
    return metadata


async def record_event(
    session: AsyncSession,
    *,
    contract_id: uuid.UUID,
    event_type: EventType,
    actor_type: ActorType,
    actor_id: str | None,
    metadata: dict[str, Any] | None = None,
    client: ClientInfo | None = None,
) -> ContractEvent:
    """Insert one event (and its PII side row) into the current transaction.

    The caller commits; the event must land in the same transaction as the
    status change it describes (rule 8).
    """
    row = ContractEvent(
        contract_id=contract_id,
        event_type=event_type.value,
        actor_type=actor_type.value,
        actor_id=actor_id,
        metadata_=check_metadata(dict(metadata or {})),
    )
    session.add(row)
    await session.flush()
    if client and (client.ip or client.user_agent):
        session.add(
            ContractEventPii(event_id=row.id, ip=client.ip, user_agent=(client.user_agent or None))
        )
        await session.flush()
    return row
