"""Signer-facing endpoints reached through the emailed link (tag ``public-signing``).

No authentication: the token in the path is the credential. Rate limited per
IP on every call and per token on signature attempts (SPEC.md §7). Nothing
here logs the path, the body, or the token (rule 6); the limiter is keyed by
``sha256(token)``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request

from app.deps import (
    ClientDep,
    LimiterDep,
    MailerDep,
    SessionDep,
    SettingsDep,
    StorageDep,
    client_ip,
)
from app.errors import rate_limited
from app.routers.responses import (
    BAD_REQUEST,
    INTERNAL,
    NOT_FOUND,
    RATE_LIMITED,
    VALIDATION,
    responses,
)
from app.schemas.common import Error
from app.schemas.public import PublicContract, SignatureResult, SubmitSignatureRequest
from app.services import signing as svc
from app.services import tokens

router = APIRouter(prefix="/public/sign", tags=["public-signing"])

LINK_GONE: dict[int | str, dict[str, Any]] = {
    410: {"model": Error, "description": "The token was valid once but can no longer be used."}
}
TOO_LARGE: dict[int | str, dict[str, Any]] = {
    413: {"model": Error, "description": "Signature image exceeds the size limit."}
}

TokenPath = Annotated[
    str,
    Path(
        pattern=tokens.TOKEN_PATTERN,
        description="43-character base64url signing token from the emailed link.",
    ),
]


def _limit_by_ip(request: Request, settings: SettingsDep, limiter: LimiterDep) -> None:
    retry_after = limiter.check(
        f"public:{client_ip(request) or 'unknown'}", settings.public_rate_limit_per_ip_per_minute
    )
    if retry_after is not None:
        raise rate_limited(retry_after)


def _limit_by_token(token: TokenPath, settings: SettingsDep, limiter: LimiterDep) -> None:
    # Runs before the body is parsed, so malformed attempts count too.
    retry_after = limiter.check(
        f"sign:{tokens.hash_token(token)}", settings.public_sign_attempts_per_token
    )
    if retry_after is not None:
        raise rate_limited(retry_after)


@router.get(
    "/{token}",
    operation_id="getContractByToken",
    summary="Load a contract for signing",
    response_model=PublicContract,
    responses=responses(NOT_FOUND, LINK_GONE, RATE_LIMITED, INTERNAL),
    dependencies=[Depends(_limit_by_ip)],
)
async def get_contract_by_token(
    token: TokenPath,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    client: ClientDep,
) -> PublicContract:
    return await svc.view_contract(session, settings, storage, token=token, client=client)


@router.post(
    "/{token}/signature",
    operation_id="submitSignature",
    summary="Submit the signature",
    response_model=SignatureResult,
    responses=responses(
        BAD_REQUEST, NOT_FOUND, LINK_GONE, TOO_LARGE, VALIDATION, RATE_LIMITED, INTERNAL
    ),
    dependencies=[Depends(_limit_by_ip), Depends(_limit_by_token)],
)
async def submit_signature(
    token: TokenPath,
    body: SubmitSignatureRequest,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    mailer: MailerDep,
    client: ClientDep,
) -> SignatureResult:
    return await svc.submit_signature(
        session, settings, storage, mailer, token=token, body=body, client=client
    )
