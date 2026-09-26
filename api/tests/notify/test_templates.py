"""The email bodies: both timezones, the link, the hash, attachment or link, admin page."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import pytest

from app.config import Settings
from app.models import Contract
from app.notify import DeliveryMode, SignedCopy, admin_contract_url, signed_copy_for
from app.notify.templates import (
    signed_copy_email_to_admin,
    signed_copy_email_to_signer,
    signing_link_email,
)
from app.services.storage import MAX_URL_TTL_SECONDS

SIGNED_AT = datetime(2026, 9, 28, 14, 22, 10, tzinfo=UTC)
EXPIRES_AT = datetime(2026, 10, 4, 3, 0, 0, tzinfo=UTC)
SHA = "ab" * 32
LINK = "http://localhost:5173/sign/" + "t" * 43
CONTRACT_ID = uuid.UUID("0f8fad5b-d9cb-469f-a165-70867728950e")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        local_storage_dir=str(tmp_path / "storage"),
        org_display_name="Foodverse Nepal",
        email_from="Foodverse Contracts <contracts@foodverse.example>",
        web_base_url="https://contracts.example/",
    )


def body_of(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain",))
    assert part is not None
    return part.get_content()


def attachments_of(message: EmailMessage) -> list[EmailMessage]:
    return list(message.iter_attachments())


def copy_attached(pdf: bytes = b"%PDF-1.4 signed") -> SignedCopy:
    return SignedCopy(filename="hotel-signed.pdf", sha256=SHA, size=len(pdf), pdf_bytes=pdf)


def copy_linked() -> SignedCopy:
    return SignedCopy(
        filename="hotel-signed.pdf",
        sha256=SHA,
        size=12 * 1024 * 1024,
        download_url="http://localhost:8000/_storage/local/contracts/x/signed.pdf?exp=1&sig=2",
        download_expires_at=SIGNED_AT + timedelta(hours=72),
    )


def test_signing_link_email_carries_link_expiry_sender_and_note(settings: Settings) -> None:
    message = signing_link_email(
        settings,
        signer_name="Maria Petrova",
        signer_email="maria@hotel-aurora.example",
        title="Hotel Aurora Onboarding 2026",
        signing_url=LINK,
        expires_at=EXPIRES_AT,
        sender_name="Ops Admin",
        note="Please sign by Friday.\nCall me with questions.",
    )
    assert message["To"] == "Maria Petrova <maria@hotel-aurora.example>"
    assert message["From"] == "Foodverse Contracts <contracts@foodverse.example>"
    assert message["Subject"] == (
        'Foodverse Nepal: "Hotel Aurora Onboarding 2026" is ready for your signature'
    )
    assert str(message["Message-ID"]).endswith("@foodverse.example>")
    assert message["Date"] is not None
    body = body_of(message)
    assert "Hello Maria Petrova," in body
    assert "Foodverse Nepal has sent you a document" in body
    assert f"  {LINK}\n" in body
    assert "2026-10-04 08:45:00 NPT (Asia/Kathmandu, UTC+05:45)" in body
    assert "2026-10-04 03:00:00 UTC" in body
    assert "Message from Ops Admin:\n  Please sign by Friday.\n  Call me with questions." in body
    assert attachments_of(message) == []


def test_signing_link_email_without_note_or_sender(settings: Settings) -> None:
    message = signing_link_email(
        settings,
        signer_name="Maria",
        signer_email="maria@example.com",
        title="T",
        signing_url=LINK,
        expires_at=EXPIRES_AT,
        sender_name=None,
        note=None,
    )
    assert "Message from" not in body_of(message)


def test_signer_copy_attaches_pdf_and_prints_hash_and_both_times(settings: Settings) -> None:
    pdf = b"%PDF-1.4 signed bytes"
    message = signed_copy_email_to_signer(
        settings,
        signer_name="Maria Petrova",
        signer_email="maria@hotel-aurora.example",
        title="Hotel Aurora Onboarding 2026",
        signed_at=SIGNED_AT,
        copy=copy_attached(pdf),
    )
    assert message["Subject"] == 'Signed: "Hotel Aurora Onboarding 2026"'
    body = body_of(message)
    assert f"  {SHA}\n" in body
    assert "2026-09-28 20:07:10 NPT (Asia/Kathmandu, UTC+05:45)" in body
    assert "2026-09-28 14:22:10 UTC" in body
    assert "The signed PDF is attached (hotel-signed.pdf, 21 bytes)." in body
    assert "/contracts/" not in body  # the admin page is for admins only
    (attachment,) = attachments_of(message)
    assert attachment.get_content_type() == "application/pdf"
    assert attachment.get_filename() == "hotel-signed.pdf"
    assert attachment.get_content() == pdf


def test_admin_copy_links_to_contract_page_and_names_signer(settings: Settings) -> None:
    message = signed_copy_email_to_admin(
        settings,
        admin_name="Ops Admin",
        admin_email="ops@example.com",
        signer_name="Maria Petrova",
        title="Hotel Aurora Onboarding 2026",
        contract_id=CONTRACT_ID,
        signed_at=SIGNED_AT,
        copy=copy_attached(),
    )
    assert message["To"] == "Ops Admin <ops@example.com>"
    assert message["Subject"] == 'Signed by Maria Petrova: "Hotel Aurora Onboarding 2026"'
    body = body_of(message)
    assert 'Maria Petrova has signed "Hotel Aurora Onboarding 2026".' in body
    assert f"  https://contracts.example/contracts/{CONTRACT_ID}\n" in body
    assert admin_contract_url(settings, CONTRACT_ID) == (
        f"https://contracts.example/contracts/{CONTRACT_ID}"
    )
    assert len(attachments_of(message)) == 1


def test_oversized_copy_carries_link_and_its_expiry_instead_of_attachment(
    settings: Settings,
) -> None:
    copy = copy_linked()
    assert copy.mode is DeliveryMode.link
    for message in (
        signed_copy_email_to_signer(
            settings,
            signer_name="Maria",
            signer_email="maria@example.com",
            title="T",
            signed_at=SIGNED_AT,
            copy=copy,
        ),
        signed_copy_email_to_admin(
            settings,
            admin_name="Ops",
            admin_email="ops@example.com",
            signer_name="Maria",
            title="T",
            contract_id=CONTRACT_ID,
            signed_at=SIGNED_AT,
            copy=copy,
        ),
    ):
        body = body_of(message)
        assert attachments_of(message) == []
        assert "(12.0 MB) is too large to attach" in body
        assert f"  {copy.download_url}\n" in body
        assert "2026-10-01 20:07:10 NPT (Asia/Kathmandu, UTC+05:45)" in body
        assert "2026-10-01 14:22:10 UTC" in body
        assert f"  {SHA}\n" in body


class _UrlRecorder:
    """Enough of a storage backend to see which key and ttl the link was minted with."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str | None]] = []

    def signed_download_url(self, key: str, ttl_seconds: int, filename: str | None = None) -> str:
        self.calls.append((key, ttl_seconds, filename))
        return f"https://bucket.example/{key}?ttl={ttl_seconds}"


def _contract(title: str = "Hotel Aurora Onboarding 2026") -> Contract:
    """A detached row; nothing here touches the database."""
    return Contract(
        id=CONTRACT_ID,
        title=title,
        status="signed",
        created_by=uuid.uuid4(),
        original_pdf_key=f"contracts/{CONTRACT_ID}/original.pdf",
        original_pdf_sha256="0" * 64,
        original_pdf_size=1,
    )


def test_signed_copy_for_attaches_at_the_limit_and_links_above_it(settings: Settings) -> None:
    storage = _UrlRecorder()
    settings.email_max_attachment_bytes = 16
    at_limit = signed_copy_for(
        settings,
        storage,  # type: ignore[arg-type]
        contract=_contract(),
        pdf_key=f"contracts/{CONTRACT_ID}/signed.pdf",
        pdf_bytes=b"x" * 16,
        sha256=SHA,
        now=SIGNED_AT,
    )
    assert at_limit.mode is DeliveryMode.attachment
    assert at_limit.filename == "hotel-aurora-onboarding-2026-signed.pdf"
    assert storage.calls == []

    above = signed_copy_for(
        settings,
        storage,  # type: ignore[arg-type]
        contract=_contract(),
        pdf_key=f"contracts/{CONTRACT_ID}/signed.pdf",
        pdf_bytes=b"x" * 17,
        sha256=SHA,
        now=SIGNED_AT,
    )
    assert above.mode is DeliveryMode.link
    assert above.pdf_bytes is None
    ttl = settings.email_download_link_ttl_hours * 3600
    assert storage.calls == [
        (f"contracts/{CONTRACT_ID}/signed.pdf", ttl, "hotel-aurora-onboarding-2026-signed.pdf")
    ]
    assert (
        above.download_url == f"https://bucket.example/contracts/{CONTRACT_ID}/signed.pdf?ttl={ttl}"
    )
    assert above.download_expires_at == SIGNED_AT + timedelta(seconds=ttl)


def test_signed_copy_link_ttl_never_exceeds_the_storage_ceiling(settings: Settings) -> None:
    storage = _UrlRecorder()
    settings.email_max_attachment_bytes = 0
    settings.email_download_link_ttl_hours = 24 * 30
    copy = signed_copy_for(
        settings,
        storage,  # type: ignore[arg-type]
        contract=_contract(),
        pdf_key=f"contracts/{CONTRACT_ID}/signed.pdf",
        pdf_bytes=b"x",
        sha256=SHA,
        now=SIGNED_AT,
    )
    assert storage.calls[0][1] == MAX_URL_TTL_SECONDS
    assert copy.download_expires_at == SIGNED_AT + timedelta(seconds=MAX_URL_TTL_SECONDS)
