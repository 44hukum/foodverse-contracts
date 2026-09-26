"""Turn an uploaded contract plus a drawn signature into the final signed PDF.

Pure function: no database, no storage, no clock. Everything that ends up in
the document comes in as an argument, so equal inputs give byte-identical
output and therefore the same SHA-256. That property is what lets the stored
``final_pdf_sha256`` be re-checked by anyone holding a copy (SPEC.md §7).

Steps, matching SPEC.md §4 step 7:

1. validate and re-encode the signature PNG;
2. stamp the signature block on the last page, or on a new page if the last
   page has no room (see ``app.pdf.layout``);
3. append the Signature Certificate page(s);
4. hash the result.

The certificate carries the *original* PDF's hash; the final hash cannot be
inside the file it hashes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.errors import PyPdfError

from app.pdf.certificate import (
    CERTIFICATE_TEXT_VERSION,
    AuditEvent,
    CertificateDetails,
    DocumentFacts,
    render_certificate,
)
from app.pdf.errors import PdfSigningError
from app.pdf.image import decode_signature_png
from app.pdf.layout import band_is_clear
from app.pdf.stamp import block_band, render_signature_block
from app.pdf.timefmt import DEFAULT_DISPLAY_TIMEZONE, require_aware

PRODUCER = "Foodverse Contract Signing"
_PDF_MAGIC = b"%PDF-"


@dataclass(frozen=True, slots=True)
class SignedPdf:
    """The stamped document and the facts the caller persists about it."""

    pdf_bytes: bytes
    sha256_hex: str
    page_count: int
    signature_on_new_page: bool
    """True when the last page had no room and the block went on a page of its own."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _open_original(original_pdf: bytes) -> PdfReader:
    if not original_pdf.lstrip().startswith(_PDF_MAGIC):
        msg = "original document is not a PDF"
        raise PdfSigningError(msg)
    try:
        reader = PdfReader(BytesIO(original_pdf), strict=False)
        # Owner-password-only files open with an empty user password.
        if reader.is_encrypted and reader.decrypt("") == 0:
            msg = "original PDF is password protected"
            raise PdfSigningError(msg)
        page_count = len(reader.pages)
    except PdfSigningError:
        raise
    except (PyPdfError, ValueError, TypeError, KeyError, OSError) as exc:
        msg = "original PDF could not be read"
        raise PdfSigningError(msg) from exc
    if page_count == 0:
        msg = "original PDF has no pages"
        raise PdfSigningError(msg)
    return reader


def sign_pdf(
    original_pdf: bytes,
    signature_png: bytes,
    typed_name: str,
    events: Sequence[AuditEvent],
    certificate: CertificateDetails,
    *,
    display_timezone: str = DEFAULT_DISPLAY_TIMEZONE,
    certificate_text_version: str = CERTIFICATE_TEXT_VERSION,
) -> SignedPdf:
    """Stamp ``signature_png`` and ``typed_name`` on ``original_pdf`` and certify it.

    Raises ``PdfSigningError`` for unusable inputs and ``ValueError`` for naive
    datetimes. Never logs or embeds anything beyond what the certificate shows.
    """
    typed_name = typed_name.strip()
    if not typed_name:
        msg = "typed name must not be blank"
        raise PdfSigningError(msg)
    require_aware(certificate.signed_at, "signed_at")
    for label, value in (
        ("link_sent_at", certificate.link_sent_at),
        ("link_expires_at", certificate.link_expires_at),
    ):
        if value is not None:
            require_aware(value, label)
    for event in events:
        require_aware(event.occurred_at, "event.occurred_at")

    signature = decode_signature_png(signature_png)
    reader = _open_original(original_pdf)
    facts = DocumentFacts(
        original_sha256=sha256_hex(original_pdf),
        page_count=len(reader.pages),
        size_bytes=len(original_pdf),
    )

    try:
        writer = PdfWriter(clone_from=reader)
        last = writer.pages[-1]
        if last.rotation % 360:
            last.transfer_rotation_to_content()
        box = last.cropbox
        left, bottom = float(box.left), float(box.bottom)
        width, height = float(box.width), float(box.height)

        block_pdf = render_signature_block(
            width,
            height,
            signature,
            typed_name,
            certificate.signed_at,
            certificate.contract_id,
            display_timezone,
        )
        block_page = PdfReader(BytesIO(block_pdf)).pages[0]
        low, high = block_band(bottom)
        on_new_page = not band_is_clear(last, low, high)
        if on_new_page:
            writer.add_page(block_page)
        else:
            last.merge_transformed_page(block_page, Transformation().translate(left, bottom))

        certificate_pdf = render_certificate(
            certificate,
            typed_name,
            facts,
            events,
            display_timezone,
            certificate_text_version,
        )
        for page in PdfReader(BytesIO(certificate_pdf)).pages:
            writer.add_page(page)

        writer.add_metadata({"/Producer": PRODUCER})
        output = BytesIO()
        writer.write(output)
    except (PyPdfError, ValueError, TypeError, KeyError, OSError) as exc:
        msg = "original PDF could not be stamped"
        raise PdfSigningError(msg) from exc

    pdf_bytes = output.getvalue()
    return SignedPdf(
        pdf_bytes=pdf_bytes,
        sha256_hex=sha256_hex(pdf_bytes),
        page_count=len(writer.pages),
        signature_on_new_page=on_new_page,
    )
