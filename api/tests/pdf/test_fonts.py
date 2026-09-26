"""Per-script font runs for the bundled Noto fonts."""

from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from app.pdf.fonts import (
    DEVANAGARI,
    DEVANAGARI_BOLD,
    FONTS_DIR,
    LATIN,
    LATIN_BOLD,
    Run,
    draw_string,
    paragraph_markup,
    register_fonts,
    script_runs,
    string_width,
)

SITA = "सीता"  # सीता
SHARMA = "शर्मा"  # शर्मा


def test_bundled_files_and_licences_are_present() -> None:
    for name in (
        "NotoSans-Regular.ttf",
        "NotoSans-Bold.ttf",
        "NotoSansDevanagari-Regular.ttf",
        "NotoSansDevanagari-Bold.ttf",
        "OFL-NotoSans.txt",
        "OFL-NotoSansDevanagari.txt",
    ):
        assert (FONTS_DIR / name).is_file(), name
    for licence in ("OFL-NotoSans.txt", "OFL-NotoSansDevanagari.txt"):
        assert "SIL Open Font License, Version 1.1" in (FONTS_DIR / licence).read_text()


def test_register_is_idempotent_and_shapable() -> None:
    register_fonts()
    register_fonts()
    for name in (LATIN, LATIN_BOLD, DEVANAGARI, DEVANAGARI_BOLD):
        assert name in pdfmetrics.getRegisteredFontNames()
        assert pdfmetrics.getFont(name).shapable


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []),
        ("Sita Sharma", [Run(LATIN, "Sita Sharma")]),
        (f"{SITA} {SHARMA}", [Run(DEVANAGARI, f"{SITA} {SHARMA}")]),
        (
            f"Sita {SHARMA} Sharma",
            [Run(LATIN, "Sita "), Run(DEVANAGARI, f"{SHARMA} "), Run(LATIN, "Sharma")],
        ),
        # neutral characters at the start take the script that follows
        (f"12. {SITA}", [Run(DEVANAGARI, f"12. {SITA}")]),
        ("12.", [Run(LATIN, "12.")]),
        # joiners and digits stay with the preceding run
        (f"{SITA}‍2 ok", [Run(DEVANAGARI, f"{SITA}‍2 "), Run(LATIN, "ok")]),
        # other scripts fall back to Noto Sans rather than the Devanagari font
        ("Zoë Ñandú", [Run(LATIN, "Zoë Ñandú")]),
    ],
)
def test_script_runs(text: str, expected: list[Run]) -> None:
    assert script_runs(text) == expected


def test_bold_runs_use_bold_faces() -> None:
    assert script_runs(f"A {SITA}", bold=True) == [
        Run(LATIN_BOLD, "A "),
        Run(DEVANAGARI_BOLD, SITA),
    ]


def test_paragraph_markup_tags_each_run_and_escapes() -> None:
    markup = paragraph_markup(f"<b>&{SITA}")
    assert (
        markup
        == f'<font name="{LATIN}">&lt;b&gt;&amp;</font><font name="{DEVANAGARI}">{SITA}</font>'
    )


def test_string_width_is_positive_and_additive() -> None:
    latin = string_width("Sita ", 9)
    devanagari = string_width(SHARMA, 9)
    assert latin > 0 and devanagari > 0
    assert string_width(f"Sita {SHARMA}", 9) == pytest.approx(latin + devanagari)
    assert string_width("Sita", 18) == pytest.approx(2 * string_width("Sita", 9))


def test_draw_string_uses_both_fonts_and_returns_width() -> None:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(300, 100), invariant=1)
    width = draw_string(pdf, 10, 50, f"Sita {SHARMA}", 12, bold=True)
    pdf.showPage()
    pdf.save()
    assert width == pytest.approx(string_width(f"Sita {SHARMA}", 12, bold=True))
    page = PdfReader(BytesIO(buffer.getvalue())).pages[0]
    fonts = {str(f.get_object()["/BaseFont"]) for f in page["/Resources"]["/Font"].values()}  # type: ignore[index]
    assert any("NotoSans-Bold" in f for f in fonts)
    assert any("NotoSansDevanagari-Bold" in f for f in fonts)
