"""FastAPI dependencies shared by routers."""

from __future__ import annotations

import ipaddress
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import get_session
from app.errors import unauthorized
from app.models.admin import Admin
from app.ratelimit import RateLimiter
from app.security import decode_admin_token
from app.services.auth import get_admin_by_id
from app.services.events import ClientInfo
from app.services.storage import StorageBackend

_bearer = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_storage(request: Request) -> StorageBackend:
    storage: StorageBackend = request.app.state.storage
    return storage


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


def _valid_ip(value: str | None) -> str | None:
    """Only a syntactically valid address reaches an ``inet`` column; junk becomes None."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = _valid_ip(forwarded.split(",")[0].strip())
        if first:
            return first
    return _valid_ip(request.client.host if request.client else None)


def get_client_info(request: Request) -> ClientInfo:
    ua = request.headers.get("user-agent")
    return ClientInfo(ip=client_ip(request), user_agent=ua[:1000] if ua else None)


async def get_current_admin(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Admin:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    admin_id = decode_admin_token(request.app.state.settings, credentials.credentials)
    if admin_id is None:
        raise unauthorized()
    admin = await get_admin_by_id(session, admin_id)
    if admin is None:
        raise unauthorized()
    return admin


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
StorageDep = Annotated[StorageBackend, Depends(get_storage)]
CurrentAdmin = Annotated[Admin, Depends(get_current_admin)]
ClientDep = Annotated[ClientInfo, Depends(get_client_info)]
LimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
