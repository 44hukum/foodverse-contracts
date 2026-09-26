"""The signature block stamped on the contract's last page."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.pdf.timefmt import DEFAULT_DISPLAY_TIMEZONE, format_both

BLOCK_MARGIN = 36.0  # distance from the page's bottom and left edge, in points
BLOCK_HEIGHT = 110.0
BLOCK_MAX_WIDTH = 360.0
BLOCK_GAP = 10.0  # clearance required above and below the block
IMAGE_MAX_WIDTH = 180.0
IMAGE_MAX_HEIGHT = 46.0

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


def block_band(bottom: float) -> tuple[float, float]:
    """Vertical band the block needs free on a page whose visible bottom is ``bottom``."""
    low = bottom + BLOCK_MARGIN - BLOCK_GAP
    return low, low + BLOCK_HEIGHT + 2 * BLOCK_GAP


def _fit(
    pdf: canvas.Canvas, text: str, font: str, size: float, max_width: float
) -> tuple[str, float]:
    """Shrink the font (down to 6 pt), then truncate with an ellipsis, so ``text`` fits."""
    while size > 6 and pdf.stringWidth(text, font, size) > max_width:
        size -= 0.5
    if pdf.stringWidth(text, font, size) <= max_width:
        return text, size
    while text and pdf.stringWidth(text + "…", font, size) > max_width:
        text = text[:-1]
    return text + "…", size


def render_signature_block(
    page_width: float,
    page_height: float,
    signature: Image.Image,
    typed_name: str,
    signed_at: datetime,
    contract_id: str,
    tz_name: str = DEFAULT_DISPLAY_TIMEZONE,
) -> bytes:
    """A one-page PDF of ``page_width`` x ``page_height`` carrying only the block.

    The caller either merges it onto the contract's last page or appends it as
    a page of its own. Output is byte-for-byte reproducible for equal inputs
    (``invariant`` canvas, no timestamps or random ids).
    """
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(page_width, page_height), invariant=1)
    pdf.setTitle("signature block")

    x0, y0 = BLOCK_MARGIN, BLOCK_MARGIN
    width = max(min(BLOCK_MAX_WIDTH, page_width - 2 * BLOCK_MARGIN), 120.0)
    inner = width - 16

    pdf.setStrokeColor(colors.HexColor("#9a9a9a"))
    pdf.setLineWidth(0.6)
    pdf.rect(x0, y0, width, BLOCK_HEIGHT, stroke=1, fill=0)

    # Signature image, scaled to fit, top-left inside the box.
    img_w, img_h = signature.size
    scale = min(IMAGE_MAX_WIDTH / img_w, IMAGE_MAX_HEIGHT / img_h, 1.0)
    draw_w, draw_h = img_w * scale, img_h * scale
    img_y = y0 + BLOCK_HEIGHT - 8 - IMAGE_MAX_HEIGHT + (IMAGE_MAX_HEIGHT - draw_h) / 2
    pdf.drawImage(ImageReader(signature), x0 + 8, img_y, draw_w, draw_h, mask="auto")

    rule_y = y0 + BLOCK_HEIGHT - 8 - IMAGE_MAX_HEIGHT - 4
    pdf.setStrokeColor(colors.HexColor("#333333"))
    pdf.line(x0 + 8, rule_y, x0 + width - 8, rule_y)

    pdf.setFillColor(colors.black)
    line, size = _fit(pdf, f"Signed electronically by {typed_name}", _FONT_BOLD, 9, inner)
    pdf.setFont(_FONT_BOLD, size)
    pdf.drawString(x0 + 8, rule_y - 12, line)

    local_line, utc_line = format_both(signed_at, tz_name)
    for offset, text in ((22, local_line), (31, utc_line)):
        line, size = _fit(pdf, text, _FONT, 7.5, inner)
        pdf.setFont(_FONT, size)
        pdf.drawString(x0 + 8, rule_y - offset, line)

    pdf.setFillColor(colors.HexColor("#555555"))
    line, size = _fit(
        pdf, f"Contract {contract_id} - see the Signature Certificate page", _FONT, 6.5, inner
    )
    pdf.setFont(_FONT, size)
    pdf.drawString(x0 + 8, y0 + 6, line)

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
