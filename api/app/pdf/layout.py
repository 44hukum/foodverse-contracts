"""Find out whether a page has free space for the signature block.

The spec puts the signature block on the last page "or on a new page if there
is no room" (SPEC.md §4 step 7). PDF has no notion of free space, so this
module scans the page's content stream for anything drawn inside the vertical
band the block would occupy:

- text: each glyph run contributes its baseline and its cap height;
- paths (``m``, ``l``, ``c``, ``v``, ``y``, ``re``): each coordinate pair
  contributes a point, so a page border or a background fill that merely
  surrounds the band does not count as occupying it;
- XObjects (``Do``, images and forms): the whole vertical extent counts, so a
  scanned page is never stamped over.

A page with no drawable content at all is treated as free.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pypdf import PageObject

Matrix = Sequence[float]
Interval = tuple[float, float]

_POINT_OPERATORS: dict[bytes, int] = {b"m": 1, b"l": 1, b"c": 3, b"v": 2, b"y": 2}


def _apply(matrix: Matrix, x: float, y: float) -> tuple[float, float]:
    """Apply a PDF transformation matrix ``[a b c d e f]`` to a point."""
    a, b, c, d, e, f = (float(v) for v in matrix)
    return a * x + c * y + e, b * x + d * y + f


def _y_in_page(cm: Matrix, tm: Matrix, x: float, y: float) -> float:
    """Text-space point -> page-space y (text matrix, then current matrix)."""
    ux, uy = _apply(tm, x, y)
    return _apply(cm, ux, uy)[1]


def content_extents(page: PageObject) -> list[Interval]:
    """Vertical intervals ``(low, high)`` occupied by content, in page user space."""
    extents: list[Interval] = []

    def on_text(text: str, cm: Matrix, tm: Matrix, _font: Any, font_size: float) -> None:
        if not text.strip():
            return
        baseline = _y_in_page(cm, tm, 0.0, 0.0)
        top = _y_in_page(cm, tm, 0.0, float(font_size or 0.0))
        extents.append((min(baseline, top), max(baseline, top)))

    def on_operand(operator: bytes, operands: Sequence[Any], cm: Matrix, _tm: Matrix) -> None:
        try:
            if operator == b"Do":
                ys = [_apply(cm, x, y)[1] for x in (0.0, 1.0) for y in (0.0, 1.0)]
                extents.append((min(ys), max(ys)))
            elif operator == b"re":
                x, y, _w, h = (float(v) for v in operands[:4])
                for py in (y, y + h):
                    py_page = _apply(cm, x, py)[1]
                    extents.append((py_page, py_page))
            elif operator in _POINT_OPERATORS:
                pairs = _POINT_OPERATORS[operator]
                values = [float(v) for v in operands[: 2 * pairs]]
                for i in range(0, len(values) - 1, 2):
                    py_page = _apply(cm, values[i], values[i + 1])[1]
                    extents.append((py_page, py_page))
        except (TypeError, ValueError, IndexError):
            # Malformed operands: ignore the operator rather than fail signing.
            return

    page.extract_text(visitor_text=on_text, visitor_operand_before=on_operand)
    return extents


def band_is_clear(page: PageObject, low: float, high: float) -> bool:
    """True when nothing on ``page`` overlaps the vertical band ``[low, high]``."""
    return all(top < low or bottom > high for bottom, top in content_extents(page))
