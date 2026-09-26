"""Bundled Noto fonts and per-script font runs for user-entered text.

reportlab embeds one TrueType font per text run and does no fallback of its
own, and Noto Sans Devanagari carries no Latin letters. So user text (names,
titles, email, user agent, consent text) is split into runs by script:
Devanagari characters go to Noto Sans Devanagari, everything else to Noto
Sans, and neutral characters (spaces, digits, punctuation, combining marks,
joiners) stay with the run they follow. Each run is drawn with HarfBuzz
shaping (``uharfbuzz`` through reportlab) so conjuncts and pre-base vowel
signs come out right.

Licences: SIL OFL 1.1, see ``fonts/README.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.pdfgen.textobject import bidiShapedText

FONTS_DIR = Path(__file__).parent / "fonts"

LATIN = "NotoSans"
LATIN_BOLD = "NotoSans-Bold"
DEVANAGARI = "NotoSansDevanagari"
DEVANAGARI_BOLD = "NotoSansDevanagari-Bold"

_FILES: dict[str, str] = {
    LATIN: "NotoSans-Regular.ttf",
    LATIN_BOLD: "NotoSans-Bold.ttf",
    DEVANAGARI: "NotoSansDevanagari-Regular.ttf",
    DEVANAGARI_BOLD: "NotoSansDevanagari-Bold.ttf",
}
_BOLD: dict[str, str] = {LATIN: LATIN_BOLD, DEVANAGARI: DEVANAGARI_BOLD}

# Devanagari, Devanagari Extended, Vedic Extensions.
_DEVANAGARI_RANGES = ((0x0900, 0x097F), (0xA8E0, 0xA8FF), (0x1CD0, 0x1CFF))


def register_fonts() -> None:
    """Register the bundled fonts with reportlab once per process. Idempotent."""
    registered = set(pdfmetrics.getRegisteredFontNames())
    for name, filename in _FILES.items():
        if name not in registered:
            pdfmetrics.registerFont(TTFont(name, str(FONTS_DIR / filename), shapable=True))
    pdfmetrics.registerFontFamily(LATIN, normal=LATIN, bold=LATIN_BOLD)
    pdfmetrics.registerFontFamily(DEVANAGARI, normal=DEVANAGARI, bold=DEVANAGARI_BOLD)


def _script(char: str) -> str | None:
    """``DEVANAGARI``, ``LATIN`` (any other letter), or None for neutral characters."""
    code = ord(char)
    if any(low <= code <= high for low, high in _DEVANAGARI_RANGES):
        return DEVANAGARI
    if char.isalpha():
        return LATIN
    return None


@dataclass(frozen=True, slots=True)
class Run:
    font: str
    text: str


def script_runs(text: str, *, bold: bool = False) -> list[Run]:
    """Split ``text`` into maximal runs that one bundled font can draw."""
    if not text:
        return []
    scripts = [_script(char) for char in text]
    # Neutral characters take the script of what precedes them, else what
    # follows, else Latin.
    previous: str | None = None
    for index, script in enumerate(scripts):
        if script is None:
            scripts[index] = previous
        else:
            previous = script
    following: str | None = None
    for index in range(len(scripts) - 1, -1, -1):
        if scripts[index] is None:
            scripts[index] = following or LATIN
        else:
            following = scripts[index]

    runs: list[Run] = []
    start = 0
    for index in range(1, len(text) + 1):
        if index == len(text) or scripts[index] != scripts[start]:
            font = scripts[start] or LATIN
            runs.append(Run(_BOLD[font] if bold else font, text[start:index]))
            start = index
    return runs


def _shaped_width(text: str, font: str, size: float) -> float:
    """Advance width of ``text`` after HarfBuzz shaping, in points."""
    # The stub types fontSize as int and the width as bool; both are wrong.
    shaped: Any = bidiShapedText(text, "LTR", fontName=font, fontSize=size, shaping=True)  # type: ignore[arg-type]
    return float(shaped[1])


def string_width(text: str, size: float, *, bold: bool = False) -> float:
    """Width of ``text`` in points when drawn with ``draw_string``."""
    register_fonts()
    return sum(_shaped_width(run.text, run.font, size) for run in script_runs(text, bold=bold))


def draw_string(
    pdf: canvas.Canvas, x: float, y: float, text: str, size: float, *, bold: bool = False
) -> float:
    """Draw ``text`` at ``(x, y)`` switching fonts per script. Returns the width drawn."""
    register_fonts()
    start = x
    for run in script_runs(text, bold=bold):
        pdf.setFont(run.font, size)
        pdf.drawString(x, y, run.text, shaping=True)
        x += _shaped_width(run.text, run.font, size)
    return x - start


def paragraph_markup(text: str, *, bold: bool = False) -> str:
    """``text`` escaped for a reportlab Paragraph, with a ``<font>`` tag per script run."""
    register_fonts()
    return "".join(
        f'<font name="{run.font}">{escape(run.text)}</font>' for run in script_runs(text, bold=bold)
    )
