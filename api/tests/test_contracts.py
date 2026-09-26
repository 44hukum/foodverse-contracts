"""Admin contract endpoints: create, list, get, cancel, download."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Admin, ContractEvent, ContractEventPii
from app.services.events import FORBIDDEN_METADATA_KEYS
from tests.conftest import PDF_BYTES, create_contract_via_api, multipart_contract, set_status

SHA = hashlib.sha256(PDF_BYTES).hexdigest()
SUMMARY_KEYS = {
    "id",
    "title",
    "status",
    "created_by",
    "term_end_date",
    "signer_name",
    "signer_email",
    "original_pdf_sha256",
    "final_pdf_sha256",
    "sent_at",
    "first_viewed_at",
    "signed_at",
    "expires_at",
    "cancelled_at",
    "retain_until",
    "anonymized_at",
    "created_at",
    "updated_at",
}
DETAIL_KEYS = SUMMARY_KEYS | {"original_pdf_size", "signer", "events"}


# --- create ---------------------------------------------------------------------


async def test_create_contract_stores_pdf_and_writes_event(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    admin: Admin,
    settings: Settings,
    session: AsyncSession,
) -> None:
    body = await create_contract_via_api(client, auth_headers, term_end_date="2028-12-31")
    assert set(body) == DETAIL_KEYS
    assert body["status"] == "draft"
    assert body["created_by"] == str(admin.id)
    assert body["term_end_date"] == "2028-12-31"
    assert body["original_pdf_sha256"] == SHA
    assert body["original_pdf_size"] == len(PDF_BYTES)
    assert body["final_pdf_sha256"] is None
    assert body["signer"]["name"] == "Maria Petrova"
    assert body["signer"]["email"] == "maria@hotel-aurora.example"
    assert body["signer"]["has_active_link"] is False
    assert "token_hash" not in body["signer"]

    stored = Path(settings.local_storage_dir) / "contracts" / body["id"] / "original.pdf"
    assert stored.read_bytes() == PDF_BYTES

    assert len(body["events"]) == 1
    event = body["events"][0]
    assert event["event_type"] == "contract.created"
    assert event["actor_type"] == "admin"
    assert event["actor_id"] == str(admin.id)
    assert event["ip"] is not None
    assert event["user_agent"] == "pytest-client/1.0"
    assert event["metadata"]["to_status"] == "draft"
    assert not FORBIDDEN_METADATA_KEYS & set(event["metadata"])

    rows = (
        (
            await session.execute(
                select(ContractEvent).where(ContractEvent.contract_id == uuid.UUID(body["id"]))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    pii = await session.get(ContractEventPii, rows[0].id)
    assert pii is not None and pii.user_agent == "pytest-client/1.0"


async def test_create_uses_first_forwarded_ip(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/admin/contracts",
        headers={**auth_headers, "x-forwarded-for": "203.0.113.5, 10.0.0.1"},
        **multipart_contract(),
    )
    assert resp.status_code == 201
    assert resp.json()["events"][0]["ip"] == "203.0.113.5"


async def test_create_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.post("/admin/contracts", **multipart_contract())
    assert resp.status_code == 401


async def test_create_rejects_non_pdf(
    client: httpx.AsyncClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    wrong_type = await client.post(
        "/admin/contracts", headers=auth_headers, **multipart_contract(content_type="image/png")
    )
    assert wrong_type.status_code == 415
    assert wrong_type.json()["error"]["code"] == "unsupported_media_type"

    wrong_magic = await client.post(
        "/admin/contracts", headers=auth_headers, **multipart_contract(pdf=b"GIF89a not a pdf")
    )
    assert wrong_magic.status_code == 415
    assert not list(Path(settings.local_storage_dir).rglob("*.pdf"))


async def test_create_rejects_oversized_pdf(
    client: httpx.AsyncClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    big = PDF_BYTES + b"0" * (settings.max_pdf_bytes - len(PDF_BYTES) + 1)
    resp = await client.post(
        "/admin/contracts", headers=auth_headers, **multipart_contract(pdf=big)
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["details"]["max_bytes"] == settings.max_pdf_bytes
    assert not list(Path(settings.local_storage_dir).rglob("*.pdf"))


async def test_create_validation_errors(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    bad_email = await client.post(
        "/admin/contracts", headers=auth_headers, **multipart_contract(signer_email="nope")
    )
    assert bad_email.status_code == 422
    assert bad_email.json()["error"]["details"]["fields"][0]["field"] == "signer_email"

    long_title = await client.post(
        "/admin/contracts", headers=auth_headers, **multipart_contract(title="x" * 201)
    )
    assert long_title.status_code == 422

    bad_date = await client.post(
        "/admin/contracts", headers=auth_headers, **multipart_contract(term_end_date="soon")
    )
    assert bad_date.status_code == 422

    missing = await client.post(
        "/admin/contracts",
        headers=auth_headers,
        data={"title": "t", "signer_name": "n", "signer_email": "a@b.co"},
    )
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "bad_request"


# --- list -----------------------------------------------------------------------


async def test_list_orders_filters_and_paginates(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: AsyncSession
) -> None:
    ids = [
        (await create_contract_via_api(client, auth_headers, title=f"Contract {i}"))["id"]
        for i in range(3)
    ]
    await set_status(session, ids[1], "cancelled")

    page = await client.get("/admin/contracts", headers=auth_headers, params={"limit": 2})
    assert page.status_code == 200
    body = page.json()
    assert set(body) == {"items", "next_cursor"}
    assert [c["id"] for c in body["items"]] == [ids[2], ids[1]]
    assert set(body["items"][0]) == SUMMARY_KEYS
    assert body["next_cursor"]

    page2 = await client.get(
        "/admin/contracts", headers=auth_headers, params={"limit": 2, "cursor": body["next_cursor"]}
    )
    assert [c["id"] for c in page2.json()["items"]] == [ids[0]]
    assert page2.json()["next_cursor"] is None

    filtered = await client.get(
        "/admin/contracts", headers=auth_headers, params=[("status", "cancelled")]
    )
    assert [c["id"] for c in filtered.json()["items"]] == [ids[1]]

    multi = await client.get(
        "/admin/contracts",
        headers=auth_headers,
        params=[("status", "draft"), ("status", "cancelled")],
    )
    assert len(multi.json()["items"]) == 3

    searched = await client.get(
        "/admin/contracts", headers=auth_headers, params={"q": "contract 0"}
    )
    assert [c["id"] for c in searched.json()["items"]] == [ids[0]]
    by_signer = await client.get("/admin/contracts", headers=auth_headers, params={"q": "PETROVA"})
    assert len(by_signer.json()["items"]) == 3
    wildcard = await client.get("/admin/contracts", headers=auth_headers, params={"q": "%"})
    assert wildcard.json()["items"] == []


async def test_list_rejects_bad_inputs(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.get("/admin/contracts")).status_code == 401
    bad_cursor = await client.get(
        "/admin/contracts", headers=auth_headers, params={"cursor": "not-a-cursor"}
    )
    assert bad_cursor.status_code == 400
    bad_limit = await client.get("/admin/contracts", headers=auth_headers, params={"limit": 101})
    assert bad_limit.status_code == 422
    bad_status = await client.get(
        "/admin/contracts", headers=auth_headers, params={"status": "bogus"}
    )
    assert bad_status.status_code == 422


# --- get ------------------------------------------------------------------------


async def test_get_contract_returns_events_ascending(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await create_contract_via_api(client, auth_headers)
    await client.get(f"/admin/contracts/{created['id']}/download", headers=auth_headers)
    resp = await client.get(f"/admin/contracts/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert [e["event_type"] for e in events] == ["contract.created", "pdf.downloaded"]
    assert events[0]["id"] < events[1]["id"]
    assert all(e["contract_id"] == created["id"] for e in events)


async def test_get_contract_not_found(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    unknown = await client.get(f"/admin/contracts/{uuid.uuid4()}", headers=auth_headers)
    assert unknown.status_code == 404
    assert unknown.json() == {"error": {"code": "not_found", "message": "Not found."}}
    malformed = await client.get("/admin/contracts/not-a-uuid", headers=auth_headers)
    assert malformed.status_code == 404
    assert malformed.json() == unknown.json()
    assert (await client.get(f"/admin/contracts/{uuid.uuid4()}")).status_code == 401


# --- cancel ---------------------------------------------------------------------


async def test_cancel_from_draft_writes_one_event(
    client: httpx.AsyncClient, auth_headers: dict[str, str], admin: Admin
) -> None:
    created = await create_contract_via_api(client, auth_headers)
    resp = await client.post(
        f"/admin/contracts/{created['id']}/cancel",
        headers=auth_headers,
        json={"reason": "Signer changed their mind"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["cancelled_at"] is not None
    assert body["updated_at"] > created["updated_at"]
    assert [e["event_type"] for e in body["events"]] == ["contract.created", "contract.cancelled"]
    cancelled = body["events"][-1]
    assert cancelled["actor_id"] == str(admin.id)
    assert cancelled["metadata"] == {
        "from_status": "draft",
        "to_status": "cancelled",
        "reason": "Signer changed their mind",
    }


@pytest.mark.parametrize("from_status", ["sent", "viewed"])
async def test_cancel_from_live_link_invalidates_token(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: AsyncSession, from_status: str
) -> None:
    created = await create_contract_via_api(client, auth_headers)
    await set_status(session, created["id"], from_status)
    await session.execute(
        __import__("sqlalchemy").text(
            "UPDATE signers SET token_hash = :h, token_created_at = now() WHERE contract_id = :id"
        ),
        {"h": "a" * 64, "id": uuid.UUID(created["id"])},
    )
    await session.commit()
    before = await client.get(f"/admin/contracts/{created['id']}", headers=auth_headers)
    assert before.json()["signer"]["has_active_link"] is True

    resp = await client.post(f"/admin/contracts/{created['id']}/cancel", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["signer"]["has_active_link"] is False
    assert resp.json()["events"][-1]["metadata"]["from_status"] == from_status


@pytest.mark.parametrize("terminal", ["signed", "expired", "cancelled"])
async def test_cancel_from_terminal_status_is_409(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: AsyncSession, terminal: str
) -> None:
    created = await create_contract_via_api(client, auth_headers)
    await set_status(session, created["id"], terminal)
    resp = await client.post(f"/admin/contracts/{created['id']}/cancel", headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["error"] == {
        "code": "invalid_state",
        "message": f"Contract cannot be cancelled from status '{terminal}'.",
        "details": {"status": terminal, "allowed_from": ["draft", "sent", "viewed"]},
    }
    detail = await client.get(f"/admin/contracts/{created['id']}", headers=auth_headers)
    assert [e["event_type"] for e in detail.json()["events"]] == ["contract.created"]


async def test_cancel_errors(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    assert (await client.post(f"/admin/contracts/{uuid.uuid4()}/cancel")).status_code == 401
    missing = await client.post(f"/admin/contracts/{uuid.uuid4()}/cancel", headers=auth_headers)
    assert missing.status_code == 404
    created = await create_contract_via_api(client, auth_headers)
    too_long = await client.post(
        f"/admin/contracts/{created['id']}/cancel", headers=auth_headers, json={"reason": "x" * 501}
    )
    assert too_long.status_code == 422


# --- download -------------------------------------------------------------------


async def test_download_original_returns_signed_url_and_event(
    client: httpx.AsyncClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    created = await create_contract_via_api(client, auth_headers, title="Hotel Aurora — 2026")
    resp = await client.get(f"/admin/contracts/{created['id']}/download", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"variant", "url", "expires_at", "sha256", "filename"}
    assert body["variant"] == "original"
    assert body["sha256"] == SHA
    assert body["filename"] == "hotel-aurora-2026-original.pdf"
    assert body["url"].startswith(
        f"{settings.api_base_url}/_storage/local/contracts/{created['id']}/"
    )
    assert "sig=" in body["url"] and "exp=" in body["url"]

    # the URL is served by the storage backend's route, not by an API endpoint
    file_resp = await client.get(body["url"])
    assert file_resp.status_code == 200
    assert file_resp.headers["content-type"] == "application/pdf"
    assert file_resp.content == PDF_BYTES

    detail = await client.get(f"/admin/contracts/{created['id']}", headers=auth_headers)
    last = detail.json()["events"][-1]
    assert last["event_type"] == "pdf.downloaded"
    assert last["metadata"] == {"variant": "original", "sha256": SHA}


async def test_download_signed_variant_requires_signed_status(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: AsyncSession
) -> None:
    created = await create_contract_via_api(client, auth_headers)
    resp = await client.get(
        f"/admin/contracts/{created['id']}/download",
        headers=auth_headers,
        params={"variant": "signed"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"] == {
        "code": "invalid_state",
        "message": "Contract is not signed; no signed PDF exists.",
        "details": {"status": "draft"},
    }
    bad_variant = await client.get(
        f"/admin/contracts/{created['id']}/download", headers=auth_headers, params={"variant": "x"}
    )
    assert bad_variant.status_code == 422
    assert (
        await client.get(f"/admin/contracts/{uuid.uuid4()}/download", headers=auth_headers)
    ).status_code == 404
    assert (await client.get(f"/admin/contracts/{created['id']}/download")).status_code == 401


async def test_local_download_route_refuses_bad_or_expired_signatures(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await create_contract_via_api(client, auth_headers)
    resp = await client.get(f"/admin/contracts/{created['id']}/download", headers=auth_headers)
    url = resp.json()["url"]
    tampered = re.sub(r"sig=([0-9a-f]{60})[0-9a-f]{4}", r"sig=\g<1>zzzz", url)
    assert tampered != url
    assert (await client.get(tampered)).status_code == 404
    no_sig = url.split("?")[0]
    assert (await client.get(no_sig)).status_code == 404
    expired = url.replace("exp=", "exp=1")  # far in the past, signature no longer matches either
    assert (await client.get(expired)).status_code == 404
    other_key = url.replace("original.pdf", "../../secret.pdf")
    assert (await client.get(other_key)).status_code == 404
