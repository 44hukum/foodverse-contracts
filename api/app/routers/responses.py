"""Shared response declarations so the generated schema matches openapi.yaml."""

from __future__ import annotations

from typing import Any

from app.schemas.common import Error

INTERNAL: dict[int | str, dict[str, Any]] = {
    500: {"model": Error, "description": "Unexpected server error."}
}
UNAUTHORIZED: dict[int | str, dict[str, Any]] = {
    401: {"model": Error, "description": "Missing or invalid bearer token."}
}
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": Error, "description": "Resource not found."}
}
BAD_REQUEST: dict[int | str, dict[str, Any]] = {
    400: {"model": Error, "description": "Malformed request."}
}
VALIDATION: dict[int | str, dict[str, Any]] = {
    422: {"model": Error, "description": "Field validation failed."}
}
RATE_LIMITED: dict[int | str, dict[str, Any]] = {
    429: {"model": Error, "description": "Too many requests."}
}
INVALID_STATE: dict[int | str, dict[str, Any]] = {
    409: {"model": Error, "description": "Current status does not allow this action."}
}


def responses(*parts: dict[int | str, dict[str, Any]]) -> dict[int | str, dict[str, Any]]:
    merged: dict[int | str, dict[str, Any]] = {}
    for part in parts:
        merged.update(part)
    return merged
