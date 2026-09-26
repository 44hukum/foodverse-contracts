"""Errors raised by the PDF module."""


class PdfSigningError(ValueError):
    """The inputs cannot be turned into a signed PDF.

    Raised for a malformed or encrypted PDF, a signature image that is not a
    valid PNG within the SPEC.md §7 limits, or missing certificate data. The
    message never contains the document or image bytes.
    """
