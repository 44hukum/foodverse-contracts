from io import BytesIO

import pytest
from PIL import Image, PngImagePlugin

from app.pdf import (
    MAX_SIGNATURE_HEIGHT_PX,
    MAX_SIGNATURE_PNG_BYTES,
    MAX_SIGNATURE_WIDTH_PX,
    PdfSigningError,
)
from app.pdf.image import decode_signature_png
from tests.pdf.conftest import make_signature_png


def test_valid_png_is_returned_as_rgba(signature_png: bytes) -> None:
    image = decode_signature_png(signature_png)
    assert image.mode == "RGBA"
    assert image.size == (600, 200)


def test_reencoding_drops_metadata_chunks() -> None:
    source = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "<script>alert(1)</script>")
    buffer = BytesIO()
    source.save(buffer, format="PNG", pnginfo=info)
    clean = decode_signature_png(buffer.getvalue())
    assert "Comment" not in clean.info


def test_jpeg_is_rejected() -> None:
    buffer = BytesIO()
    Image.new("RGB", (40, 20), (255, 255, 255)).save(buffer, format="JPEG")
    with pytest.raises(PdfSigningError, match="not a PNG"):
        decode_signature_png(buffer.getvalue())


def test_png_magic_with_garbage_body_is_rejected() -> None:
    with pytest.raises(PdfSigningError, match="could not be decoded"):
        decode_signature_png(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)


def test_empty_bytes_are_rejected() -> None:
    with pytest.raises(PdfSigningError):
        decode_signature_png(b"")


def test_oversized_dimensions_are_rejected() -> None:
    too_wide = make_signature_png((MAX_SIGNATURE_WIDTH_PX + 1, 10))
    too_tall = make_signature_png((10, MAX_SIGNATURE_HEIGHT_PX + 1))
    with pytest.raises(PdfSigningError, match="pixels"):
        decode_signature_png(too_wide)
    with pytest.raises(PdfSigningError, match="pixels"):
        decode_signature_png(too_tall)


def test_maximum_dimensions_are_accepted() -> None:
    image = decode_signature_png(
        make_signature_png((MAX_SIGNATURE_WIDTH_PX, MAX_SIGNATURE_HEIGHT_PX))
    )
    assert image.size == (MAX_SIGNATURE_WIDTH_PX, MAX_SIGNATURE_HEIGHT_PX)


def test_oversized_file_is_rejected_before_decoding() -> None:
    padded = make_signature_png() + b"\x00" * MAX_SIGNATURE_PNG_BYTES
    with pytest.raises(PdfSigningError, match="bytes"):
        decode_signature_png(padded)
