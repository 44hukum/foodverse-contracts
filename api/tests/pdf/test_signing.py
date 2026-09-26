"""Behaviour of ``sign_pdf`` on 1-page, multi-page, landscape and edge-case PDFs."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4, landscape, letter

from app.pdf import (
    AuditEvent,
    CertificateDetails,
    PdfSigningError,
    SignedPdf,
    sign_pdf,
)
from app.pdf.certificate import FOOTER, HEADING
from tests.pdf.conftest import make_pdf, make_signature_png

TYPED_NAME = "Sita Sharma"
KATHMANDU_LINE = "2026-09-28 20:07:10 NPT (Asia/Kathmandu, UTC+05:45)"
UTC_LINE = "2026-09-28 14:22:10 UTC"


def _sign(
    pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
    **kwargs: object,
) -> SignedPdf:
    return sign_pdf(pdf, signature_png, TYPED_NAME, events, certificate, **kwargs)  # type: ignore[arg-type]


def _reader(signed: SignedPdf) -> PdfReader:
    return PdfReader(BytesIO(signed.pdf_bytes))


def _text(reader: PdfReader, index: int) -> str:
    # NFKC folds the ligatures HarfBuzz shaping produces ("fi" -> "fi").
    return unicodedata.normalize("NFKC", " ".join(reader.pages[index].extract_text().split()))


def _text_by_font(reader: PdfReader, index: int) -> dict[str, str]:
    """Text drawn on the page, keyed by the base font name that drew it."""
    drawn: dict[str, list[str]] = {}

    def visit(text: str, _cm: object, _tm: object, font: dict[str, object], _size: float) -> None:
        if text.strip():
            drawn.setdefault(str(font.get("/BaseFont", "")), []).append(text)

    reader.pages[index].extract_text(visitor_text=visit)
    return {font: "".join(parts) for font, parts in drawn.items()}


def _fonts_matching(by_font: dict[str, str], name: str) -> str:
    return "".join(text for font, text in by_font.items() if name in font)


@pytest.mark.parametrize(
    ("fixture_name", "original_pages"),
    [("one_page_pdf", 1), ("multi_page_pdf", 4), ("landscape_pdf", 2)],
)
def test_page_count_is_original_plus_one(
    fixture_name: str,
    original_pages: int,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
    request: pytest.FixtureRequest,
) -> None:
    original = request.getfixturevalue(fixture_name)
    assert len(PdfReader(BytesIO(original)).pages) == original_pages
    signed = _sign(original, signature_png, certificate, events)
    assert signed.page_count == original_pages + 1
    assert len(_reader(signed).pages) == original_pages + 1
    assert signed.signature_on_new_page is False


@pytest.mark.parametrize("fixture_name", ["one_page_pdf", "multi_page_pdf", "landscape_pdf"])
def test_hash_matches_bytes(
    fixture_name: str,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
    request: pytest.FixtureRequest,
) -> None:
    signed = _sign(request.getfixturevalue(fixture_name), signature_png, certificate, events)
    assert signed.sha256_hex == hashlib.sha256(signed.pdf_bytes).hexdigest()
    assert len(signed.sha256_hex) == 64
    assert signed.pdf_bytes.startswith(b"%PDF-")


@pytest.mark.parametrize("fixture_name", ["one_page_pdf", "multi_page_pdf", "landscape_pdf"])
def test_same_input_gives_same_hash(
    fixture_name: str,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
    request: pytest.FixtureRequest,
) -> None:
    original = request.getfixturevalue(fixture_name)
    first = _sign(original, signature_png, certificate, events)
    second = _sign(original, signature_png, certificate, events)
    assert first.pdf_bytes == second.pdf_bytes
    assert first.sha256_hex == second.sha256_hex


def test_different_input_gives_different_hash(
    one_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    base = _sign(one_page_pdf, signature_png, certificate, events)
    other_name = sign_pdf(one_page_pdf, signature_png, "Ram Thapa", events, certificate)
    other_time = _sign(
        one_page_pdf,
        signature_png,
        replace(certificate, signed_at=certificate.signed_at.replace(second=11)),
        events,
    )
    other_image = _sign(one_page_pdf, make_signature_png((300, 100)), certificate, events)
    hashes = {base.sha256_hex, other_name.sha256_hex, other_time.sha256_hex, other_image.sha256_hex}
    assert len(hashes) == 4


def test_signature_is_stamped_on_last_original_page(
    multi_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    signed = _sign(multi_page_pdf, signature_png, certificate, events)
    reader = _reader(signed)
    last = reader.pages[3]
    text = _text(reader, 3)
    assert "Sample contract page 4 of 4" in text  # original content still there
    assert f"Signed electronically by {TYPED_NAME}" in text
    assert KATHMANDU_LINE in text
    assert UTC_LINE in text
    assert certificate.contract_id in text
    assert len(last.images) == 1  # the drawn signature
    # earlier pages are untouched
    for index in range(3):
        assert "Signed electronically" not in _text(reader, index)
        assert len(reader.pages[index].images) == 0


def test_original_pages_keep_their_text(
    multi_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    original = PdfReader(BytesIO(multi_page_pdf))
    signed = _reader(_sign(multi_page_pdf, signature_png, certificate, events))
    for index in range(len(original.pages)):
        original_text = " ".join(original.pages[index].extract_text().split())
        assert original_text in _text(signed, index)


def test_landscape_page_keeps_its_orientation(
    landscape_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    signed = _reader(_sign(landscape_pdf, signature_png, certificate, events))
    width, height = landscape(letter)
    last_original = signed.pages[1]
    assert float(last_original.mediabox.width) == pytest.approx(width)
    assert float(last_original.mediabox.height) == pytest.approx(height)
    assert "Signed electronically" in _text(signed, 1)
    # the certificate is always A4 portrait
    cert = signed.pages[2]
    assert float(cert.mediabox.width) == pytest.approx(A4[0])
    assert float(cert.mediabox.height) == pytest.approx(A4[1])


def test_rotated_last_page_is_stamped_upright(
    rotated_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    signed = _sign(rotated_pdf, signature_png, certificate, events)
    reader = _reader(signed)
    assert signed.page_count == 2
    assert reader.pages[0].rotation == 0  # rotation baked into content, block drawn upright
    assert "Signed electronically" in _text(reader, 0)
    assert "Sample contract page 1 of 1" in _text(reader, 0)


def test_full_last_page_gets_signature_on_a_new_page(
    full_last_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    original_pages = len(PdfReader(BytesIO(full_last_page_pdf)).pages)
    signed = _sign(full_last_page_pdf, signature_png, certificate, events)
    reader = _reader(signed)
    assert signed.signature_on_new_page is True
    # No room on the last page: original + 2 (signature page, then certificate).
    assert signed.page_count == original_pages + 2
    assert len(reader.pages) == original_pages + 2
    assert "Signed electronically" not in _text(reader, 1)
    assert "Signed electronically" in _text(reader, 2)
    assert len(reader.pages[2].images) == 1
    assert HEADING in _text(reader, 3)
    # the new page matches the contract's page size, not the certificate's
    assert float(reader.pages[2].mediabox.width) == pytest.approx(A4[0])


def test_certificate_page_contents_in_spec_order(
    one_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    signed = _sign(one_page_pdf, signature_png, certificate, events)
    text = _text(_reader(signed), 1)
    original_sha = hashlib.sha256(one_page_pdf).hexdigest()

    expected_in_order = [
        HEADING,
        certificate.contract_id,
        certificate.title,
        original_sha,
        "Pages 1",
        f"{len(one_page_pdf):,} bytes",
        certificate.signer_name,
        TYPED_NAME,
        certificate.signer_email,
        KATHMANDU_LINE,
        UTC_LINE,
        "2026-09-20 08:45:00 NPT (Asia/Kathmandu, UTC+05:45)",  # link sent
        "2026-09-20 03:00:00 UTC",
        "2026-10-04 08:45:00 NPT (Asia/Kathmandu, UTC+05:45)",  # link expiry
        "2026-10-04 03:00:00 UTC",
        "203.0.113.7",
        "Mozilla/5.0 (X11; Linux x86_64) Example/1.0",
        "Consent text (version v0-draft)",
        "I confirm that I am Sita Sharma",
        "Audit trail",
        "contract.created",
        "contract.sent",
        "link.viewed",
        "contract.signed",
        "2026-09-28 20:07:10 NPT",
        "Generated by Foodverse Contract Signing",
        "Certificate wording version v0-draft",
    ]
    position = -1
    for needle in expected_in_order:
        found = text.find(needle, position + 1)
        assert found > position, f"{needle!r} missing or out of order"
        position = found
    assert " ".join(FOOTER.split()) in text
    # the final hash cannot be inside the file it hashes
    assert signed.sha256_hex not in text


def test_certificate_marks_missing_optional_facts(
    one_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
) -> None:
    sparse = replace(
        certificate,
        link_sent_at=None,
        link_expires_at=None,
        signer_ip=None,
        signer_user_agent=None,
    )
    text = _text(_reader(_sign(one_page_pdf, signature_png, sparse, [])), 1)
    assert text.count("not recorded") == 5  # sent, expiry, ip, user agent, events


def test_certificate_escapes_markup_in_user_text(
    one_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    hostile = replace(
        certificate,
        title="<b>bold</b> & <font color='red'>red</font>",
        signer_user_agent="<script>alert(1)</script>",
    )
    signed = sign_pdf(one_page_pdf, signature_png, "<i>Sita</i>", events, hostile)
    text = _text(_reader(signed), 1)
    assert "<b>bold</b> & <font color='red'>red</font>" in text
    assert "<script>alert(1)</script>" in text
    assert "<i>Sita</i>" in text


def test_long_event_trail_spills_to_extra_certificate_pages(
    one_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
) -> None:
    many = [
        AuditEvent("link.viewed", "signer", datetime(2026, 9, 21, 0, 0, i % 60, tzinfo=UTC))
        for i in range(120)
    ]
    signed = _sign(one_page_pdf, signature_png, certificate, many)
    reader = _reader(signed)
    assert signed.page_count > 2
    assert HEADING in _text(reader, 1)
    assert "Certificate wording version" in _text(reader, signed.page_count - 1)


def test_display_timezone_is_configurable(
    one_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    signed = _sign(
        one_page_pdf, signature_png, certificate, events, display_timezone="Europe/Paris"
    )
    reader = _reader(signed)
    assert "2026-09-28 16:22:10 CEST (Europe/Paris, UTC+02:00)" in _text(reader, 0)
    assert UTC_LINE in _text(reader, 1)


def test_producer_metadata_and_no_original_dates_added(
    one_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    metadata = _reader(_sign(one_page_pdf, signature_png, certificate, events)).metadata
    assert metadata is not None
    assert metadata.producer == "Foodverse Contract Signing"


def test_owner_password_only_pdf_is_accepted(
    one_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    writer = PdfWriter(clone_from=PdfReader(BytesIO(one_page_pdf)))
    writer.encrypt(user_password="", owner_password="owner-only", algorithm="AES-256")
    out = BytesIO()
    writer.write(out)
    signed = _sign(out.getvalue(), signature_png, certificate, events)
    assert signed.page_count == 2
    assert not _reader(signed).is_encrypted


def test_user_password_pdf_is_rejected(
    one_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    writer = PdfWriter(clone_from=PdfReader(BytesIO(one_page_pdf)))
    writer.encrypt(user_password="secret-user-password", algorithm="AES-256")
    out = BytesIO()
    writer.write(out)
    with pytest.raises(PdfSigningError, match="password protected"):
        _sign(out.getvalue(), signature_png, certificate, events)


@pytest.mark.parametrize(
    "bad_pdf", [b"", b"not a pdf at all", b"%PDF-1.7\n%%EOF\n", b"%PDF-" + b"\x00" * 100]
)
def test_unreadable_pdf_is_rejected(
    bad_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    with pytest.raises(PdfSigningError):
        _sign(bad_pdf, signature_png, certificate, events)


def test_bad_signature_image_is_rejected(
    one_page_pdf: bytes, certificate: CertificateDetails, events: list[AuditEvent]
) -> None:
    with pytest.raises(PdfSigningError, match="PNG"):
        _sign(one_page_pdf, b"GIF89a", certificate, events)


def test_blank_typed_name_is_rejected(
    one_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    with pytest.raises(PdfSigningError, match="typed name"):
        sign_pdf(one_page_pdf, signature_png, "   ", events, certificate)


def test_naive_datetimes_are_rejected(
    one_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    naive = replace(certificate, signed_at=datetime(2026, 9, 28, 14, 22, 10))
    with pytest.raises(ValueError, match="signed_at"):
        _sign(one_page_pdf, signature_png, naive, events)
    naive_event = [AuditEvent("contract.sent", "admin", datetime(2026, 9, 20, 3, 0, 0))]
    with pytest.raises(ValueError, match="occurred_at"):
        _sign(one_page_pdf, signature_png, certificate, naive_event)


def test_signature_png_bytes_are_not_embedded_verbatim(
    one_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    """The image is decoded and re-encoded (SPEC.md §7), never copied through."""
    signed = _sign(one_page_pdf, signature_png, certificate, events)
    assert signature_png not in signed.pdf_bytes


def test_devanagari_typed_name_renders_with_devanagari_glyphs(
    one_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    typed = "\u0938\u0940\u0924\u093e \u0936\u0930\u094d\u092e\u093e"  # सीता शर्मा
    named = replace(certificate, signer_name=typed, title="\u0939\u094b\u091f\u0932 onboarding")
    signed = sign_pdf(one_page_pdf, signature_png, typed, events, named)
    reader = _reader(signed)
    for page in (0, 1):
        by_font = _text_by_font(reader, page)
        devanagari = _fonts_matching(by_font, "NotoSansDevanagari")
        latin = _fonts_matching(by_font, "NotoSans")
        # every Devanagari letter of the name was drawn from the Devanagari font ...
        for char in "\u0938\u0940\u0924\u093e\u0936\u092e":
            assert char in devanagari, (
                f"{char!r} not drawn with Noto Sans Devanagari on page {page}"
            )
        # ... and no Devanagari was sent to a font that cannot draw it
        assert not any("\u0900" <= c <= "\u097f" for c in latin.replace(devanagari, ""))
        assert "\ufffd" not in devanagari
    assert "Signed electronically by" in _fonts_matching(_text_by_font(reader, 0), "NotoSans-Bold")
    assert "Signature Certificate" in _text(reader, 1)


def test_mixed_script_name_switches_fonts_per_run(
    one_page_pdf: bytes,
    signature_png: bytes,
    certificate: CertificateDetails,
    events: list[AuditEvent],
) -> None:
    sharma = "\u0936\u0930\u094d\u092e\u093e"  # शर्मा
    typed = f"Sita {sharma} Sharma"
    signed = sign_pdf(one_page_pdf, signature_png, typed, events, certificate)
    reader = _reader(signed)
    # Signature block: bold faces of both fonts, Latin parts in Noto Sans Bold.
    block = _text_by_font(reader, 0)
    assert "Signed electronically by Sita " in _fonts_matching(block, "NotoSans-Bold")
    assert "Sharma" in _fonts_matching(block, "NotoSans-Bold")
    for char in "\u0936\u092e\u093e":
        assert char in _fonts_matching(block, "NotoSansDevanagari-Bold")
    # Certificate: regular faces, same split.
    cert = _text_by_font(reader, 1)
    assert "Sita " in _fonts_matching(cert, "NotoSans")
    for char in "\u0936\u092e\u093e":
        assert char in _fonts_matching(cert, "NotoSansDevanagari")
    assert "Sita" in _text(reader, 0) and "Sharma" in _text(reader, 0)


def test_small_page_still_gets_a_block(
    signature_png: bytes, certificate: CertificateDetails, events: list[AuditEvent]
) -> None:
    tiny = make_pdf(1, (200, 300))
    signed = _sign(tiny, signature_png, certificate, events)
    assert "Signed electronically" in _text(_reader(signed), 0)
