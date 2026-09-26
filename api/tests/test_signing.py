"""Signing links end to end: send, view, sign, expire, reuse, unknown, tampered.

Runs through the HTTP surface (admin send, public get, public signature) against
the real test database and the local storage backend. No token ever reaches a
fixture or an assertion message beyond the response that legitimately carries it.
"""

from __future__ import annotations

import base64
import hashlib
import unicodedata
import uuid
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Admin
from app.services.events import FORBIDDEN_METADATA_KEYS
from app.services.tokens import hash_token
from tests.conftest import PDF_BYTES, create_contract_via_api, set_status
from tests.pdf.conftest import make_pdf, make_signature_png

SIGNER_IP = "203.0.113.9"
SIGNER_UA = "Mozilla/5.0 (X11; Linux x86_64) SignerBrowser/1.0"
SIGNER_HEADERS = {"x-forwarded-for": SIGNER_IP, "user-agent": SIGNER_UA}
PUBLIC_KEYS = {
    "contract_id",
    "title",
    "status",
    "signer",
    "sent_by",
    "expires_at",
    "pdf",
    "consent_text",
    "consent_text_version",
}


def token_of(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


def signature_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "typed_name": "Maria Petrova",
        "signature_image": data_url(make_signature_png()),
        "consent": True,
        "consent_text_version": "v0-draft",
    }
    body.update(overrides)
    return body


def iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def create_and_send(
    client: httpx.AsyncClient, auth_headers: dict[str, str], **kwargs: Any
) -> tuple[dict[str, Any], str]:
    """A sent contract and its raw token. Uses a real PDF so it can be stamped."""
    kwargs.setdefault("pdf", make_pdf(1))
    created = await create_contract_via_api(client, auth_headers, **kwargs)
    resp = await client.post(f"/admin/contracts/{created['id']}/send", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body, token_of(body["signing_link"]["url"])


async def events_of(
    client: httpx.AsyncClient, auth_headers: dict[str, str], contract_id: str
) -> list[dict[str, Any]]:
    resp = await client.get(f"/admin/contracts/{contract_id}", headers=auth_headers)
    assert resp.status_code == 200
    events: list[dict[str, Any]] = resp.json()["events"]
    return events


async def token_hash_in_db(session: AsyncSession, contract_id: str) -> str | None:
    session.expire_all()
    row = await session.execute(
        text("SELECT token_hash FROM signers WHERE contract_id = :id"),
        {"id": uuid.UUID(contract_id)},
    )
    value: str | None = row.scalar_one()
    return value


# --- send -------------------------------------------------------------------------


async def test_send_from_draft_issues_link_and_stores_only_the_hash(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    admin: Admin,
    settings: Settings,
    session: AsyncSession,
) -> None:
    created = await create_contract_via_api(client, auth_headers)
    before = datetime.now(UTC)
    resp = await client.post(
        f"/admin/contracts/{created['id']}/send", headers=auth_headers, json={}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"contract", "signing_link", "email_sent"}
    assert set(body["signing_link"]) == {"url", "expires_at"}
    token = token_of(body["signing_link"]["url"])
    assert body["signing_link"]["url"] == f"{settings.web_base_url}/sign/{token}"
    assert len(token) == 43
    expires_at = iso(body["signing_link"]["expires_at"])
    ttl = timedelta(days=settings.signing_link_ttl_days)
    assert ttl <= (expires_at - before) < ttl + timedelta(seconds=5)
    assert body["email_sent"] is False  # SMTP delivery arrives with the notifications issue

    contract = body["contract"]
    assert contract["status"] == "sent"
    assert iso(contract["sent_at"]) >= before
    assert contract["expires_at"] == body["signing_link"]["expires_at"]
    assert contract["signer"]["has_active_link"] is True
    assert contract["signer"]["token_created_at"] is not None
    assert token not in resp.text.replace(body["signing_link"]["url"], "")

    assert [e["event_type"] for e in contract["events"]] == ["contract.created", "contract.sent"]
    sent = contract["events"][-1]
    assert sent["actor_type"] == "admin" and sent["actor_id"] == str(admin.id)
    assert sent["metadata"] == {
        "from_status": "draft",
        "to_status": "sent",
        "delivery": "email",
        "expires_in_days": settings.signing_link_ttl_days,
        "token_rotated": False,
    }
    assert not FORBIDDEN_METADATA_KEYS & set(sent["metadata"])
    assert token not in str(sent["metadata"])

    assert await token_hash_in_db(session, created["id"]) == hash_token(token)
    # the link is shown once: neither get nor list carries it
    detail = await client.get(f"/admin/contracts/{created['id']}", headers=auth_headers)
    listing = await client.get("/admin/contracts", headers=auth_headers)
    assert token not in detail.text and token not in listing.text


async def test_send_manual_delivery_with_custom_expiry(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await create_contract_via_api(client, auth_headers)
    before = datetime.now(UTC)
    resp = await client.post(
        f"/admin/contracts/{created['id']}/send",
        headers=auth_headers,
        json={"send_email": False, "expires_in_days": 3, "message": "Please sign by Friday"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email_sent"] is False
    lifetime = iso(body["signing_link"]["expires_at"]) - before
    assert timedelta(days=3) <= lifetime < timedelta(days=3, seconds=5)
    event = body["contract"]["events"][-1]
    assert event["metadata"]["delivery"] == "manual"
    assert event["metadata"]["expires_in_days"] == 3
    assert "Please sign" not in str(event["metadata"])  # the note is not audit data


async def test_send_validation_auth_and_not_found(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await create_contract_via_api(client, auth_headers)
    url = f"/admin/contracts/{created['id']}/send"
    assert (await client.post(url)).status_code == 401
    missing = await client.post(f"/admin/contracts/{uuid.uuid4()}/send", headers=auth_headers)
    assert missing.status_code == 404
    for days in (0, 31):
        bad = await client.post(url, headers=auth_headers, json={"expires_in_days": days})
        assert bad.status_code == 422, days
        assert bad.json()["error"]["details"]["fields"][0]["field"] == "expires_in_days"
    long_note = await client.post(url, headers=auth_headers, json={"message": "x" * 1001})
    assert long_note.status_code == 422
    # nothing above changed the contract
    detail = await client.get(f"/admin/contracts/{created['id']}", headers=auth_headers)
    assert detail.json()["status"] == "draft"
    assert len(detail.json()["events"]) == 1


@pytest.mark.parametrize("view_first", [False, True])
async def test_resend_rotates_token_and_kills_the_old_link(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    session: AsyncSession,
    view_first: bool,
) -> None:
    first, old_token = await create_and_send(client, auth_headers)
    contract_id = first["contract"]["id"]
    if view_first:
        assert (await client.get(f"/public/sign/{old_token}")).status_code == 200
    resp = await client.post(f"/admin/contracts/{contract_id}/send", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    new_token = token_of(body["signing_link"]["url"])
    assert new_token != old_token
    assert body["contract"]["status"] == "sent"
    assert body["contract"]["signer"]["has_active_link"] is True
    assert body["contract"]["events"][-1]["event_type"] == "link.resent"
    assert body["contract"]["events"][-1]["metadata"]["from_status"] == (
        "viewed" if view_first else "sent"
    )
    assert body["contract"]["events"][-1]["metadata"]["token_rotated"] is True
    if view_first:
        assert body["contract"]["first_viewed_at"] is not None  # history is kept
    assert await token_hash_in_db(session, contract_id) == hash_token(new_token)

    # the old link is indistinguishable from one that never existed
    old = await client.get(f"/public/sign/{old_token}")
    unknown = await client.get(f"/public/sign/{'x' * 43}")
    assert old.status_code == 404
    assert old.json() == unknown.json()
    assert (await client.get(f"/public/sign/{new_token}")).status_code == 200


async def test_send_from_expired_writes_contract_sent(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: AsyncSession
) -> None:
    first, _ = await create_and_send(client, auth_headers)
    contract_id = first["contract"]["id"]
    await set_status(session, contract_id, "expired")
    resp = await client.post(f"/admin/contracts/{contract_id}/send", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["contract"]["status"] == "sent"
    last = resp.json()["contract"]["events"][-1]
    assert last["event_type"] == "contract.sent"
    assert last["metadata"]["from_status"] == "expired"
    assert last["metadata"]["token_rotated"] is True


@pytest.mark.parametrize("terminal", ["signed", "cancelled"])
async def test_send_from_terminal_status_is_409(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: AsyncSession, terminal: str
) -> None:
    created = await create_contract_via_api(client, auth_headers)
    await set_status(session, created["id"], terminal)
    resp = await client.post(f"/admin/contracts/{created['id']}/send", headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["error"] == {
        "code": "invalid_state",
        "message": f"Contract cannot be sent from status '{terminal}'.",
        "details": {"status": terminal, "allowed_from": ["draft", "sent", "viewed", "expired"]},
    }
    assert len(await events_of(client, auth_headers, created["id"])) == 1


async def test_send_anonymized_contract_is_409(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: AsyncSession
) -> None:
    created = await create_contract_via_api(client, auth_headers)
    await session.execute(
        text("UPDATE signers SET name = NULL, email = NULL WHERE contract_id = :id"),
        {"id": uuid.UUID(created["id"])},
    )
    await set_status(session, created["id"], "expired", anonymized_at=datetime.now(UTC))
    resp = await client.post(f"/admin/contracts/{created['id']}/send", headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "invalid_state"
    assert resp.json()["error"]["details"] == {"reason": "anonymized"}


# --- view -------------------------------------------------------------------------


async def test_view_marks_viewed_and_records_each_load(
    client: httpx.AsyncClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    sent, token = await create_and_send(client, auth_headers, title="Hotel Aurora — 2026")
    contract_id = sent["contract"]["id"]
    pdf = make_pdf(1)
    before = datetime.now(UTC)

    resp = await client.get(f"/public/sign/{token}", headers=SIGNER_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == PUBLIC_KEYS
    assert body["contract_id"] == contract_id
    assert body["title"] == "Hotel Aurora — 2026"
    assert body["status"] == "viewed"
    assert body["signer"] == {"name": "Maria Petrova", "email": "maria@hotel-aurora.example"}
    assert body["sent_by"] == settings.org_display_name
    assert body["expires_at"] == sent["signing_link"]["expires_at"]
    assert body["consent_text_version"] == "v0-draft"
    assert "I confirm that I am Maria Petrova" in body["consent_text"]
    assert '"Hotel Aurora — 2026"' in body["consent_text"]
    assert set(body["pdf"]) == {"url", "expires_at", "sha256", "size"}
    assert body["pdf"]["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert body["pdf"]["size"] == len(pdf)
    assert (
        timedelta(0)
        < iso(body["pdf"]["expires_at"]) - before
        <= timedelta(seconds=settings.download_url_ttl_seconds + 5)
    )
    assert token not in body["pdf"]["url"]
    file_resp = await client.get(body["pdf"]["url"])
    assert file_resp.status_code == 200
    assert file_resp.headers["content-type"] == "application/pdf"
    assert file_resp.content == pdf

    detail = (await client.get(f"/admin/contracts/{contract_id}", headers=auth_headers)).json()
    assert detail["status"] == "viewed"
    assert detail["first_viewed_at"] is not None
    assert detail["signer"]["has_active_link"] is True
    viewed = detail["events"][-1]
    assert viewed["event_type"] == "link.viewed"
    assert viewed["actor_type"] == "signer"
    assert viewed["actor_id"] == detail["signer"]["id"]
    assert viewed["ip"] == SIGNER_IP
    assert viewed["user_agent"] == SIGNER_UA
    assert viewed["metadata"] == {"from_status": "sent", "to_status": "viewed"}
    assert not FORBIDDEN_METADATA_KEYS & set(viewed["metadata"])

    # reopening is allowed (single use is the signing action) and is evented every time
    again = await client.get(f"/public/sign/{token}", headers=SIGNER_HEADERS)
    assert again.status_code == 200
    assert again.json()["status"] == "viewed"
    after = (await client.get(f"/admin/contracts/{contract_id}", headers=auth_headers)).json()
    assert after["first_viewed_at"] == detail["first_viewed_at"]
    assert [e["event_type"] for e in after["events"]] == [
        "contract.created",
        "contract.sent",
        "link.viewed",
        "link.viewed",
    ]
    assert after["events"][-1]["metadata"] == {"from_status": "viewed", "to_status": "viewed"}


@pytest.mark.parametrize(
    "bad_token",
    [
        "x" * 43,  # well formed, never issued
        "x" * 42,  # too short
        "x" * 44,  # too long
        "x" * 42 + "=",  # padding is never part of a token
        "x" * 21 + "%2F" + "x" * 21,  # url-encoded slash: a path that matches no route
    ],
)
async def test_unknown_and_malformed_tokens_are_404_alike(
    client: httpx.AsyncClient, auth_headers: dict[str, str], bad_token: str
) -> None:
    resp = await client.get(f"/public/sign/{bad_token}")
    assert resp.status_code == 404
    assert resp.json() == {"error": {"code": "not_found", "message": "Not found."}}
    signed = await client.post(f"/public/sign/{bad_token}/signature", json=signature_body())
    assert signed.status_code == 404
    assert signed.json() == resp.json()


async def test_tampered_token_is_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    sent, token = await create_and_send(client, auth_headers)
    flipped = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert flipped != token
    resp = await client.get(f"/public/sign/{flipped}")
    assert resp.status_code == 404
    assert resp.json() == {"error": {"code": "not_found", "message": "Not found."}}
    signed = await client.post(f"/public/sign/{flipped}/signature", json=signature_body())
    assert signed.status_code == 404
    # the real link still works and nothing was recorded for the failed attempts
    assert (await client.get(f"/public/sign/{token}")).status_code == 200
    events = await events_of(client, auth_headers, sent["contract"]["id"])
    assert [e["event_type"] for e in events] == ["contract.created", "contract.sent", "link.viewed"]


async def test_expired_link_is_410_and_expires_the_contract(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: AsyncSession
) -> None:
    sent, token = await create_and_send(client, auth_headers)
    contract_id = sent["contract"]["id"]
    past = datetime.now(UTC) - timedelta(minutes=1)
    await session.execute(
        text("UPDATE contracts SET expires_at = :past WHERE id = :id"),
        {"past": past, "id": uuid.UUID(contract_id)},
    )
    await session.commit()

    resp = await client.get(f"/public/sign/{token}")
    assert resp.status_code == 410
    assert resp.json()["error"]["code"] == "link_expired"
    assert iso(resp.json()["error"]["details"]["expired_at"]) == past
    assert "expired" in resp.json()["error"]["message"]

    detail = (await client.get(f"/admin/contracts/{contract_id}", headers=auth_headers)).json()
    assert detail["status"] == "expired"
    assert detail["signer"]["has_active_link"] is False
    expired = detail["events"][-1]
    assert expired["event_type"] == "contract.expired"
    assert expired["actor_type"] == "system" and expired["actor_id"] is None
    assert expired["ip"] is None and expired["user_agent"] is None
    assert expired["metadata"]["from_status"] == "sent"
    assert expired["metadata"]["to_status"] == "expired"

    # a second open, and a signing attempt, are refused without a new event
    assert (await client.get(f"/public/sign/{token}")).status_code == 410
    signed = await client.post(f"/public/sign/{token}/signature", json=signature_body())
    assert signed.status_code == 410
    assert signed.json()["error"]["code"] == "link_expired"
    assert len(await events_of(client, auth_headers, contract_id)) == len(detail["events"])

    # the admin recovers by re-sending
    resent = await client.post(f"/admin/contracts/{contract_id}/send", headers=auth_headers)
    assert resent.status_code == 200
    fresh = token_of(resent.json()["signing_link"]["url"])
    assert (await client.get(f"/public/sign/{fresh}")).status_code == 200
    assert (await client.get(f"/public/sign/{token}")).status_code == 404


async def test_link_after_cancel_is_410_contract_cancelled(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    sent, token = await create_and_send(client, auth_headers)
    cancel = await client.post(
        f"/admin/contracts/{sent['contract']['id']}/cancel", headers=auth_headers
    )
    assert cancel.status_code == 200
    resp = await client.get(f"/public/sign/{token}")
    assert resp.status_code == 410
    assert resp.json()["error"] == {
        "code": "contract_cancelled",
        "message": "This contract has been cancelled by the sender.",
    }
    signed = await client.post(f"/public/sign/{token}/signature", json=signature_body())
    assert signed.status_code == 410
    assert signed.json()["error"]["code"] == "contract_cancelled"


async def test_public_requests_are_rate_limited_per_ip(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    unknown = "u" * 43
    for _ in range(settings.public_rate_limit_per_ip_per_minute):
        assert (await client.get(f"/public/sign/{unknown}")).status_code == 404
    limited = await client.get(f"/public/sign/{unknown}")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) >= 1
    # the signature endpoint shares the per-IP budget
    post = await client.post(f"/public/sign/{unknown}/signature", json=signature_body())
    assert post.status_code == 429
    other = await client.get(f"/public/sign/{unknown}", headers={"x-forwarded-for": "198.51.100.9"})
    assert other.status_code == 404


async def test_signature_attempts_are_rate_limited_per_token(
    client: httpx.AsyncClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    _, token = await create_and_send(client, auth_headers)
    bad = signature_body(consent=False)
    for _ in range(settings.public_sign_attempts_per_token):
        assert (await client.post(f"/public/sign/{token}/signature", json=bad)).status_code == 422
    limited = await client.post(f"/public/sign/{token}/signature", json=bad)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    # another token from the same IP is unaffected, and so is viewing
    other = await client.post(f"/public/sign/{'o' * 43}/signature", json=signature_body())
    assert other.status_code == 404
    assert (await client.get(f"/public/sign/{token}")).status_code == 200


# --- sign -------------------------------------------------------------------------


def _page_text(pdf: bytes, index: int) -> str:
    reader = PdfReader(BytesIO(pdf))
    return unicodedata.normalize("NFKC", " ".join(reader.pages[index].extract_text().split()))


async def test_sign_stamps_stores_and_invalidates(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    settings: Settings,
    session: AsyncSession,
) -> None:
    original = make_pdf(2)
    sent, token = await create_and_send(client, auth_headers, pdf=original)
    contract_id = sent["contract"]["id"]
    assert (await client.get(f"/public/sign/{token}", headers=SIGNER_HEADERS)).status_code == 200
    before = datetime.now(UTC)

    resp = await client.post(
        f"/public/sign/{token}/signature",
        headers=SIGNER_HEADERS,
        json=signature_body(typed_name="  Maria K. Petrova  "),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"contract_id", "status", "signed_at", "final_pdf_sha256", "download"}
    assert body["contract_id"] == contract_id
    assert body["status"] == "signed"
    signed_at = iso(body["signed_at"])
    assert before <= signed_at <= datetime.now(UTC)
    download = body["download"]
    assert set(download) == {"variant", "url", "expires_at", "sha256", "filename"}
    assert download["variant"] == "signed"
    assert download["sha256"] == body["final_pdf_sha256"]
    assert download["filename"] == "hotel-aurora-onboarding-2026-signed.pdf"
    assert token not in resp.text

    # the signed PDF is served only through the storage backend's signed URL
    file_resp = await client.get(download["url"])
    assert file_resp.status_code == 200
    final = file_resp.content
    assert hashlib.sha256(final).hexdigest() == body["final_pdf_sha256"]
    assert len(PdfReader(BytesIO(final)).pages) == 3  # original 2 + certificate
    assert "Signed electronically by Maria K. Petrova" in _page_text(final, 1)
    certificate = _page_text(final, 2)
    assert "Signature Certificate" in certificate
    assert contract_id in certificate
    assert "Maria K. Petrova" in certificate
    assert "maria@hotel-aurora.example" in certificate
    assert SIGNER_IP in certificate and SIGNER_UA in certificate
    assert hashlib.sha256(original).hexdigest() in certificate
    assert body["final_pdf_sha256"] not in certificate
    for name in ("contract.created", "contract.sent", "link.viewed", "contract.signed"):
        assert name in certificate

    storage_dir = Path(settings.local_storage_dir) / "contracts" / contract_id
    assert (storage_dir / "signed.pdf").read_bytes() == final
    assert (storage_dir / "signature.png").read_bytes().startswith(b"\x89PNG")

    detail = (await client.get(f"/admin/contracts/{contract_id}", headers=auth_headers)).json()
    assert detail["status"] == "signed"
    assert detail["signed_at"] == body["signed_at"]
    assert detail["final_pdf_sha256"] == body["final_pdf_sha256"]
    assert detail["retain_until"] == str(
        signed_at.date().replace(year=signed_at.year + settings.retention_signed_years_after_term)
    )
    signer = detail["signer"]
    assert signer["has_active_link"] is False
    assert signer["typed_name"] == "Maria K. Petrova"
    assert signer["consent_given_at"] == body["signed_at"]
    assert signer["consent_text_version"] == "v0-draft"
    assert signer["signed_ip"] == SIGNER_IP
    assert signer["signed_user_agent"] == SIGNER_UA
    event = detail["events"][-1]
    assert [e["event_type"] for e in detail["events"]] == [
        "contract.created",
        "contract.sent",
        "link.viewed",
        "contract.signed",
    ]
    assert event["actor_type"] == "signer" and event["actor_id"] == signer["id"]
    assert event["occurred_at"] == body["signed_at"]
    assert event["ip"] == SIGNER_IP and event["user_agent"] == SIGNER_UA
    assert event["metadata"]["from_status"] == "viewed"
    assert event["metadata"]["to_status"] == "signed"
    assert event["metadata"]["final_pdf_sha256"] == body["final_pdf_sha256"]
    assert event["metadata"]["page_count"] == 3
    assert not FORBIDDEN_METADATA_KEYS & set(event["metadata"])
    assert "Maria" not in str(event["metadata"])

    # the admin can now fetch the signed variant
    admin_dl = await client.get(
        f"/admin/contracts/{contract_id}/download",
        headers=auth_headers,
        params={"variant": "signed"},
    )
    assert admin_dl.status_code == 200
    assert admin_dl.json()["sha256"] == body["final_pdf_sha256"]

    # single use: the link is dead for viewing and for signing
    reopened = await client.get(f"/public/sign/{token}")
    assert reopened.status_code == 410
    assert reopened.json()["error"]["code"] == "link_used"
    assert reopened.json()["error"]["details"]["signed_at"] == body["signed_at"]
    reused = await client.post(f"/public/sign/{token}/signature", json=signature_body())
    assert reused.status_code == 410
    assert reused.json()["error"]["code"] == "link_used"
    # only the admin download above added an event; the refused reuse attempts added none
    assert [e["event_type"] for e in await events_of(client, auth_headers, contract_id)] == [
        "contract.created",
        "contract.sent",
        "link.viewed",
        "contract.signed",
        "pdf.downloaded",
    ]
    assert await token_hash_in_db(session, contract_id) == hash_token(token)


async def test_sign_without_prior_view_and_term_end_date(
    client: httpx.AsyncClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    sent, token = await create_and_send(client, auth_headers, term_end_date="2028-12-31")
    resp = await client.post(f"/public/sign/{token}/signature", json=signature_body())
    assert resp.status_code == 200, resp.text
    detail = (
        await client.get(f"/admin/contracts/{sent['contract']['id']}", headers=auth_headers)
    ).json()
    assert detail["status"] == "signed"
    assert detail["first_viewed_at"] is None
    assert detail["events"][-1]["metadata"]["from_status"] == "sent"
    assert detail["retain_until"] == str(
        date(2028, 12, 31).replace(year=2028 + settings.retention_signed_years_after_term)
    )


async def test_sign_validation_errors_change_nothing(
    client: httpx.AsyncClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    # Every attempt counts against the per-token budget (10), so the cases are
    # spread over two links.
    first, token_a = await create_and_send(client, auth_headers)
    second, token_b = await create_and_send(client, auth_headers)

    async def expect(
        token: str, status: int, field: str | None = None, **overrides: Any
    ) -> dict[str, Any]:
        resp = await client.post(
            f"/public/sign/{token}/signature", json=signature_body(**overrides)
        )
        assert resp.status_code == status, (overrides, resp.text)
        error: dict[str, Any] = resp.json()["error"]
        if field is not None:
            assert error["code"] == "validation_error"
            assert field in {f["field"] for f in error["details"]["fields"]}
        return error

    await expect(token_a, 422, "consent", consent=False)
    await expect(token_a, 422, "typed_name", typed_name="M")
    await expect(token_a, 422, "typed_name", typed_name="   ")
    await expect(token_a, 422, "typed_name", typed_name="x" * 201)
    await expect(token_a, 422, "signature_image", signature_image="data:image/jpeg;base64,AAAA")
    await expect(token_a, 422, "signature_image", signature_image="data:image/png;base64,####")
    await expect(token_a, 422, "signature_image", signature_image="data:image/png;base64,AAAAA")
    await expect(token_a, 422, "signature_image", signature_image=data_url(b"GIF89a not a png"))

    too_wide = make_signature_png((2001, 10))
    await expect(token_b, 422, "signature_image", signature_image=data_url(too_wide))
    await expect(token_b, 422, "consent_text_version", consent_text_version="v1-final")
    oversized = make_signature_png((1990, 990), transparent=False)
    oversized = oversized + b"\x00" * (settings.max_signature_png_bytes - len(oversized) + 1)
    error = await expect(token_b, 413, signature_image=data_url(oversized))
    assert error["code"] == "payload_too_large"
    assert error["details"] == {"max_bytes": settings.max_signature_png_bytes}
    url_b = f"/public/sign/{token_b}/signature"
    missing = await client.post(url_b, json={"typed_name": "Maria Petrova"})
    assert missing.status_code == 422
    bad_json = await client.post(
        url_b, content=b"{nope", headers={"content-type": "application/json"}
    )
    assert bad_json.status_code == 400
    assert bad_json.json()["error"]["code"] == "bad_request"

    for contract_id in (first["contract"]["id"], second["contract"]["id"]):
        detail = (await client.get(f"/admin/contracts/{contract_id}", headers=auth_headers)).json()
        assert detail["status"] == "sent"
        assert detail["signer"]["typed_name"] is None
        assert [e["event_type"] for e in detail["events"]] == ["contract.created", "contract.sent"]
        folder = Path(settings.local_storage_dir) / "contracts" / contract_id
        assert sorted(p.name for p in folder.iterdir()) == ["original.pdf"]
    # both links are still good
    url_a = f"/public/sign/{token_a}/signature"
    assert (await client.post(url_a, json=signature_body())).status_code == 200
    assert (await client.post(url_b, json=signature_body())).status_code == 200


async def test_sign_failure_leaves_contract_and_storage_untouched(
    client: httpx.AsyncClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    # PDF_BYTES carries the magic bytes but no pages, so stamping fails server-side.
    sent, token = await create_and_send(client, auth_headers, pdf=PDF_BYTES)
    contract_id = sent["contract"]["id"]
    assert (await client.get(f"/public/sign/{token}")).status_code == 200
    resp = await client.post(f"/public/sign/{token}/signature", json=signature_body())
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
    assert "request_id" in resp.json()["error"]["details"]
    assert token not in resp.text

    detail = (await client.get(f"/admin/contracts/{contract_id}", headers=auth_headers)).json()
    assert detail["status"] == "viewed"
    assert detail["final_pdf_sha256"] is None
    assert detail["signer"]["has_active_link"] is True
    assert [e["event_type"] for e in detail["events"]] == [
        "contract.created",
        "contract.sent",
        "link.viewed",
    ]
    folder = Path(settings.local_storage_dir) / "contracts" / contract_id
    assert sorted(p.name for p in folder.iterdir()) == ["original.pdf"]
    assert (await client.get(f"/public/sign/{token}")).status_code == 200  # can retry


async def test_sign_refuses_when_original_hash_no_longer_matches(
    client: httpx.AsyncClient, auth_headers: dict[str, str], app: FastAPI
) -> None:
    sent, token = await create_and_send(client, auth_headers)
    contract_id = sent["contract"]["id"]
    await app.state.storage.put(
        f"contracts/{contract_id}/original.pdf", make_pdf(3), "application/pdf"
    )
    resp = await client.post(f"/public/sign/{token}/signature", json=signature_body())
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
    detail = (await client.get(f"/admin/contracts/{contract_id}", headers=auth_headers)).json()
    assert detail["status"] == "sent"
    assert detail["final_pdf_sha256"] is None


async def test_garbage_forwarded_ip_does_not_break_signing(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    sent, token = await create_and_send(client, auth_headers)
    headers = {"x-forwarded-for": "not-an-ip, 10.0.0.1", "user-agent": "x" * 2000}
    assert (await client.get(f"/public/sign/{token}", headers=headers)).status_code == 200
    resp = await client.post(
        f"/public/sign/{token}/signature", headers=headers, json=signature_body()
    )
    assert resp.status_code == 200, resp.text
    detail = (
        await client.get(f"/admin/contracts/{sent['contract']['id']}", headers=auth_headers)
    ).json()
    assert detail["signer"]["signed_ip"] == "127.0.0.1"  # the direct peer, not the junk header
    assert len(detail["signer"]["signed_user_agent"]) == 1000
    assert detail["events"][-1]["ip"] == "127.0.0.1"
