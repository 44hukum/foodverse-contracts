"""Audit log tables and the code-level append-only guard.

``contract_events`` is insert-only (CLAUDE.md rule 1). Three layers enforce it:

1. This module: SQLAlchemy session hooks reject any ORM update or delete of
   ``ContractEvent`` rows and any update of ``ContractEventPii`` rows before
   the statement is even built.
2. The migration: a trigger raises on UPDATE/DELETE/TRUNCATE of
   ``contract_events`` and on UPDATE of ``contract_event_pii``.
3. Deployment: the application role has no UPDATE/DELETE grant on the table
   (see docs/runbooks/database-roles.md).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, Index, Text, event, inspect, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, ORMExecuteState, Session, mapped_column, relationship

from app.models.base import Base, utcnow

if TYPE_CHECKING:
    from app.models.contract import Contract


class EventType(enum.StrEnum):
    contract_created = "contract.created"
    contract_sent = "contract.sent"
    link_resent = "link.resent"
    link_viewed = "link.viewed"
    contract_signed = "contract.signed"
    contract_expired = "contract.expired"
    contract_cancelled = "contract.cancelled"
    pdf_downloaded = "pdf.downloaded"
    notification_sent = "notification.sent"
    notification_failed = "notification.failed"
    signer_anonymized = "signer.anonymized"


class ActorType(enum.StrEnum):
    admin = "admin"
    signer = "signer"
    system = "system"


class AppendOnlyViolationError(RuntimeError):
    """Raised in application code before an audit row could be changed."""


class ContractEvent(Base):
    __tablename__ = "contract_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        nullable=False, default=utcnow, server_default=text("now()")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    contract: Mapped[Contract] = relationship(back_populates="events")
    pii: Mapped[ContractEventPii | None] = relationship(back_populates="event", uselist=False)

    __table_args__ = (Index("ix_contract_events_contract_id", "contract_id"),)


class ContractEventPii(Base):
    __tablename__ = "contract_event_pii"

    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("contract_events.id", ondelete="RESTRICT"), primary_key=True
    )
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)

    event: Mapped[ContractEvent] = relationship(back_populates="pii")


# --- code-level guard ---------------------------------------------------------

_MESSAGE = "contract_events is append-only; write a new event instead of changing one"


def _has_changes(obj: object) -> bool:
    state = inspect(obj)
    assert state is not None
    return any(attr.history.has_changes() for attr in state.attrs)


@event.listens_for(Session, "before_flush")
def _reject_audit_changes(session: Session, flush_context: object, instances: object) -> None:
    for obj in session.deleted:
        if isinstance(obj, ContractEvent):
            raise AppendOnlyViolationError(_MESSAGE)
    for obj in session.dirty:
        if isinstance(obj, ContractEvent | ContractEventPii) and _has_changes(obj):
            raise AppendOnlyViolationError(_MESSAGE)


@event.listens_for(Session, "do_orm_execute")
def _reject_audit_statements(state: ORMExecuteState) -> None:
    if not (state.is_update or state.is_delete):
        return
    mapper = state.bind_mapper
    if mapper is None:
        return
    if mapper.class_ is ContractEvent or (mapper.class_ is ContractEventPii and state.is_update):
        raise AppendOnlyViolationError(_MESSAGE)
