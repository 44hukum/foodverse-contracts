from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from pydantic import EmailStr, TypeAdapter, ValidationError

from app.deps import ClientDep, CurrentAdmin, SessionDep, SettingsDep, StorageDep
from app.errors import ApiError, not_found
from app.models.contract import ContractStatus
from app.routers.responses import (
    BAD_REQUEST,
    INTERNAL,
    INVALID_STATE,
    NOT_FOUND,
    UNAUTHORIZED,
    VALIDATION,
    responses,
)
from app.schemas.common import Error, ErrorCode
from app.schemas.contracts import (
    CancelContractRequest,
    ContractDetail,
    ContractList,
    DownloadLink,
    PdfVariant,
)
from app.services import contracts as svc

router = APIRouter(prefix="/admin/contracts", tags=["admin-contracts"])
_EMAIL: TypeAdapter[EmailStr] = TypeAdapter(EmailStr)


def _parse_id(contract_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(contract_id)
    except ValueError as exc:
        raise not_found() from exc


async def _read_upload(upload: UploadFile, limit: int) -> bytes:
    """Read at most limit+1 bytes so an oversized upload is rejected without buffering it all."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            break
    return b"".join(chunks)


@router.post(
    "",
    operation_id="createContract",
    summary="Create a contract (upload PDF and add signer)",
    status_code=status.HTTP_201_CREATED,
    response_model=ContractDetail,
    responses=responses(
        BAD_REQUEST,
        UNAUTHORIZED,
        {413: {"model": Error, "description": "PDF exceeds the size limit."}},
        {415: {"model": Error, "description": "Uploaded file is not a PDF."}},
        VALIDATION,
        INTERNAL,
    ),
)
async def create_contract(
    admin: CurrentAdmin,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    client: ClientDep,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=200)],
    signer_name: Annotated[str, Form(min_length=1, max_length=200)],
    signer_email: Annotated[str, Form(max_length=320)],
    term_end_date: Annotated[date | None, Form()] = None,
) -> ContractDetail:
    try:
        _EMAIL.validate_python(signer_email)
    except ValidationError as exc:
        raise ApiError(
            422,
            ErrorCode.validation_error,
            "One or more fields are invalid.",
            {"fields": [{"field": "signer_email", "message": "Not a valid email address."}]},
        ) from exc
    data = await _read_upload(file, settings.max_pdf_bytes)
    return await svc.create_contract(
        session,
        settings,
        storage,
        admin_id=admin.id,
        new=svc.NewContract(
            title=title.strip(),
            signer_name=signer_name.strip(),
            signer_email=signer_email.strip(),
            term_end_date=term_end_date,
            pdf=data,
            content_type=file.content_type,
        ),
        client=client,
    )


@router.get(
    "",
    operation_id="listContracts",
    summary="List contracts",
    response_model=ContractList,
    responses=responses(BAD_REQUEST, UNAUTHORIZED, VALIDATION, INTERNAL),
)
async def list_contracts(
    admin: CurrentAdmin,
    session: SessionDep,
    status_filter: Annotated[list[ContractStatus] | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query()] = None,
) -> ContractList:
    return await svc.list_contracts(
        session, statuses=status_filter, q=q, limit=limit, cursor=cursor
    )


@router.get(
    "/{contract_id}",
    operation_id="getContract",
    summary="Get a contract with its signer and audit events",
    response_model=ContractDetail,
    responses=responses(UNAUTHORIZED, NOT_FOUND, INTERNAL),
)
async def get_contract(
    admin: CurrentAdmin, session: SessionDep, contract_id: str
) -> ContractDetail:
    return await svc.get_contract(session, _parse_id(contract_id))


@router.post(
    "/{contract_id}/cancel",
    operation_id="cancelContract",
    summary="Cancel a contract",
    response_model=ContractDetail,
    responses=responses(UNAUTHORIZED, NOT_FOUND, INVALID_STATE, VALIDATION, INTERNAL),
)
async def cancel_contract(
    admin: CurrentAdmin,
    session: SessionDep,
    client: ClientDep,
    contract_id: str,
    body: CancelContractRequest | None = None,
) -> ContractDetail:
    return await svc.cancel_contract(
        session,
        contract_id=_parse_id(contract_id),
        admin_id=admin.id,
        reason=body.reason if body else None,
        client=client,
    )


@router.get(
    "/{contract_id}/download",
    operation_id="getContractDownloadUrl",
    summary="Get a short-lived signed URL for the original or signed PDF",
    response_model=DownloadLink,
    responses=responses(UNAUTHORIZED, NOT_FOUND, INVALID_STATE, VALIDATION, INTERNAL),
)
async def get_contract_download_url(
    admin: CurrentAdmin,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    client: ClientDep,
    contract_id: str,
    variant: PdfVariant = PdfVariant.original,
) -> DownloadLink:
    return await svc.download_link(
        session,
        settings,
        storage,
        contract_id=_parse_id(contract_id),
        admin_id=admin.id,
        variant=variant,
        client=client,
    )
