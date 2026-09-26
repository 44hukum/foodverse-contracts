"""Public signing schemas, named one-to-one with openapi.yaml."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.contract import ContractStatus
from app.schemas.contracts import DownloadLink

SIGNATURE_DATA_URL_PATTERN = r"^data:image/png;base64,[A-Za-z0-9+/=]+$"
SIGNATURE_DATA_URL_PREFIX = "data:image/png;base64,"


class PublicSigner(BaseModel):
    name: str
    email: str


class PublicPdf(BaseModel):
    url: str
    expires_at: datetime
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int


class PublicContract(BaseModel):
    contract_id: uuid.UUID
    title: str
    status: ContractStatus
    signer: PublicSigner
    sent_by: str
    expires_at: datetime
    pdf: PublicPdf
    consent_text: str
    consent_text_version: str


class SubmitSignatureRequest(BaseModel):
    typed_name: str = Field(min_length=2, max_length=200)
    signature_image: str = Field(pattern=SIGNATURE_DATA_URL_PATTERN, max_length=700_000)
    consent: Literal[True]
    consent_text_version: str = Field(min_length=1, max_length=64)


class SignatureResult(BaseModel):
    contract_id: uuid.UUID
    status: ContractStatus
    signed_at: datetime
    final_pdf_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    download: DownloadLink
