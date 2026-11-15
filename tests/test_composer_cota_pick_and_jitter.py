# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A short cota between two neighbours of a chain can be picked, and a
click whose hand trembles a pixel moves nothing — neither the cota (which
broke its anchor to the model) nor its text (which left the automatic
spot)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtWidgets import QApplication

from core.composition import CotaItem
from tests.test_composer_cota_cadena import _composer
from views.composer import CotaCanvasItem

_app = QApplication.instance() or QApplication([])


def _items(composer, *models):
    composer._rebuild_canvas()
    found = {id(it.model): it for it in composer.canvas.items()
             if isinstance(it, CotaCanvasItem)}
    return [found[id(m)] for m in models]


def test_a_short_cota_in_a_chain_can_be_picked():
    composer, _host = _composer()
    row = dict(y_mm=50.0, dy_mm=0.0, sep_mm=-10.0, scale_n=50.0)
    a = CotaItem(x_mm=20.0, dx_mm=30.0, **row)
    short = CotaItem(x_mm=50.0, dx_mm=4.0, **row)            # 0.20 m
    c = CotaItem(x_mm=54.0, dx_mm=30.0, **row)               # on top
    composer.comp.cotas += [a, short, c]
    _items(composer, a, short, c)
    view = composer._view
    view.resetTransform()
    view.scale(4.0, 4.0)                                     # ~100 %
    for x in (51.0, 52.0, 53.0):                             # along its line
        top = next(it for it in composer.canvas.items(QPointF(x, 40.0))
                   if isinstance(it, CotaCanvasItem))
        assert top.model is short, x


class _Ev:
    def __init__(self, pos, screen, down=QPoint(500, 500)):
        self._pos, self._screen, self._down = pos, screen, down

    def pos(self):
        return self._pos

    def screenPos(self):
        return self._screen

    def buttonDownScreenPos(self, _button):
        return self._down

    def modifiers(self):
        return Qt.NoModifier

    def accept(self):
        pass


def test_a_trembling_click_on_the_text_moves_nothing():
    composer, _host = _composer()
    ct = CotaItem(x_mm=40.0, y_mm=60.0, dx_mm=50.0, dy_mm=0.0)
    composer.comp.cotas.append(ct)
    (item,) = _items(composer, ct)
    on_text = item._label_path().boundingRect().center()
    item.mousePressEvent(_Ev(on_text, QPoint(500, 500)))
    assert item._text_dragging
    item.mouseMoveEvent(_Ev(on_text + QPointF(0.4, 0.2), QPoint(502, 501)))
    assert (ct.text_dx_mm, ct.text_dy_mm) == (0.0, 0.0)      # a tremble
    item.mouseMoveEvent(_Ev(on_text + QPointF(5.0, 0.0), QPoint(520, 500)))
    assert ct.text_dx_mm == 5.0                              # a real drag
