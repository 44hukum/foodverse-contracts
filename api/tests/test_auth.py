"""POST /admin/auth/login and GET /admin/auth/me."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Admin
from app.security import create_admin_token
from tests.conftest import PASSWORD


async def test_login_returns_jwt_and_admin(
    client: httpx.AsyncClient, admin: Admin, settings: Settings, session: AsyncSession
) -> None:
    resp = await client.post(
        "/admin/auth/login", json={"email": admin.email.upper(), "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "admin"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.admin_jwt_ttl_minutes * 60
    assert body["admin"]["id"] == str(admin.id)
    assert body["admin"]["email"] == admin.email
    assert "password_hash" not in body["admin"]
    claims = jwt.decode(
        body["access_token"], settings.jwt_secret, algorithms=["HS256"], issuer=settings.jwt_issuer
    )
    assert claims["sub"] == str(admin.id)
    assert claims["exp"] - claims["iat"] == settings.admin_jwt_ttl_minutes * 60
    admin_id = admin.id
    session.expire_all()
    refreshed = await session.get(Admin, admin_id)
    assert refreshed is not None and refreshed.last_login_at is not None
    assert body["admin"]["last_login_at"] is not None


async def test_login_failures_are_indistinguishable(
    client: httpx.AsyncClient, admin: Admin, session: AsyncSession
) -> None:
    wrong = await client.post(
        "/admin/auth/login", json={"email": admin.email, "password": "definitely-not-it-123"}
    )
    unknown = await client.post(
        "/admin/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    admin.is_active = False
    await session.commit()
    inactive = await client.post(
        "/admin/auth/login", json={"email": admin.email, "password": PASSWORD}
    )
    for resp in (wrong, unknown, inactive):
        assert resp.status_code == 401
        assert resp.json() == {
            "error": {"code": "invalid_credentials", "message": "Email or password is incorrect."}
        }


async def test_login_validation_and_bad_json(client: httpx.AsyncClient) -> None:
    short = await client.post("/admin/auth/login", json={"email": "a@b.co", "password": "short"})
    assert short.status_code == 422
    assert short.json()["error"]["code"] == "validation_error"
    assert short.json()["error"]["details"]["fields"][0]["field"] == "password"

    bad_email = await client.post(
        "/admin/auth/login", json={"email": "not-an-email", "password": PASSWORD}
    )
    assert bad_email.status_code == 422

    bad_json = await client.post(
        "/admin/auth/login", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert bad_json.status_code == 400
    assert bad_json.json()["error"]["code"] == "bad_request"


async def test_login_is_rate_limited_per_ip(
    client: httpx.AsyncClient, admin: Admin, settings: Settings
) -> None:
    payload = {"email": admin.email, "password": "definitely-not-it-123"}
    for _ in range(settings.admin_login_rate_limit_per_ip_per_minute):
        resp = await client.post("/admin/auth/login", json=payload)
        assert resp.status_code == 401
    limited = await client.post("/admin/auth/login", json=payload)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) >= 1
    # a different client IP is not affected
    other = await client.post(
        "/admin/auth/login", json=payload, headers={"x-forwarded-for": "198.51.100.9"}
    )
    assert other.status_code == 401


async def test_me_requires_valid_bearer(
    client: httpx.AsyncClient, admin: Admin, settings: Settings, auth_headers: dict[str, str]
) -> None:
    ok = await client.get("/admin/auth/me", headers=auth_headers)
    assert ok.status_code == 200
    assert ok.json()["id"] == str(admin.id)
    assert set(ok.json()) == {"id", "email", "name", "last_login_at", "created_at"}

    missing = await client.get("/admin/auth/me")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"
    assert missing.headers["www-authenticate"] == "Bearer"

    garbage = await client.get("/admin/auth/me", headers={"Authorization": "Bearer nope"})
    assert garbage.status_code == 401

    expired_token = create_admin_token(
        settings,
        admin.id,
        now=datetime.now(UTC) - timedelta(minutes=settings.admin_jwt_ttl_minutes + 5),
    )
    expired = await client.get(
        "/admin/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert expired.status_code == 401

    wrong_key = jwt.encode(
        {"sub": str(admin.id), "iat": 0, "exp": 2**31, "iss": settings.jwt_issuer},
        "another-secret-that-is-long-enough-0123456789",
        algorithm="HS256",
    )
    forged = await client.get("/admin/auth/me", headers={"Authorization": f"Bearer {wrong_key}"})
    assert forged.status_code == 401

    unknown_admin = create_admin_token(settings, uuid.uuid4())
    gone = await client.get("/admin/auth/me", headers={"Authorization": f"Bearer {unknown_admin}"})
    assert gone.status_code == 401


async def test_inactive_admin_keeps_token_until_expiry(
    client: httpx.AsyncClient, admin: Admin, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    admin.is_active = False
    await session.commit()
    resp = await client.get("/admin/auth/me", headers=auth_headers)
    assert resp.status_code == 200
