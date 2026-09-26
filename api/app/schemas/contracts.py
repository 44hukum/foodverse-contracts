from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.contract import ContractStatus
from app.models.event import ActorType, EventType
from app.schemas.common import ApiModel


class PdfVariant(enum.StrEnum):
    original = "original"
    signed = "signed"


class CancelContractRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class Signer(ApiModel):
    id: uuid.UUID
    name: str | None
    email: str | None
    has_active_link: bool
    token_created_at: datetime | None = None
    typed_name: str | None = None
    consent_given_at: datetime | None = None
    consent_text_version: str | None = None
    signed_ip: str | None = None
    signed_user_agent: str | None = None


class ContractSummary(ApiModel):
    id: uuid.UUID
    title: str
    status: ContractStatus
    created_by: uuid.UUID
    term_end_date: date | None = None
    signer_name: str | None
    signer_email: str | None
    original_pdf_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    final_pdf_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    sent_at: datetime | None = None
    first_viewed_at: datetime | None = None
    signed_at: datetime | None = None
    expires_at: datetime | None = None
    cancelled_at: datetime | None = None
    retain_until: date | None = None
    anonymized_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ContractEvent(ApiModel):
    id: int
    contract_id: uuid.UUID
    event_type: EventType
    actor_type: ActorType
    actor_id: str | None = None
    occurred_at: datetime
    ip: str | None = None
    user_agent: str | None = None
    metadata: dict[str, Any]


class ContractDetail(ContractSummary):
    original_pdf_size: int
    signer: Signer
    events: list[ContractEvent]


class ContractList(BaseModel):
    items: list[ContractSummary]
    next_cursor: str | None


class DownloadLink(BaseModel):
    variant: PdfVariant
    url: str
    expires_at: datetime
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    filename: str
