from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, CheckConstraint, Date, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.event import ContractEvent
    from app.models.signer import Signer


class ContractStatus(enum.StrEnum):
    draft = "draft"
    sent = "sent"
    viewed = "viewed"
    signed = "signed"
    expired = "expired"
    cancelled = "cancelled"


STATUS_VALUES = tuple(s.value for s in ContractStatus)


class Contract(TimestampMixin, Base):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=ContractStatus.draft.value, server_default="draft"
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False
    )
    term_end_date: Mapped[date | None] = mapped_column(Date)
    original_pdf_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_pdf_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    original_pdf_size: Mapped[int] = mapped_column(Integer, nullable=False)
    final_pdf_key: Mapped[str | None] = mapped_column(Text)
    final_pdf_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    sent_at: Mapped[datetime | None]
    first_viewed_at: Mapped[datetime | None]
    signed_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    retain_until: Mapped[date | None] = mapped_column(Date)
    anonymized_at: Mapped[datetime | None]

    signer: Mapped[Signer | None] = relationship(back_populates="contract", uselist=False)
    events: Mapped[list[ContractEvent]] = relationship(
        back_populates="contract", order_by="ContractEvent.id"
    )

    __table_args__ = (
        CheckConstraint(
            "status in ('draft','sent','viewed','signed','expired','cancelled')",
            name="ck_contracts_status",
        ),
        CheckConstraint("char_length(title) between 1 and 200", name="ck_contracts_title_length"),
        Index("ix_contracts_status", "status"),
        Index("ix_contracts_created_by", "created_by"),
        Index("ix_contracts_created_at_id", text("created_at desc"), text("id desc")),
    )
