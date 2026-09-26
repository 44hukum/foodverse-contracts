from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class ErrorCode(enum.StrEnum):
    bad_request = "bad_request"
    unauthorized = "unauthorized"
    invalid_credentials = "invalid_credentials"
    not_found = "not_found"
    invalid_state = "invalid_state"
    link_expired = "link_expired"
    link_used = "link_used"
    contract_cancelled = "contract_cancelled"
    payload_too_large = "payload_too_large"
    unsupported_media_type = "unsupported_media_type"
    validation_error = "validation_error"
    rate_limited = "rate_limited"
    internal_error = "internal_error"


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None


class Error(BaseModel):
    error: ErrorBody


class ApiModel(BaseModel):
    """Base for response models built from ORM rows."""

    model_config = ConfigDict(from_attributes=True)
