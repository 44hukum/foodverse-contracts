"""Notification use cases: the signing-link email and the two signed-copy emails.

Every attempt ends in exactly one ``notification.sent`` or
``notification.failed`` event (SPEC.md §10) whose metadata names the
recipient role, the delivery mode, the message id, and the attempt count,
never an address. A send is retried up to ``EMAIL_SEND_ATTEMPTS`` times in a
row before it is recorded as failed; nothing here raises to the caller, so an
SMTP outage can never roll back a signature or a send (§12, decision 7).

Logging: contract id, recipient role, and the exception class only. Neither
the message (it carries the raw token, rule 6) nor the address (rule 1's
spirit for the log) is ever written out.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.admin import Admin
from app.models.contract import Contract
from app.models.event import ActorType, EventType
from app.models.signer import Signer
from app.notify.mailer import Mailer
from app.notify.templates import (
    DeliveryMode,
    Recipient,
    SignedCopy,
    signed_copy_email_to_admin,
    signed_copy_email_to_signer,
    signing_link_email,
)
from app.schemas.contracts import PdfVariant
from app.services.contracts import download_filename
from app.services.events import record_event
from app.services.storage import MAX_URL_TTL_SECONDS, StorageBackend

log = logging.getLogger(__name__)

# Pause between attempts, multiplied by the attempt number. Short on purpose:
# the retries run inside the request that triggered the notification.
RETRY_BACKOFF_SECONDS = 0.5


class Notification(enum.StrEnum):
    signing_link = "signing_link"
    signed_copy = "signed_copy"


async def _deliver(
    mailer: Mailer, message: EmailMessage, attempts: int
) -> tuple[bool, int, str | None]:
    """Try ``attempts`` times; return (sent, attempts used, last exception class)."""
    error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            await mailer.send(message)
        except Exception as exc:  # any transport failure is a failed attempt
            error = type(exc).__name__
            if attempt < attempts:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
            continue
        return True, attempt, None
    return False, attempts, error


async def _record(
    session: AsyncSession,
    *,
    contract_id: uuid.UUID,
    sent: bool,
    notification: Notification,
    recipient: Recipient,
    delivery: DeliveryMode,
    message_id: str | None,
    attempts: int,
    error: str | None,
    actor_type: ActorType,
    actor_id: str | None,
) -> None:
    metadata: dict[str, Any] = {
        "notification": notification.value,
        "recipient": recipient.value,
        "delivery": delivery.value,
        "message_id": message_id,
        "attempts": attempts,
    }
    if error is not None:
        metadata["error"] = error
    try:
        await record_event(
            session,
            contract_id=contract_id,
            event_type=EventType.notification_sent if sent else EventType.notification_failed,
            actor_type=actor_type,
            actor_id=actor_id,
            metadata=metadata,
        )
        await session.commit()
    except Exception:
        log.exception(
            "could not record notification event contract=%s notification=%s recipient=%s",
            contract_id,
            notification.value,
            recipient.value,
        )
        await session.rollback()


async def _notify(
    session: AsyncSession,
    settings: Settings,
    mailer: Mailer,
    *,
    contract_id: uuid.UUID,
    notification: Notification,
    recipient: Recipient,
    delivery: DeliveryMode,
    build: Callable[[], EmailMessage],
    actor_type: ActorType = ActorType.system,
    actor_id: str | None = None,
) -> bool:
    """Build, deliver with retries, and record; True when the transport accepted the mail."""
    message_id: str | None = None
    try:
        message = build()
        message_id = str(message["Message-ID"])
        sent, attempts, error = await _deliver(mailer, message, settings.email_send_attempts)
    except Exception as exc:  # a template or storage failure must not propagate
        sent, attempts, error = False, 0, type(exc).__name__
        log.exception(
            "notification could not be built contract=%s notification=%s recipient=%s",
            contract_id,
            notification.value,
            recipient.value,
        )
    if not sent:
        log.warning(
            "notification failed contract=%s notification=%s recipient=%s attempts=%d error=%s",
            contract_id,
            notification.value,
            recipient.value,
            attempts,
            error,
        )
    await _record(
        session,
        contract_id=contract_id,
        sent=sent,
        notification=notification,
        recipient=recipient,
        delivery=delivery,
        message_id=message_id,
        attempts=attempts,
        error=error,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    return sent


# --- use cases ---------------------------------------------------------------------


async def send_signing_link(
    session: AsyncSession,
    settings: Settings,
    mailer: Mailer,
    *,
    contract: Contract,
    signer_name: str,
    signer_email: str,
    admin_id: uuid.UUID,
    signing_url: str,
    expires_at: datetime,
    note: str | None,
) -> bool:
    """Email the signing link to the signer after a send or re-send. Never raises."""
    try:
        admin = await session.get(Admin, admin_id)
        sender_name = admin.name if admin is not None else None
    except Exception:  # the name is decoration; the link must still go out
        log.exception("could not load sender for contract=%s", contract.id)
        sender_name = None
    return await _notify(
        session,
        settings,
        mailer,
        contract_id=contract.id,
        notification=Notification.signing_link,
        recipient=Recipient.signer,
        delivery=DeliveryMode.link,
        build=lambda: signing_link_email(
            settings,
            signer_name=signer_name,
            signer_email=signer_email,
            title=contract.title,
            signing_url=signing_url,
            expires_at=expires_at,
            sender_name=sender_name,
            note=note,
        ),
        actor_type=ActorType.admin,
        actor_id=str(admin_id),
    )


def signed_copy_for(
    settings: Settings,
    storage: StorageBackend,
    *,
    contract: Contract,
    pdf_key: str,
    pdf_bytes: bytes,
    sha256: str,
    now: datetime,
) -> SignedCopy:
    """Attach the PDF when it fits ``EMAIL_MAX_ATTACHMENT_BYTES``; otherwise a pre-signed link."""
    filename = download_filename(contract.title, PdfVariant.signed)
    size = len(pdf_bytes)
    if size <= settings.email_max_attachment_bytes:
        return SignedCopy(filename=filename, sha256=sha256, size=size, pdf_bytes=pdf_bytes)
    ttl = min(settings.email_download_link_ttl_hours * 3600, MAX_URL_TTL_SECONDS)
    return SignedCopy(
        filename=filename,
        sha256=sha256,
        size=size,
        download_url=storage.signed_download_url(pdf_key, ttl, filename),
        download_expires_at=now + timedelta(seconds=ttl),
    )


async def send_signed_copies(
    session: AsyncSession,
    settings: Settings,
    storage: StorageBackend,
    mailer: Mailer,
    *,
    contract: Contract,
    signer: Signer,
    pdf_key: str,
    pdf_bytes: bytes,
    sha256: str,
    signed_at: datetime,
) -> None:
    """SPEC.md §4 step 8: the signed PDF (or link) to the signer and to the creating admin.

    Runs after the signature has been committed and never raises; each
    recipient gets its own event so a failure on one side is visible on its own.
    """
    signer_name, signer_email = signer.name, signer.email
    if signer_name is None or signer_email is None:  # pragma: no cover - signing requires both
        log.error("signed contract=%s has no signer contact; no copies sent", contract.id)
        return
    try:
        admin = await session.get(Admin, contract.created_by)
    except Exception:  # the signer's copy must still go out
        log.exception("could not load creating admin for contract=%s", contract.id)
        admin = None
    copy: SignedCopy | None = None

    def build_copy() -> SignedCopy:
        nonlocal copy
        if copy is None:
            copy = signed_copy_for(
                settings,
                storage,
                contract=contract,
                pdf_key=pdf_key,
                pdf_bytes=pdf_bytes,
                sha256=sha256,
                now=signed_at,
            )
        return copy

    expected_mode = (
        DeliveryMode.attachment
        if len(pdf_bytes) <= settings.email_max_attachment_bytes
        else DeliveryMode.link
    )
    await _notify(
        session,
        settings,
        mailer,
        contract_id=contract.id,
        notification=Notification.signed_copy,
        recipient=Recipient.signer,
        delivery=expected_mode,
        build=lambda: signed_copy_email_to_signer(
            settings,
            signer_name=signer_name,
            signer_email=signer_email,
            title=contract.title,
            signed_at=signed_at,
            copy=build_copy(),
        ),
    )
    if admin is None:
        log.error("contract=%s has no creating admin row; admin copy not sent", contract.id)
        return
    creator = admin
    await _notify(
        session,
        settings,
        mailer,
        contract_id=contract.id,
        notification=Notification.signed_copy,
        recipient=Recipient.admin,
        delivery=expected_mode,
        build=lambda: signed_copy_email_to_admin(
            settings,
            admin_name=creator.name,
            admin_email=creator.email,
            signer_name=signer_name,
            title=contract.title,
            contract_id=contract.id,
            signed_at=signed_at,
            copy=build_copy(),
        ),
    )


__all__ = [
    "RETRY_BACKOFF_SECONDS",
    "Notification",
    "send_signed_copies",
    "send_signing_link",
    "signed_copy_for",
]
