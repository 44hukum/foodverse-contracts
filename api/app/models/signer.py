from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.contract import Contract


class Signer(TimestampMixin, Base):
    __tablename__ = "signers"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    token_hash: Mapped[str | None] = mapped_column(CHAR(64))
    token_created_at: Mapped[datetime | None]
    token_invalidated_at: Mapped[datetime | None]
    typed_name: Mapped[str | None] = mapped_column(Text)
    signature_image_key: Mapped[str | None] = mapped_column(Text)
    consent_given_at: Mapped[datetime | None]
    consent_text_version: Mapped[str | None] = mapped_column(Text)
    signed_ip: Mapped[str | None] = mapped_column(INET)
    signed_user_agent: Mapped[str | None] = mapped_column(Text)

    contract: Mapped[Contract] = relationship(back_populates="signer")

    __table_args__ = (
        Index(
            "ix_signers_token_hash",
            "token_hash",
            unique=True,
            postgresql_where=text("token_hash is not null"),
        ),
    )
