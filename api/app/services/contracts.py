"""Contract use cases: create, list, get, cancel, download link.

Every status change is a conditional ``UPDATE ... WHERE status IN (...)`` and
writes exactly one ``contract_events`` row in the same transaction (rule 8).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Select, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.errors import ApiError, invalid_state, not_found
from app.models.contract import Contract, ContractStatus
from app.models.event import ActorType, EventType
from app.models.event import ContractEvent as ContractEventModel
from app.models.signer import Signer
from app.schemas.common import ErrorCode
from app.schemas.contracts import (
    ContractDetail,
    ContractEvent,
    ContractList,
    ContractSummary,
    DownloadLink,
    PdfVariant,
)
from app.schemas.contracts import Signer as SignerSchema
from app.services.events import ClientInfo, record_event
from app.services.storage import StorageBackend

PDF_MAGIC = b"%PDF-"
CANCEL_ALLOWED_FROM = (ContractStatus.draft, ContractStatus.sent, ContractStatus.viewed)


def original_pdf_key(contract_id: uuid.UUID) -> str:
    return f"contracts/{contract_id}/original.pdf"


def signed_pdf_key(contract_id: uuid.UUID) -> str:
    return f"contracts/{contract_id}/signed.pdf"


# --- serialisation ---------------------------------------------------------------


def signer_has_active_link(signer: Signer, contract: Contract) -> bool:
    if signer.token_hash is None or signer.token_invalidated_at is not None:
        return False
    return contract.expires_at is None or contract.expires_at > datetime.now(UTC)


def to_summary(contract: Contract) -> ContractSummary:
    signer = contract.signer
    return ContractSummary(
        id=contract.id,
        title=contract.title,
        status=ContractStatus(contract.status),
        created_by=contract.created_by,
        term_end_date=contract.term_end_date,
        signer_name=signer.name if signer else None,
        signer_email=signer.email if signer else None,
        original_pdf_sha256=contract.original_pdf_sha256,
        final_pdf_sha256=contract.final_pdf_sha256,
        sent_at=contract.sent_at,
        first_viewed_at=contract.first_viewed_at,
        signed_at=contract.signed_at,
        expires_at=contract.expires_at,
        cancelled_at=contract.cancelled_at,
        retain_until=contract.retain_until,
        anonymized_at=contract.anonymized_at,
        created_at=contract.created_at,
        updated_at=contract.updated_at,
    )


def to_detail(contract: Contract) -> ContractDetail:
    signer = contract.signer
    if signer is None:  # pragma: no cover - every contract is created with a signer
        raise RuntimeError(f"contract {contract.id} has no signer row")
    summary = to_summary(contract)
    return ContractDetail(
        **summary.model_dump(),
        original_pdf_size=contract.original_pdf_size,
        signer=SignerSchema(
            id=signer.id,
            name=signer.name,
            email=signer.email,
            has_active_link=signer_has_active_link(signer, contract),
            token_created_at=signer.token_created_at,
            typed_name=signer.typed_name,
            consent_given_at=signer.consent_given_at,
            consent_text_version=signer.consent_text_version,
            signed_ip=str(signer.signed_ip) if signer.signed_ip is not None else None,
            signed_user_agent=signer.signed_user_agent,
        ),
        events=[
            ContractEvent(
                id=e.id,
                contract_id=e.contract_id,
                event_type=EventType(e.event_type),
                actor_type=ActorType(e.actor_type),
                actor_id=e.actor_id,
                occurred_at=e.occurred_at,
                ip=str(e.pii.ip) if e.pii and e.pii.ip is not None else None,
                user_agent=e.pii.user_agent if e.pii else None,
                metadata=e.metadata_,
            )
            for e in contract.events
        ],
    )


def _detail_query() -> Select[Contract]:
    return select(Contract).options(
        selectinload(Contract.signer),
        selectinload(Contract.events).selectinload(ContractEventModel.pii),
    )


# --- use cases ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NewContract:
    title: str
    signer_name: str
    signer_email: str
    term_end_date: date | None
    pdf: bytes
    content_type: str | None


def validate_pdf_upload(settings: Settings, content_type: str | None, data: bytes) -> None:
    """Reject non-PDFs (415) and oversized files (413) before anything is stored."""
    if (content_type or "").split(";")[0].strip().lower() != "application/pdf":
        raise ApiError(415, ErrorCode.unsupported_media_type, "Only PDF files are accepted.")
    if len(data) > settings.max_pdf_bytes:
        raise ApiError(
            413,
            ErrorCode.payload_too_large,
            f"PDF must be {settings.max_pdf_bytes // (1024 * 1024)} MB or smaller.",
            {"max_bytes": settings.max_pdf_bytes},
        )
    if not data.startswith(PDF_MAGIC):
        raise ApiError(415, ErrorCode.unsupported_media_type, "Only PDF files are accepted.")


async def create_contract(
    session: AsyncSession,
    settings: Settings,
    storage: StorageBackend,
    *,
    admin_id: uuid.UUID,
    new: NewContract,
    client: ClientInfo,
) -> ContractDetail:
    validate_pdf_upload(settings, new.content_type, new.pdf)
    contract_id = uuid.uuid4()
    key = original_pdf_key(contract_id)
    sha256 = hashlib.sha256(new.pdf).hexdigest()
    await storage.put(key, new.pdf, "application/pdf")
    try:
        contract = Contract(
            id=contract_id,
            title=new.title,
            status=ContractStatus.draft.value,
            created_by=admin_id,
            term_end_date=new.term_end_date,
            original_pdf_key=key,
            original_pdf_sha256=sha256,
            original_pdf_size=len(new.pdf),
        )
        session.add(contract)
        session.add(Signer(contract_id=contract_id, name=new.signer_name, email=new.signer_email))
        await session.flush()
        await record_event(
            session,
            contract_id=contract_id,
            event_type=EventType.contract_created,
            actor_type=ActorType.admin,
            actor_id=str(admin_id),
            metadata={
                "to_status": ContractStatus.draft.value,
                "original_pdf_sha256": sha256,
                "original_pdf_size": len(new.pdf),
            },
            client=client,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        await storage.delete(key)
        raise
    return await get_contract(session, contract_id)


async def load_contract(session: AsyncSession, contract_id: uuid.UUID) -> Contract:
    stmt = _detail_query().where(Contract.id == contract_id)
    contract = (await session.execute(stmt)).scalar_one_or_none()
    if contract is None:
        raise not_found()
    return contract


async def get_contract(session: AsyncSession, contract_id: uuid.UUID) -> ContractDetail:
    session.expire_all()
    return to_detail(await load_contract(session, contract_id))


# cursor = base64url("<created_at iso>|<id>") of the last item on the previous page
def _encode_cursor(contract: Contract) -> str:
    raw = f"{contract.created_at.isoformat()}|{contract.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded).decode()
        created_str, id_str = raw.split("|", 1)
        created = datetime.fromisoformat(created_str)
        if created.tzinfo is None:
            raise ValueError("naive cursor timestamp")
        return created, uuid.UUID(id_str)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ApiError(400, ErrorCode.bad_request, "Invalid cursor.") from exc


async def list_contracts(
    session: AsyncSession,
    *,
    statuses: list[ContractStatus] | None,
    q: str | None,
    limit: int,
    cursor: str | None,
) -> ContractList:
    stmt = (
        select(Contract)
        .options(selectinload(Contract.signer))
        .order_by(Contract.created_at.desc(), Contract.id.desc())
        .limit(limit + 1)
    )
    if statuses:
        stmt = stmt.where(Contract.status.in_([s.value for s in statuses]))
    if q:
        pattern = f"%{_escape_like(q)}%"
        stmt = stmt.outerjoin(Signer, Signer.contract_id == Contract.id).where(
            or_(
                Contract.title.ilike(pattern, escape="\\"),
                Signer.name.ilike(pattern, escape="\\"),
                Signer.email.ilike(pattern, escape="\\"),
            )
        )
    if cursor:
        created, last_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Contract.created_at < created,
                (Contract.created_at == created) & (Contract.id < last_id),
            )
        )
    rows = list((await session.execute(stmt)).scalars().all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1])
    return ContractList(items=[to_summary(c) for c in rows], next_cursor=next_cursor)


def _escape_like(value: str) -> str:
    return re.sub(r"([\\%_])", r"\\\1", value)


async def cancel_contract(
    session: AsyncSession,
    *,
    contract_id: uuid.UUID,
    admin_id: uuid.UUID,
    reason: str | None,
    client: ClientInfo,
) -> ContractDetail:
    # Lock the row so the status we report in a 409 is the status we decided on.
    locked = (
        await session.execute(select(Contract).where(Contract.id == contract_id).with_for_update())
    ).scalar_one_or_none()
    if locked is None:
        raise not_found()
    from_status = locked.status
    if from_status not in {s.value for s in CANCEL_ALLOWED_FROM}:
        await session.rollback()
        raise invalid_state(
            f"Contract cannot be cancelled from status '{from_status}'.",
            {"status": from_status, "allowed_from": [s.value for s in CANCEL_ALLOWED_FROM]},
        )
    now = datetime.now(UTC)
    updated = (
        (
            await session.execute(
                update(Contract)
                .where(
                    Contract.id == contract_id,
                    Contract.status.in_([s.value for s in CANCEL_ALLOWED_FROM]),
                )
                .values(status=ContractStatus.cancelled.value, cancelled_at=now, updated_at=now)
                .returning(Contract.id)
            )
        )
        .scalars()
        .all()
    )
    if len(updated) != 1:  # pragma: no cover - guarded by the row lock above
        await session.rollback()
        raise invalid_state(
            "Contract cannot be cancelled from its current status.", {"status": from_status}
        )
    # The hash stays so the cancelled link answers 410 contract_cancelled rather than
    # 404 (SPEC.md §4); token_invalidated_at is what makes it dead.
    await session.execute(
        update(Signer)
        .where(
            Signer.contract_id == contract_id,
            Signer.token_hash.is_not(None),
            Signer.token_invalidated_at.is_(None),
        )
        .values(token_invalidated_at=now, updated_at=now)
    )
    metadata: dict[str, object] = {
        "from_status": from_status,
        "to_status": ContractStatus.cancelled.value,
    }
    if reason:
        metadata["reason"] = reason
    await record_event(
        session,
        contract_id=contract_id,
        event_type=EventType.contract_cancelled,
        actor_type=ActorType.admin,
        actor_id=str(admin_id),
        metadata=metadata,
        client=client,
    )
    await session.commit()
    return await get_contract(session, contract_id)


def download_filename(title: str, variant: PdfVariant) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80] or "contract"
    return f"{slug}-{variant.value}.pdf"


async def download_link(
    session: AsyncSession,
    settings: Settings,
    storage: StorageBackend,
    *,
    contract_id: uuid.UUID,
    admin_id: uuid.UUID,
    variant: PdfVariant,
    client: ClientInfo,
) -> DownloadLink:
    contract = await session.get(Contract, contract_id)
    if contract is None:
        raise not_found()
    if variant is PdfVariant.signed:
        if contract.status != ContractStatus.signed.value or not contract.final_pdf_key:
            raise invalid_state(
                "Contract is not signed; no signed PDF exists.", {"status": contract.status}
            )
        key, sha256 = contract.final_pdf_key, contract.final_pdf_sha256 or ""
    else:
        key, sha256 = contract.original_pdf_key, contract.original_pdf_sha256
    ttl = settings.download_url_ttl_seconds
    filename = download_filename(contract.title, variant)
    url = storage.signed_download_url(key, ttl, filename)
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
    await record_event(
        session,
        contract_id=contract_id,
        event_type=EventType.pdf_downloaded,
        actor_type=ActorType.admin,
        actor_id=str(admin_id),
        metadata={"variant": variant.value, "sha256": sha256},
        client=client,
    )
    await session.commit()
    return DownloadLink(
        variant=variant, url=url, expires_at=expires_at, sha256=sha256, filename=filename
    )
