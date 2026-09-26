from __future__ import annotations

from fastapi import APIRouter, Request

from app.deps import CurrentAdmin, LimiterDep, SessionDep, SettingsDep, client_ip
from app.errors import ApiError
from app.routers.responses import (
    BAD_REQUEST,
    INTERNAL,
    RATE_LIMITED,
    UNAUTHORIZED,
    VALIDATION,
    responses,
)
from app.schemas.auth import AdminUser, LoginRequest, LoginResponse
from app.schemas.common import Error, ErrorCode
from app.services.auth import authenticate

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


@router.post(
    "/login",
    operation_id="adminLogin",
    summary="Log in with email and password",
    response_model=LoginResponse,
    responses=responses(
        BAD_REQUEST,
        {401: {"model": Error, "description": "Wrong email or password, or inactive admin."}},
        VALIDATION,
        RATE_LIMITED,
        INTERNAL,
    ),
)
async def admin_login(
    request: Request,
    body: LoginRequest,
    session: SessionDep,
    settings: SettingsDep,
    limiter: LimiterDep,
) -> LoginResponse:
    retry_after = limiter.check(
        f"login:{client_ip(request) or 'unknown'}",
        settings.admin_login_rate_limit_per_ip_per_minute,
    )
    if retry_after is not None:
        raise ApiError(
            429,
            ErrorCode.rate_limited,
            "Too many requests. Try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )
    result = await authenticate(session, settings, body.email, body.password)
    if result is None:
        raise ApiError(401, ErrorCode.invalid_credentials, "Email or password is incorrect.")
    admin, token = result
    return LoginResponse(
        access_token=token,
        expires_in=settings.admin_jwt_ttl_minutes * 60,
        admin=AdminUser.model_validate(admin),
    )


@router.get(
    "/me",
    operation_id="getCurrentAdmin",
    summary="Get the admin identified by the bearer token",
    response_model=AdminUser,
    responses=responses(UNAUTHORIZED, INTERNAL),
)
async def get_current_admin(admin: CurrentAdmin) -> AdminUser:
    return AdminUser.model_validate(admin)
