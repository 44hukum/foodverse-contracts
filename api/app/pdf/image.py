"""Signature image validation and re-encoding (SPEC.md §7 "Signature image").

The drawn signature is accepted only as PNG, decoded, and re-encoded before it
touches the PDF so that any payload hidden in ancillary chunks or metadata is
dropped. The limits here mirror the spec and must not be relaxed (CLAUDE.md
rule 9); the HTTP layer enforces the same limits earlier, this is the last line.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, UnidentifiedImageError

from app.pdf.errors import PdfSigningError

MAX_SIGNATURE_PNG_BYTES = 500 * 1024
MAX_SIGNATURE_WIDTH_PX = 2000
MAX_SIGNATURE_HEIGHT_PX = 1000

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def decode_signature_png(data: bytes) -> Image.Image:
    """Validate ``data`` as a signature PNG and return a clean RGBA copy of it."""
    if len(data) > MAX_SIGNATURE_PNG_BYTES:
        msg = f"signature image exceeds {MAX_SIGNATURE_PNG_BYTES} bytes"
        raise PdfSigningError(msg)
    if not data.startswith(_PNG_MAGIC):
        msg = "signature image is not a PNG"
        raise PdfSigningError(msg)
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format != "PNG":
                msg = "signature image is not a PNG"
                raise PdfSigningError(msg)
            width, height = source.size
            if width > MAX_SIGNATURE_WIDTH_PX or height > MAX_SIGNATURE_HEIGHT_PX:
                msg = (
                    "signature image exceeds "
                    f"{MAX_SIGNATURE_WIDTH_PX}x{MAX_SIGNATURE_HEIGHT_PX} pixels"
                )
                raise PdfSigningError(msg)
            if width == 0 or height == 0:
                msg = "signature image is empty"
                raise PdfSigningError(msg)
            rgba = source.convert("RGBA")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        if isinstance(exc, PdfSigningError):
            raise
        msg = "signature image could not be decoded"
        raise PdfSigningError(msg) from exc

    # Re-encode from raw pixels: only the pixel data survives.
    clean = Image.frombytes("RGBA", rgba.size, rgba.tobytes())
    buffer = BytesIO()
    clean.save(buffer, format="PNG", optimize=False)
    buffer.seek(0)
    reencoded = Image.open(buffer)
    reencoded.load()
    return reencoded
