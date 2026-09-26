"""Fixtures for the PDF module tests.

Sample PDFs and the signature PNG are generated in-process with reportlab and
Pillow so no binary fixtures are checked in (CLAUDE.md rule 6: no PDF bytes in
fixtures) and every property of a sample is visible in the code that makes it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4, landscape, letter
from reportlab.pdfgen import canvas

from app.pdf import AuditEvent, CertificateDetails

CONSENT_TEXT = (
    "I confirm that I am Sita Sharma, that I have read the document titled "
    '"Hotel Everest onboarding", and that I agree to sign it electronically. '
    "[v0-draft - pending legal review]"
)


def make_pdf(
    pages: int = 1,
    pagesize: tuple[float, float] = A4,
    *,
    fill_to_bottom: bool = False,
    rotate: int = 0,
) -> bytes:
    """A text-only PDF with ``pages`` pages, deterministic across runs."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=pagesize, invariant=1)
    _width, height = pagesize
    for number in range(1, pages + 1):
        pdf.setFont("Helvetica", 12)
        pdf.drawString(72, height - 72, f"Sample contract page {number} of {pages}")
        y = height - 100
        stop = 20 if fill_to_bottom else height / 2
        line = 0
        while y > stop:
            pdf.drawString(72, y, f"Clause {number}.{line}: lorem ipsum dolor sit amet.")
            y -= 14
            line += 1
        pdf.showPage()
    pdf.save()
    if not rotate:
        return buffer.getvalue()
    # A /Rotate entry, as scanners and print drivers produce it: the content
    # stays portrait, the viewer turns the page.
    writer = PdfWriter(clone_from=PdfReader(BytesIO(buffer.getvalue())))
    for page in writer.pages:
        page.rotate(rotate)
    rotated = BytesIO()
    writer.write(rotated)
    return rotated.getvalue()


def make_signature_png(size: tuple[int, int] = (600, 200), *, transparent: bool = True) -> bytes:
    image = Image.new("RGBA", size, (0, 0, 0, 0) if transparent else (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    w, h = size
    draw.line(
        [(w * 0.1, h * 0.7), (w * 0.4, h * 0.2), (w * 0.6, h * 0.8), (w * 0.9, h * 0.3)],
        fill=(10, 10, 120, 255),
        width=8,
    )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(scope="session")
def one_page_pdf() -> bytes:
    return make_pdf(1)


@pytest.fixture(scope="session")
def multi_page_pdf() -> bytes:
    return make_pdf(4)


@pytest.fixture(scope="session")
def landscape_pdf() -> bytes:
    return make_pdf(2, landscape(letter))


@pytest.fixture(scope="session")
def full_last_page_pdf() -> bytes:
    return make_pdf(2, fill_to_bottom=True)


@pytest.fixture(scope="session")
def rotated_pdf() -> bytes:
    return make_pdf(1, rotate=90)


@pytest.fixture(scope="session")
def signature_png() -> bytes:
    return make_signature_png()


@pytest.fixture
def certificate() -> CertificateDetails:
    return CertificateDetails(
        contract_id="0f8fad5b-d9cb-469f-a165-70867728950e",
        title="Hotel Everest onboarding",
        signer_name="Sita Sharma",
        signer_email="signer@example.com",
        signed_at=datetime(2026, 9, 28, 14, 22, 10, tzinfo=UTC),
        consent_text=CONSENT_TEXT,
        consent_text_version="v0-draft",
        link_sent_at=datetime(2026, 9, 20, 3, 0, 0, tzinfo=UTC),
        link_expires_at=datetime(2026, 10, 4, 3, 0, 0, tzinfo=UTC),
        signer_ip="203.0.113.7",
        signer_user_agent="Mozilla/5.0 (X11; Linux x86_64) Example/1.0",
    )


@pytest.fixture
def events() -> list[AuditEvent]:
    return [
        AuditEvent("contract.created", "admin", datetime(2026, 9, 20, 2, 58, 0, tzinfo=UTC)),
        AuditEvent("contract.sent", "admin", datetime(2026, 9, 20, 3, 0, 0, tzinfo=UTC)),
        AuditEvent("link.viewed", "signer", datetime(2026, 9, 28, 14, 20, 5, tzinfo=UTC)),
        AuditEvent("contract.signed", "signer", datetime(2026, 9, 28, 14, 22, 10, tzinfo=UTC)),
    ]
