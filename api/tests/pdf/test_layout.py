"""The "is there room on the last page" heuristic."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.pdf.image import decode_signature_png
from app.pdf.layout import band_is_clear, content_extents
from app.pdf.stamp import block_band
from tests.pdf.conftest import make_pdf, make_signature_png


def _page(draw: object) -> PdfReader:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4, invariant=1)
    draw(pdf)  # type: ignore[operator]
    pdf.showPage()
    pdf.save()
    return PdfReader(BytesIO(buffer.getvalue()))


def test_blank_page_is_clear() -> None:
    page = _page(lambda pdf: None).pages[0]
    assert content_extents(page) == []
    assert band_is_clear(page, *block_band(0.0))


def test_text_in_the_band_blocks() -> None:
    low, high = block_band(0.0)
    page = _page(lambda pdf: pdf.drawString(72, (low + high) / 2, "Signature: ______")).pages[0]
    assert not band_is_clear(page, low, high)


def test_text_above_the_band_does_not_block() -> None:
    low, high = block_band(0.0)
    page = _page(lambda pdf: pdf.drawString(72, high + 30, "Clause 12")).pages[0]
    assert band_is_clear(page, low, high)


def test_page_number_just_below_the_band_does_not_block() -> None:
    low, high = block_band(0.0)

    def draw(pdf: canvas.Canvas) -> None:
        pdf.setFont("Helvetica", 8)
        pdf.drawString(300, low - 14, "3")

    page = _page(draw).pages[0]
    assert band_is_clear(page, low, high)


def test_page_border_around_the_band_does_not_block() -> None:
    low, high = block_band(0.0)
    page = _page(lambda pdf: pdf.rect(15, 15, A4[0] - 30, A4[1] - 30, stroke=1, fill=0)).pages[0]
    assert band_is_clear(page, low, high)


def test_horizontal_rule_in_the_band_blocks() -> None:
    low, high = block_band(0.0)
    page = _page(lambda pdf: pdf.line(72, low + 20, 300, low + 20)).pages[0]
    assert not band_is_clear(page, low, high)


def test_full_page_image_blocks() -> None:
    image = decode_signature_png(make_signature_png((400, 400)))
    page = _page(lambda pdf: pdf.drawImage(ImageReader(image), 0, 0, *A4, mask="auto")).pages[0]
    assert not band_is_clear(page, *block_band(0.0))


def test_logo_in_the_header_does_not_block() -> None:
    image = decode_signature_png(make_signature_png((100, 40)))
    page = _page(
        lambda pdf: pdf.drawImage(ImageReader(image), 72, A4[1] - 100, 100, 40, mask="auto")
    ).pages[0]
    assert band_is_clear(page, *block_band(0.0))


def test_fixture_with_text_to_the_bottom_is_not_clear() -> None:
    page = PdfReader(BytesIO(make_pdf(1, fill_to_bottom=True))).pages[0]
    assert not band_is_clear(page, *block_band(0.0))


def test_fixture_with_half_page_of_text_is_clear() -> None:
    page = PdfReader(BytesIO(make_pdf(1))).pages[0]
    assert band_is_clear(page, *block_band(0.0))
