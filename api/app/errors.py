"""Error responses. Every error body uses the ``Error`` schema from openapi.yaml."""

from __future__ import annotations

import logging
import re
import secrets
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import Error, ErrorBody, ErrorCode

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_response(
    status_code: int,
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = Error(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", exclude_none=True),
        headers=headers,
    )


def not_found() -> ApiError:
    return ApiError(404, ErrorCode.not_found, "Not found.")


def unauthorized() -> ApiError:
    return ApiError(
        401,
        ErrorCode.unauthorized,
        "A valid bearer token is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def invalid_state(message: str, details: dict[str, Any]) -> ApiError:
    return ApiError(409, ErrorCode.invalid_state, message, details)


def rate_limited(retry_after: int) -> ApiError:
    return ApiError(
        429,
        ErrorCode.rate_limited,
        "Too many requests. Try again shortly.",
        headers={"Retry-After": str(retry_after)},
    )


def internal_error(reason: str) -> ApiError:
    """A 500 with a reference id; ``reason`` is logged, never sent to the client."""
    request_id = secrets.token_hex(4)
    log.error("internal error request_id=%s reason=%s", request_id, reason)
    return ApiError(
        500,
        ErrorCode.internal_error,
        f"Something went wrong. Reference id {request_id}.",
        {"request_id": request_id},
    )


# Signing tokens travel in the public URL path (rule 6): never let them into a log line.
_TOKEN_PATH_RE = re.compile(r"(/public/sign/)[^/?#]+")


def redact_path(path: str) -> str:
    return _TOKEN_PATH_RE.sub(r"\1[redacted]", path)


_STATUS_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.bad_request,
    401: ErrorCode.unauthorized,
    404: ErrorCode.not_found,
    405: ErrorCode.not_found,
    413: ErrorCode.payload_too_large,
    415: ErrorCode.unsupported_media_type,
    422: ErrorCode.validation_error,
    429: ErrorCode.rate_limited,
}


def _field_path(loc: tuple[int | str, ...]) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return ".".join(parts) if parts else str(loc[-1]) if loc else ""


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        # Malformed input (not valid JSON, a missing multipart part) is 400; a
        # well-formed body with bad field values is 422. A malformed path id is
        # indistinguishable from an unknown one and is reported as 404.
        if any(e.get("type") == "json_invalid" for e in errors):
            return error_response(400, ErrorCode.bad_request, "Request body is not valid JSON.")
        if any(tuple(e.get("loc", ()))[:1] == ("path",) for e in errors):
            return error_response(404, ErrorCode.not_found, "Not found.")
        content_type = request.headers.get("content-type", "")
        is_form = content_type.startswith(
            ("multipart/form-data", "application/x-www-form-urlencoded")
        )
        if is_form and any(e.get("type") == "missing" for e in errors):
            missing = [_field_path(tuple(e["loc"])) for e in errors if e.get("type") == "missing"]
            return error_response(
                400,
                ErrorCode.bad_request,
                "Missing multipart part(s): " + ", ".join(missing) + ".",
                {"fields": [{"field": f, "message": "Missing."} for f in missing]},
            )
        fields = [
            {"field": _field_path(tuple(e.get("loc", ()))), "message": str(e.get("msg", ""))}
            for e in errors
        ]
        return error_response(
            422,
            ErrorCode.validation_error,
            "One or more fields are invalid.",
            {"fields": fields},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.internal_error)
        status = exc.status_code if exc.status_code in _STATUS_TO_CODE else 500
        message = "Not found." if code is ErrorCode.not_found else str(exc.detail)
        headers = dict(exc.headers) if exc.headers else None
        return error_response(status, code, message, headers=headers)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = secrets.token_hex(4)
        # Never log request or response bodies (rule 6); the id is enough to correlate.
        log.exception(
            "unhandled error request_id=%s path=%s", request_id, redact_path(request.url.path)
        )
        return error_response(
            500,
            ErrorCode.internal_error,
            f"Something went wrong. Reference id {request_id}.",
            {"request_id": request_id},
        )
