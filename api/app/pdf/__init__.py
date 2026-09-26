"""PDF module: stamp the signature, append the certificate page, hash the result.

Public surface::

    from app.pdf import AuditEvent, CertificateDetails, PdfSigningError, SignedPdf, sign_pdf

``sign_pdf`` is a pure function of its arguments (FVR-8). It touches no
database, storage, network, or clock, and equal inputs produce byte-identical
output.
"""

from app.pdf.certificate import (
    CERTIFICATE_TEXT_VERSION,
    AuditEvent,
    CertificateDetails,
    DocumentFacts,
)
from app.pdf.errors import PdfSigningError
from app.pdf.image import (
    MAX_SIGNATURE_HEIGHT_PX,
    MAX_SIGNATURE_PNG_BYTES,
    MAX_SIGNATURE_WIDTH_PX,
)
from app.pdf.signing import SignedPdf, sha256_hex, sign_pdf
from app.pdf.timefmt import DEFAULT_DISPLAY_TIMEZONE, format_both, format_display, format_utc

__all__ = [
    "CERTIFICATE_TEXT_VERSION",
    "DEFAULT_DISPLAY_TIMEZONE",
    "MAX_SIGNATURE_HEIGHT_PX",
    "MAX_SIGNATURE_PNG_BYTES",
    "MAX_SIGNATURE_WIDTH_PX",
    "AuditEvent",
    "CertificateDetails",
    "DocumentFacts",
    "PdfSigningError",
    "SignedPdf",
    "format_both",
    "format_display",
    "format_utc",
    "sha256_hex",
    "sign_pdf",
]
