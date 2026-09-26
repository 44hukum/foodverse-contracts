"""Signing links: issue (send / re-send), open (view), and consume (sign).

State machine per SPEC.md §5; token rules per §7. Every status change here is
a conditional ``UPDATE ... WHERE status IN (...)`` under a row lock and writes
exactly one ``contract_events`` row in the same transaction (rule 8). The raw
token is never stored, logged, or put into an event; lookups and rate-limit
keys use ``sha256(token)`` (rule 6).

Why a used or cancelled link is 410 and a rotated one is 404: the signer's
``token_hash`` is kept after signing and cancelling (with
``token_invalidated_at`` set) so the link can be told apart from an unknown
one, while a re-send overwrites the hash so the old link becomes
indistinguishable from a token that never existed.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ApiError, internal_error, invalid_state, not_found
from app.models.contract import Contract, ContractStatus
from app.models.event import ActorType, EventType
from app.models.event import ContractEvent as ContractEventModel
from app.models.signer import Signer
from app.notify import Mailer, send_signed_copies, send_signing_link
from app.pdf import AuditEvent, CertificateDetails, PdfSigningError, sign_pdf
from app.pdf.image import decode_signature_png
from app.schemas.common import ErrorCode
from app.schemas.contracts import (
    DownloadLink,
    PdfVariant,
    SendContractRequest,
    SendContractResponse,
    SigningLink,
)
from app.schemas.public import (
    SIGNATURE_DATA_URL_PREFIX,
    PublicContract,
    PublicPdf,
    PublicSigner,
    SignatureResult,
    SubmitSignatureRequest,
)
from app.services import tokens
from app.services.consent import render_consent_text
from app.services.contracts import download_filename, get_contract
from app.services.events import ClientInfo, record_event
from app.services.storage import SIGNATURE_PNG, SIGNED_PDF, StorageBackend, contract_key

log = logging.getLogger(__name__)

SEND_ALLOWED_FROM = (
    ContractStatus.draft,
    ContractStatus.sent,
    ContractStatus.viewed,
    ContractStatus.expired,
)
RESEND_FROM = (ContractStatus.sent, ContractStatus.viewed)
OPEN_STATUSES = (ContractStatus.sent, ContractStatus.viewed)


def _values(statuses: tuple[ContractStatus, ...]) -> list[str]:
    return [s.value for s in statuses]


# --- admin: send / re-send ---------------------------------------------------------


async def send_link(
    session: AsyncSession,
    settings: Settings,
    mailer: Mailer,
    *,
    contract_id: uuid.UUID,
    admin_id: uuid.UUID,
    request: SendContractRequest,
    client: ClientInfo,
) -> SendContractResponse:
    """Issue a fresh token, invalidating any previous one, and move the contract to ``sent``.

    With ``send_email`` the link is then emailed to the signer; ``email_sent``
    reports whether the SMTP handoff succeeded. A failed email never undoes
    the send (the link is in the response either way) and is visible as a
    ``notification.failed`` event.
    """
    contract = (
        await session.execute(select(Contract).where(Contract.id == contract_id).with_for_update())
    ).scalar_one_or_none()
    if contract is None:
        raise not_found()
    signer = (
        await session.execute(select(Signer).where(Signer.contract_id == contract_id))
    ).scalar_one()
    if contract.anonymized_at is not None or signer.email is None or signer.name is None:
        await session.rollback()
        raise invalid_state(
            "Signer data was removed by the retention policy; this contract cannot be sent.",
            {"reason": "anonymized"},
        )
    from_status = contract.status
    if from_status not in _values(SEND_ALLOWED_FROM):
        await session.rollback()
        raise invalid_state(
            f"Contract cannot be sent from status '{from_status}'.",
            {"status": from_status, "allowed_from": _values(SEND_ALLOWED_FROM)},
        )

    days = tokens.link_ttl_days(settings, request.expires_in_days)
    token = tokens.generate_token()
    now = datetime.now(UTC)
    expires_at = tokens.expiry_for(days, now)
    updated = (
        (
            await session.execute(
                update(Contract)
                .where(Contract.id == contract_id, Contract.status.in_(_values(SEND_ALLOWED_FROM)))
                .values(
                    status=ContractStatus.sent.value,
                    sent_at=now,
                    expires_at=expires_at,
                    updated_at=now,
                )
                .returning(Contract.id)
            )
        )
        .scalars()
        .all()
    )
    if len(updated) != 1:  # pragma: no cover - guarded by the row lock above
        await session.rollback()
        raise invalid_state(
            "Contract cannot be sent from its current status.", {"status": from_status}
        )
    await session.execute(
        update(Signer)
        .where(Signer.id == signer.id)
        .values(
            token_hash=tokens.hash_token(token),
            token_created_at=now,
            token_invalidated_at=None,
            updated_at=now,
        )
    )
    resend = from_status in _values(RESEND_FROM)
    metadata: dict[str, Any] = {
        "from_status": from_status,
        "to_status": ContractStatus.sent.value,
        "delivery": "email" if request.send_email else "manual",
        "expires_in_days": days,
        "token_rotated": from_status != ContractStatus.draft.value,
    }
    await record_event(
        session,
        contract_id=contract_id,
        event_type=EventType.link_resent if resend else EventType.contract_sent,
        actor_type=ActorType.admin,
        actor_id=str(admin_id),
        metadata=metadata,
        client=client,
        occurred_at=now,
    )
    await session.commit()
    signing_url = tokens.signing_url(settings, token)
    email_sent = False
    if request.send_email:
        email_sent = await send_signing_link(
            session,
            settings,
            mailer,
            contract=contract,
            signer_name=signer.name,
            signer_email=signer.email,
            admin_id=admin_id,
            signing_url=signing_url,
            expires_at=expires_at,
            note=request.message,
        )
    detail = await get_contract(session, contract_id)
    return SendContractResponse(
        contract=detail,
        signing_link=SigningLink(url=signing_url, expires_at=expires_at),
        email_sent=email_sent,
    )


# --- token resolution shared by the public endpoints -----------------------------


async def _load_by_token(session: AsyncSession, token: str) -> tuple[Signer, Contract] | None:
    """The signer and (row-locked) contract behind a token, or None for anything unknown."""
    if not tokens.is_well_formed(token):
        return None
    signer = (
        await session.execute(select(Signer).where(Signer.token_hash == tokens.hash_token(token)))
    ).scalar_one_or_none()
    if signer is None:
        return None
    contract = (
        await session.execute(
            select(Contract).where(Contract.id == signer.contract_id).with_for_update()
        )
    ).scalar_one()
    return signer, contract


def _link_expired(expired_at: datetime | None) -> ApiError:
    details: dict[str, Any] = {}
    if expired_at is not None:
        details["expired_at"] = expired_at
    return ApiError(
        410,
        ErrorCode.link_expired,
        "This signing link has expired. Ask the sender for a new one.",
        details or None,
    )


def _link_used(signed_at: datetime | None) -> ApiError:
    details: dict[str, Any] = {}
    if signed_at is not None:
        details["signed_at"] = signed_at
    return ApiError(
        410, ErrorCode.link_used, "This document has already been signed.", details or None
    )


def _contract_cancelled() -> ApiError:
    return ApiError(
        410, ErrorCode.contract_cancelled, "This contract has been cancelled by the sender."
    )


async def _expire(session: AsyncSession, contract: Contract, now: datetime) -> None:
    """Lazy expiry (SPEC.md §5): ``sent``/``viewed`` -> ``expired`` plus one system event."""
    from_status = contract.status
    updated = (
        (
            await session.execute(
                update(Contract)
                .where(Contract.id == contract.id, Contract.status.in_(_values(OPEN_STATUSES)))
                .values(status=ContractStatus.expired.value, updated_at=now)
                .returning(Contract.id)
            )
        )
        .scalars()
        .all()
    )
    if len(updated) == 1:
        await record_event(
            session,
            contract_id=contract.id,
            event_type=EventType.contract_expired,
            actor_type=ActorType.system,
            actor_id=None,
            metadata={
                "from_status": from_status,
                "to_status": ContractStatus.expired.value,
                "expires_at": contract.expires_at.isoformat() if contract.expires_at else None,
            },
            occurred_at=now,
        )
    await session.commit()


async def _require_open(
    session: AsyncSession, signer: Signer, contract: Contract, now: datetime
) -> None:
    """Raise the contract's 404/410 unless the link can still be viewed and signed."""
    status = contract.status
    if status == ContractStatus.cancelled.value:
        raise _contract_cancelled()
    if status == ContractStatus.signed.value:
        raise _link_used(contract.signed_at)
    if signer.token_invalidated_at is not None or status not in _values(OPEN_STATUSES):
        # A token that was invalidated without a terminal status, or a live token on a
        # contract that never left draft, cannot arise through the API; fail closed.
        if status == ContractStatus.expired.value:
            raise _link_expired(contract.expires_at)
        raise not_found()
    if contract.expires_at is None or contract.expires_at <= now:
        await _expire(session, contract, now)
        raise _link_expired(contract.expires_at)


# --- signer: view ------------------------------------------------------------------


async def view_contract(
    session: AsyncSession,
    settings: Settings,
    storage: StorageBackend,
    *,
    token: str,
    client: ClientInfo,
) -> PublicContract:
    """``GET /public/sign/{token}``: metadata plus a short-lived PDF URL; marks ``viewed``."""
    loaded = await _load_by_token(session, token)
    if loaded is None:
        raise not_found()
    signer, contract = loaded
    now = datetime.now(UTC)
    await _require_open(session, signer, contract, now)
    from_status = contract.status
    if from_status == ContractStatus.sent.value:
        updated = (
            (
                await session.execute(
                    update(Contract)
                    .where(Contract.id == contract.id, Contract.status == ContractStatus.sent.value)
                    .values(status=ContractStatus.viewed.value, first_viewed_at=now, updated_at=now)
                    .returning(Contract.id)
                )
            )
            .scalars()
            .all()
        )
        if len(updated) != 1:  # pragma: no cover - guarded by the row lock
            await session.rollback()
            raise not_found()
    await record_event(
        session,
        contract_id=contract.id,
        event_type=EventType.link_viewed,
        actor_type=ActorType.signer,
        actor_id=str(signer.id),
        metadata={"from_status": from_status, "to_status": ContractStatus.viewed.value},
        client=client,
        occurred_at=now,
    )
    await session.commit()

    assert signer.name is not None and signer.email is not None  # checked by _require_open path
    assert contract.expires_at is not None
    ttl = settings.download_url_ttl_seconds
    url = storage.signed_download_url(
        contract.original_pdf_key, ttl, download_filename(contract.title, PdfVariant.original)
    )
    return PublicContract(
        contract_id=contract.id,
        title=contract.title,
        status=ContractStatus.viewed,
        signer=PublicSigner(name=signer.name, email=signer.email),
        sent_by=settings.org_display_name,
        expires_at=contract.expires_at,
        pdf=PublicPdf(
            url=url,
            expires_at=now + timedelta(seconds=ttl),
            sha256=contract.original_pdf_sha256,
            size=contract.original_pdf_size,
        ),
        consent_text=render_consent_text(settings, signer_name=signer.name, title=contract.title),
        consent_text_version=settings.consent_text_version,
    )


# --- signer: sign ------------------------------------------------------------------


def _field_error(field: str, message: str) -> ApiError:
    return ApiError(
        422,
        ErrorCode.validation_error,
        "One or more fields are invalid.",
        {"fields": [{"field": field, "message": message}]},
    )


def decode_signature_data_url(settings: Settings, data_url: str) -> bytes:
    """PNG bytes from the ``data:image/png;base64,...`` value, within the size limit."""
    if not data_url.startswith(SIGNATURE_DATA_URL_PREFIX):
        raise _field_error("signature_image", "Must be a PNG data URL.")
    try:
        raw = base64.b64decode(data_url[len(SIGNATURE_DATA_URL_PREFIX) :], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _field_error("signature_image", "Not valid base64.") from exc
    if len(raw) > settings.max_signature_png_bytes:
        raise ApiError(
            413,
            ErrorCode.payload_too_large,
            f"Signature image must be {settings.max_signature_png_bytes // 1024} KB or smaller.",
            {"max_bytes": settings.max_signature_png_bytes},
        )
    return raw


def clean_signature_png(raw: bytes) -> bytes:
    """Validate the PNG and return a re-encoded copy carrying only pixel data."""
    try:
        image = decode_signature_png(raw)
    except PdfSigningError as exc:
        raise _field_error("signature_image", str(exc)) from exc
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def retain_until_for(settings: Settings, term_end_date: date | None, signed_at: datetime) -> date:
    """``(term_end_date or signed_at::date) + RETENTION_SIGNED_YEARS_AFTER_TERM`` (SPEC.md §9)."""
    base = term_end_date or signed_at.date()
    years = settings.retention_signed_years_after_term
    try:
        return base.replace(year=base.year + years)
    except ValueError:  # 29 February
        return base.replace(year=base.year + years, day=28)


async def submit_signature(
    session: AsyncSession,
    settings: Settings,
    storage: StorageBackend,
    mailer: Mailer,
    *,
    token: str,
    body: SubmitSignatureRequest,
    client: ClientInfo,
) -> SignatureResult:
    """``POST /public/sign/{token}/signature``: SPEC.md §4 step 7, one unit of work.

    Nothing is stored unless every step succeeds: the stamped PDF and the
    signature PNG are written to storage first and removed again if the
    database transaction does not commit. The completion emails (step 8) go
    out only after the commit and cannot fail the request.
    """
    raw_png = decode_signature_data_url(settings, body.signature_image)
    if body.consent_text_version != settings.consent_text_version:
        raise _field_error(
            "consent_text_version",
            f"Consent text has changed; reload and accept version "
            f"'{settings.consent_text_version}'.",
        )
    loaded = await _load_by_token(session, token)
    if loaded is None:
        raise not_found()
    signer, contract = loaded
    now = datetime.now(UTC)
    await _require_open(session, signer, contract, now)
    assert signer.name is not None and signer.email is not None
    typed_name = body.typed_name.strip()
    if len(typed_name) < 2:
        raise _field_error("typed_name", "Enter your full name.")
    png = clean_signature_png(raw_png)

    original = await storage.get(contract.original_pdf_key)
    if hashlib.sha256(original).hexdigest() != contract.original_pdf_sha256:
        raise internal_error(f"original PDF hash mismatch for contract {contract.id}")

    existing = (
        (
            await session.execute(
                select(ContractEventModel)
                .where(ContractEventModel.contract_id == contract.id)
                .order_by(ContractEventModel.id)
            )
        )
        .scalars()
        .all()
    )
    trail = [AuditEvent(e.event_type, e.actor_type, e.occurred_at) for e in existing]
    trail.append(AuditEvent(EventType.contract_signed.value, ActorType.signer.value, now))
    consent_text = render_consent_text(settings, signer_name=signer.name, title=contract.title)
    certificate = CertificateDetails(
        contract_id=str(contract.id),
        title=contract.title,
        signer_name=signer.name,
        signer_email=signer.email,
        signed_at=now,
        consent_text=consent_text,
        consent_text_version=settings.consent_text_version,
        link_sent_at=contract.sent_at,
        link_expires_at=contract.expires_at,
        signer_ip=client.ip,
        signer_user_agent=client.user_agent,
    )
    try:
        signed = await asyncio.to_thread(
            sign_pdf,
            original,
            png,
            typed_name,
            trail,
            certificate,
            display_timezone=settings.display_timezone,
            certificate_text_version=settings.certificate_text_version,
        )
    except PdfSigningError as exc:
        raise internal_error(f"contract {contract.id} could not be stamped: {exc}") from exc

    from_status = contract.status
    signed_key = contract_key(contract.id, SIGNED_PDF)
    png_key = contract_key(contract.id, SIGNATURE_PNG)
    await storage.put(signed_key, signed.pdf_bytes, "application/pdf")
    await storage.put(png_key, png, "image/png")
    try:
        updated = (
            (
                await session.execute(
                    update(Contract)
                    .where(Contract.id == contract.id, Contract.status.in_(_values(OPEN_STATUSES)))
                    .values(
                        status=ContractStatus.signed.value,
                        signed_at=now,
                        final_pdf_key=signed_key,
                        final_pdf_sha256=signed.sha256_hex,
                        retain_until=retain_until_for(settings, contract.term_end_date, now),
                        updated_at=now,
                    )
                    .returning(Contract.id)
                )
            )
            .scalars()
            .all()
        )
        if len(updated) != 1:  # pragma: no cover - guarded by the row lock
            raise _link_used(None)
        await session.execute(
            update(Signer)
            .where(Signer.id == signer.id)
            .values(
                typed_name=typed_name,
                signature_image_key=png_key,
                consent_given_at=now,
                consent_text_version=settings.consent_text_version,
                signed_ip=client.ip,
                signed_user_agent=client.user_agent,
                token_invalidated_at=now,
                updated_at=now,
            )
        )
        await record_event(
            session,
            contract_id=contract.id,
            event_type=EventType.contract_signed,
            actor_type=ActorType.signer,
            actor_id=str(signer.id),
            metadata={
                "from_status": from_status,
                "to_status": ContractStatus.signed.value,
                "final_pdf_sha256": signed.sha256_hex,
                "page_count": signed.page_count,
                "signature_on_new_page": signed.signature_on_new_page,
                "consent_text_version": settings.consent_text_version,
                "certificate_text_version": settings.certificate_text_version,
            },
            client=client,
            occurred_at=now,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        await storage.delete(signed_key)
        await storage.delete(png_key)
        raise

    await send_signed_copies(
        session,
        settings,
        storage,
        mailer,
        contract=contract,
        signer=signer,
        pdf_key=signed_key,
        pdf_bytes=signed.pdf_bytes,
        sha256=signed.sha256_hex,
        signed_at=now,
    )

    ttl = settings.download_url_ttl_seconds
    filename = download_filename(contract.title, PdfVariant.signed)
    return SignatureResult(
        contract_id=contract.id,
        status=ContractStatus.signed,
        signed_at=now,
        final_pdf_sha256=signed.sha256_hex,
        download=DownloadLink(
            variant=PdfVariant.signed,
            url=storage.signed_download_url(signed_key, ttl, filename),
            expires_at=now + timedelta(seconds=ttl),
            sha256=signed.sha256_hex,
            filename=filename,
        ),
    )
