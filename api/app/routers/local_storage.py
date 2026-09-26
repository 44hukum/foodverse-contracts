"""Download route for the ``local`` storage backend.

Not part of the API surface in openapi.yaml (excluded from the schema). It is
mounted only when ``STORAGE_BACKEND=local`` and serves a file only for a
valid, unexpired HMAC signature (SPEC.md §6). Anything else is a 404.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.errors import not_found
from app.services.storage import LocalStorage

router = APIRouter(include_in_schema=False)


@router.get("/_storage/local/{key:path}")
async def local_download(
    request: Request, key: str, exp: str = "", sig: str = "", filename: str | None = None
) -> FileResponse:
    storage = request.app.state.storage
    if not isinstance(storage, LocalStorage):
        raise not_found()
    path = storage.verify(key, exp, sig)
    if path is None:
        raise not_found()
    safe_name = "".join(c for c in (filename or path.name) if c.isalnum() or c in "-_.") or "file"
    return FileResponse(
        path,
        media_type="application/pdf" if path.suffix == ".pdf" else "application/octet-stream",
        filename=safe_name,
        headers={"Cache-Control": "private, no-store"},
    )
