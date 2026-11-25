# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The rows' eye and padlock are kept at the common pixel ratios, so a
window at one of them paints the exact drawing. Kept only at 1x and 3x, a
window at 125 % (Wayland with a fractional scale: the screen says 2.0, the
window paints at 1.25) got the 3x drawing scaled down by 2.4 and the marks
came out blurred (Marco, 21-11, the Layers bar beside «Layer 0»)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _painted(icon, dpr, size=18):
    img = QImage(round(size * dpr), round(size * dpr),
                 QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(0)
    p = QPainter(img)
    icon.paint(p, QRect(0, 0, size, size))
    p.end()
    return img


@pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0, 2.5, 3.0])
@pytest.mark.parametrize("key", ["eye", "eye_off", "lock", "lock_open"])
def test_a_mark_is_the_drawing_at_the_painters_own_ratio(key, dpr):
    from views.outliner import _draw_pixmap, node_icon
    got = _painted(node_icon(key), dpr)
    want = _draw_pixmap(key, dpr).toImage().convertToFormat(
        QImage.Format_ARGB32_Premultiplied)
    assert got.size() == want.size()
    assert got == want


@pytest.mark.parametrize("dpr", [1.25, 1.75, 2.25])
@pytest.mark.parametrize("key", ["eye", "lock"])
def test_a_fractional_window_gets_the_drawing_made_for_it(key, dpr):
    """Where 18 px is not a whole number of pixels the icon still hands
    over the pixmap drawn at that ratio, not another one scaled."""
    from PySide6.QtCore import QSize
    from views.outliner import _draw_pixmap, node_icon
    got = node_icon(key).pixmap(QSize(18, 18), dpr).toImage()
    want = _draw_pixmap(key, dpr).toImage()
    assert got.size() == want.size()
    assert got.convertToFormat(QImage.Format_ARGB32_Premultiplied) == \
        want.convertToFormat(QImage.Format_ARGB32_Premultiplied)


def test_strokes_are_whole_pixels_on_a_fractional_screen():
    from views.outliner import _draw_pixmap
    # The padlock's body at 125 %: its vertical sides land on whole
    # pixels, with fewer half-covered ones than a 1.5 px stroke leaves.
    img = _draw_pixmap("lock", 1.25).toImage()
    alphas = [img.pixelColor(x, y).alpha()
              for y in range(img.height()) for x in range(img.width())]
    inked = [a for a in alphas if a]
    solid = sum(a > 230 for a in inked) / len(inked)
    assert solid > 0.4


def test_the_inherited_mark_is_the_same_drawing_fainter():
    from views.outliner import mark_icon, node_icon
    own = _painted(node_icon("eye"), 1.25)
    faint = _painted(mark_icon("eye", inherited=True), 1.25)
    a_own = max(own.pixelColor(x, y).alpha()
                for y in range(own.height()) for x in range(own.width()))
    a_faint = max(faint.pixelColor(x, y).alpha()
                  for y in range(faint.height()) for x in range(faint.width()))
    assert 0 < a_faint < a_own
