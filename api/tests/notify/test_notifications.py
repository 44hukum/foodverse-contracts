"""Notifications through the HTTP surface: send emails the link, signing emails the copies.

Everything lands in the in-memory outbox from the root conftest. The only
place the raw token may appear is the signer's email; every assertion about
events checks it (and every address) stays out of ``metadata``.
"""

from __future__ import annotations

import hashlib
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Admin
from app.notify import InMemoryMailer
from app.services.events import FORBIDDEN_METADATA_KEYS
from tests.conftest import create_contract_via_api
from tests.pdf.conftest import make_pdf
from tests.test_signing import SIGNER_HEADERS, create_and_send, events_of, iso, signature_body

SIGNER_EMAIL = "maria@hotel-aurora.example"


def body_of(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain",))
    assert part is not None
    return part.get_content()


def notification_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if e["event_type"].startswith("notification.")]


def assert_clean(event: dict[str, Any], *secrets: str) -> None:
    """No personal data or token in the audit row, and no PII side row for system mail."""
    assert not FORBIDDEN_METADATA_KEYS & set(event["metadata"])
    blob = str(event["metadata"])
    for secret in (SIGNER_EMAIL, "example.com", *secrets):
        assert secret not in blob
    assert event["ip"] is None and event["user_agent"] is None


# --- signing link ---------------------------------------------------------------------


async def test_send_emails_the_link_to_the_signer_and_records_notification_sent(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    admin: Admin,
    mailer: InMemoryMailer,
    settings: Settings,
) -> None:
    created = await create_contract_via_api(client, auth_headers, title="Hotel Aurora 2026")
    resp = await client.post(
        f"/admin/contracts/{created['id']}/send",
        headers=auth_headers,
        json={"message": "Please sign by Friday."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email_sent"] is True
    link = body["signing_link"]["url"]
    token = link.rsplit("/", 1)[-1]

    (message,) = mailer.outbox
    assert message["To"] == f"Maria Petrova <{SIGNER_EMAIL}>"
    assert message["From"] == settings.email_from
    assert message["Subject"] == (
        f'{settings.org_display_name}: "Hotel Aurora 2026" is ready for your signature'
    )
    text = body_of(message)
    assert f"  {link}\n" in text
    assert "Message from Test Admin:\n  Please sign by Friday." in text
    expires_at = iso(body["signing_link"]["expires_at"])
    assert expires_at.strftime("%Y-%m-%d %H:%M:%S UTC") in text
    assert "NPT (Asia/Kathmandu, UTC+05:45)" in text
    assert list(message.iter_attachments()) == []

    events = body["contract"]["events"]
    assert [e["event_type"] for e in events] == [
        "contract.created",
        "contract.sent",
        "notification.sent",
    ]
    note = events[-1]
    assert note["actor_type"] == "admin" and note["actor_id"] == str(admin.id)
    assert note["metadata"] == {
        "notification": "signing_link",
        "recipient": "signer",
        "delivery": "link",
        "message_id": str(message["Message-ID"]),
        "attempts": 1,
    }
    assert_clean(note, token, "Please sign")


async def test_send_email_false_sends_nothing_and_writes_no_notification_event(
    client: httpx.AsyncClient, auth_headers: dict[str, str], mailer: InMemoryMailer
) -> None:
    created = await create_contract_via_api(client, auth_headers)
    resp = await client.post(
        f"/admin/contracts/{created['id']}/send", headers=auth_headers, json={"send_email": False}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["email_sent"] is False
    assert mailer.outbox == []
    assert notification_events(resp.json()["contract"]["events"]) == []


async def test_resend_emails_the_new_link_only(
    client: httpx.AsyncClient, auth_headers: dict[str, str], mailer: InMemoryMailer
) -> None:
    first, old_token = await create_and_send(client, auth_headers)
    resp = await client.post(
        f"/admin/contracts/{first['contract']['id']}/send", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    new_link = resp.json()["signing_link"]["url"]
    assert len(mailer.outbox) == 2
    second = body_of(mailer.outbox[1])
    assert new_link in second and old_token not in second
    assert [e["event_type"] for e in resp.json()["contract"]["events"]] == [
        "contract.created",
        "contract.sent",
        "notification.sent",
        "link.resent",
        "notification.sent",
    ]


async def test_send_still_succeeds_when_every_smtp_attempt_fails(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    mailer: InMemoryMailer,
    settings: Settings,
    session: AsyncSession,
) -> None:
    attempts = settings.email_send_attempts
    mailer.failures = [smtplib.SMTPConnectError(421, b"busy")] * attempts
    created = await create_contract_via_api(client, auth_headers)
    resp = await client.post(f"/admin/contracts/{created['id']}/send", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email_sent"] is False
    assert body["signing_link"]["url"]  # the admin can still share the link by hand
    assert body["contract"]["status"] == "sent"
    assert body["contract"]["signer"]["has_active_link"] is True
    assert mailer.outbox == [] and mailer.failures == []

    failed = body["contract"]["events"][-1]
    assert failed["event_type"] == "notification.failed"
    assert failed["metadata"] == {
        "notification": "signing_link",
        "recipient": "signer",
        "delivery": "link",
        "message_id": failed["metadata"]["message_id"],
        "attempts": attempts,
        "error": "SMTPConnectError",
    }
    assert failed["metadata"]["message_id"].startswith("<")
    assert_clean(failed, body["signing_link"]["url"].rsplit("/", 1)[-1])
    # the failure is not sticky: the next send goes out
    again = await client.post(f"/admin/contracts/{created['id']}/send", headers=auth_headers)
    assert again.json()["email_sent"] is True
    assert len(mailer.outbox) == 1


async def test_transient_smtp_failure_is_retried_within_the_request(
    client: httpx.AsyncClient, auth_headers: dict[str, str], mailer: InMemoryMailer
) -> None:
    mailer.failures = [OSError("connection reset")]
    created = await create_contract_via_api(client, auth_headers)
    resp = await client.post(f"/admin/contracts/{created['id']}/send", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["email_sent"] is True
    assert len(mailer.outbox) == 1
    sent = resp.json()["contract"]["events"][-1]
    assert sent["event_type"] == "notification.sent"
    assert sent["metadata"]["attempts"] == 2
    assert "error" not in sent["metadata"]


async def test_send_attempts_setting_has_a_floor_of_one(mailer: InMemoryMailer) -> None:
    import pytest

    with pytest.raises(ValueError, match="EMAIL_SEND_ATTEMPTS"):
        Settings(email_send_attempts=0)


# --- signed copies --------------------------------------------------------------------


async def test_signing_emails_the_signed_pdf_to_signer_and_admin(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    admin: Admin,
    mailer: InMemoryMailer,
    settings: Settings,
) -> None:
    sent, token = await create_and_send(client, auth_headers, title="Hotel Aurora 2026")
    contract_id = sent["contract"]["id"]
    assert (await client.get(f"/public/sign/{token}", headers=SIGNER_HEADERS)).status_code == 200
    resp = await client.post(
        f"/public/sign/{token}/signature", headers=SIGNER_HEADERS, json=signature_body()
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    sha256 = result["final_pdf_sha256"]
    signed_at = iso(result["signed_at"])

    _link_mail, signer_mail, admin_mail = mailer.outbox
    assert signer_mail["To"] == f"Maria Petrova <{SIGNER_EMAIL}>"
    assert admin_mail["To"] == f"{admin.name} <{admin.email}>"
    assert signer_mail["Subject"] == 'Signed: "Hotel Aurora 2026"'
    assert admin_mail["Subject"] == 'Signed by Maria Petrova: "Hotel Aurora 2026"'
    for message in (signer_mail, admin_mail):
        text = body_of(message)
        assert f"  {sha256}\n" in text
        assert signed_at.strftime("%Y-%m-%d %H:%M:%S UTC") in text
        assert "NPT (Asia/Kathmandu, UTC+05:45)" in text
        assert "is attached (hotel-aurora-2026-signed.pdf" in text
        assert token not in text
        (attachment,) = message.iter_attachments()
        assert attachment.get_content_type() == "application/pdf"
        assert attachment.get_filename() == "hotel-aurora-2026-signed.pdf"
        assert hashlib.sha256(attachment.get_content()).hexdigest() == sha256
    admin_page = f"{settings.web_base_url}/contracts/{contract_id}"
    assert admin_page in body_of(admin_mail)
    assert admin_page not in body_of(signer_mail)

    events = await events_of(client, auth_headers, contract_id)
    assert [e["event_type"] for e in events] == [
        "contract.created",
        "contract.sent",
        "notification.sent",
        "link.viewed",
        "contract.signed",
        "notification.sent",
        "notification.sent",
    ]
    for event, recipient, message in zip(
        events[-2:], ("signer", "admin"), (signer_mail, admin_mail), strict=True
    ):
        assert event["actor_type"] == "system" and event["actor_id"] is None
        assert event["metadata"] == {
            "notification": "signed_copy",
            "recipient": recipient,
            "delivery": "attachment",
            "message_id": str(message["Message-ID"]),
            "attempts": 1,
        }
        assert_clean(event, token, admin.email, "Maria")


async def test_oversized_signed_pdf_is_sent_as_a_download_link(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    mailer: InMemoryMailer,
    settings: Settings,
) -> None:
    settings.email_max_attachment_bytes = 1024  # a stamped PDF is far larger
    sent, token = await create_and_send(client, auth_headers, pdf=make_pdf(2))
    before = datetime.now(UTC)
    resp = await client.post(f"/public/sign/{token}/signature", json=signature_body())
    assert resp.status_code == 200, resp.text
    sha256 = resp.json()["final_pdf_sha256"]

    _, signer_mail, admin_mail = mailer.outbox
    for message in (signer_mail, admin_mail):
        assert list(message.iter_attachments()) == []
        text = body_of(message)
        assert "is too large to attach" in text
        assert f"  {sha256}\n" in text
        url = next(line.strip() for line in text.splitlines() if "/_storage/local/" in line)
        assert token not in url
        download = await client.get(url)
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/pdf"
        assert hashlib.sha256(download.content).hexdigest() == sha256
        exp = int(httpx.URL(url).params["exp"])
        ttl = timedelta(hours=settings.email_download_link_ttl_hours)
        lifetime = datetime.fromtimestamp(exp, UTC) - before
        assert ttl - timedelta(seconds=5) <= lifetime <= ttl + timedelta(seconds=5)
        assert (before + ttl).strftime("%Y-%m-%d %H:%M") in text

    events = await events_of(client, auth_headers, sent["contract"]["id"])
    assert [e["metadata"]["delivery"] for e in notification_events(events)] == [
        "link",
        "link",
        "link",
    ]
    assert [e["metadata"]["recipient"] for e in notification_events(events)] == [
        "signer",
        "signer",
        "admin",
    ]


async def test_signature_stands_when_completion_emails_fail(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    mailer: InMemoryMailer,
    settings: Settings,
) -> None:
    sent, token = await create_and_send(client, auth_headers)
    contract_id = sent["contract"]["id"]
    # both recipients, every attempt
    mailer.failures = [smtplib.SMTPServerDisconnected("gone")] * (2 * settings.email_send_attempts)
    resp = await client.post(f"/public/sign/{token}/signature", json=signature_body())
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "signed"
    assert mailer.failures == [] and len(mailer.outbox) == 1  # only the earlier link email

    detail = (await client.get(f"/admin/contracts/{contract_id}", headers=auth_headers)).json()
    assert detail["status"] == "signed"
    assert detail["final_pdf_sha256"] == resp.json()["final_pdf_sha256"]
    failed = [e for e in detail["events"] if e["event_type"] == "notification.failed"]
    assert [e["metadata"]["recipient"] for e in failed] == ["signer", "admin"]
    for event in failed:
        assert event["metadata"]["notification"] == "signed_copy"
        assert event["metadata"]["delivery"] == "attachment"
        assert event["metadata"]["attempts"] == settings.email_send_attempts
        assert event["metadata"]["error"] == "SMTPServerDisconnected"
        assert_clean(event, token)
    # the admin can still fetch the signed copy and forward it by hand
    download = await client.get(
        f"/admin/contracts/{contract_id}/download",
        headers=auth_headers,
        params={"variant": "signed"},
    )
    assert download.status_code == 200


async def test_one_failed_recipient_does_not_block_the_other(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    mailer: InMemoryMailer,
    settings: Settings,
) -> None:
    sent, token = await create_and_send(client, auth_headers)
    mailer.failures = [OSError("refused")] * settings.email_send_attempts  # the signer's copy
    resp = await client.post(f"/public/sign/{token}/signature", json=signature_body())
    assert resp.status_code == 200, resp.text
    assert len(mailer.outbox) == 2  # link email + the admin's copy
    assert "Signed by" in str(mailer.outbox[-1]["Subject"])
    events = notification_events(await events_of(client, auth_headers, sent["contract"]["id"]))
    assert [(e["event_type"], e["metadata"]["recipient"]) for e in events] == [
        ("notification.sent", "signer"),
        ("notification.failed", "signer"),
        ("notification.sent", "admin"),
    ]
