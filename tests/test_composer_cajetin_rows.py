# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Title-block rows take the height their content needs (Marco, 2026-09-07,
looking at the real Yanque title block: «el nombre es largo… no se ve bien
porque la fuente disminuye y lo demás se hace más grande»).

A long project name used to wrap and SHRINK inside its equal-height row,
next to a date and a sheet number drawn twice as big. Now the row grows —
paid for by the rows that never used their share — and every value comes
out at about one size. A block whose values all fit keeps the equal rows it
always had.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from core.composition import Cajetin
from views.composer import (CAJETIN_ROW_GROW, _fit_text_size_mm,
                            cajetin_row_heights, paint_cajetin_mm)

_app = QApplication.instance() or QApplication([])

LONG = ("CREACION DE LOS SERVICIOS DE ESPACIOS PÚBLICOS URBANOS EN LA PLAZA "
        "PRINCIPAL DE YANQUE DISTRITO DE CHICHAS DE LA PROVINCIA DE "
        "CONDESUYOS DEL DEPARTAMENTO DE AREQUIPA")
ROWS = [["PROYECTO", LONG],
        ["AUTOR", "MUNICIPALIDAD DISTRITAL DE CHICHAS"],
        ["FECHA", "07/09/2026"],
        ["ESCALA", "1:20"],
        ["LÁMINA", "L-01"]]
SHORT = [["PROYECTO", "Plaza Yanque"], ["AUTOR", "MST"],
         ["FECHA", "07/09/2026"], ["ESCALA", "1:20"], ["LÁMINA", "L-01"]]

#: Marco's block on the A3 sheet.
W, H = 184.0, 47.5
LABEL_W = min(28.0, W * 0.3)


def _heights(rows, cols=1, w=W, h=H, layout="grid"):
    per = -(-len(rows) // cols)
    return cajetin_row_heights(rows, cols, per, h, w / cols, LABEL_W, layout)


def _value_sizes(rows, heights, w=W, h=H):
    """The size each value ends up drawn at, the way the painter picks it."""
    base = h / len(heights)
    out = []
    for (_label, value), rh in zip(rows, heights):
        rect = QRectF(0, 0, w - LABEL_W - 3, rh - 1.0)
        out.append(_fit_text_size_mm(str(value), rect, base * 0.52))
    return out


def test_a_block_that_fits_keeps_its_equal_rows():
    hs = _heights(SHORT)
    assert len(hs) == 5
    assert all(h == pytest.approx(H / 5) for h in hs)


def test_the_long_row_grows_and_the_others_pay_for_it():
    hs = _heights(ROWS)
    base = H / 5
    assert sum(hs) == pytest.approx(H)          # the block keeps its height
    assert hs[0] > base * 1.5                   # the project name grew
    assert all(h < base for h in hs[1:])        # the short rows gave it up
    assert all(h == pytest.approx(hs[1]) for h in hs[2:])   # …equally
    assert hs[0] <= base * CAJETIN_ROW_GROW + 1e-9          # bounded


def test_every_value_now_reads_at_about_one_size():
    grown = _value_sizes(ROWS, _heights(ROWS))
    equal = _value_sizes(ROWS, [H / 5] * 5)
    assert min(equal) < max(equal) * 0.85       # the defect: the odd one out
    assert grown[0] > equal[0]                  # the project name got bigger
    assert min(grown) >= max(grown) * 0.95      # …and now they match


def test_a_cramped_block_still_shrinks_the_text_instead_of_vanishing():
    """Bounded: 5 rows in 30 mm cannot hold that name at full size, so the
    row stops growing and the fit takes over — no hairline rows."""
    hs = _heights(ROWS, w=70.0, h=30.0)
    base = 30.0 / 5
    assert sum(hs) == pytest.approx(30.0)
    assert all(h > 1.0 for h in hs)
    assert hs[0] <= base * CAJETIN_ROW_GROW + 1e-9


def test_the_rows_of_a_two_column_block_stay_lined_up():
    hs = _heights(ROWS, cols=2)
    assert len(hs) == 3                     # 5 fields over 2 columns
    assert sum(hs) == pytest.approx(H)
    # row 0 holds the long name in column 1 and «ESCALA 1:20» in column 2:
    # both columns get the taller row, so the grid lines still meet.
    assert hs[0] > H / 3


@pytest.mark.parametrize("layout", ["grid", "banded", "minimal"])
def test_every_layout_paints_with_the_new_rows(layout):
    c = Cajetin(w_mm=W, h_mm=H)
    c.campos = [list(r) for r in ROWS]
    c.layout = layout
    img = QImage(int(W * 4), int(H * 4), QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.scale(4, 4)
    paint_cajetin_mm(p, c)
    p.end()
    # something was drawn on the white ground
    assert any(img.pixelColor(x, y) != QColor(255, 255, 255)
               for y in range(0, img.height(), 7)
               for x in range(0, img.width(), 7))
