# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A press on a cota's text (or a handle) selects the cota as a plain
click does: the item selected before lets go, and the panel shows the
cota. It used to stay selected — usually the frame under the cota — and
keep the panel, so the cota's properties «sometimes» did not show."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.composition import CotaItem
from tests.test_composer_cota_cadena import _composer
from views.composer import CotaCanvasItem, FrameItem

_app = QApplication.instance() or QApplication([])


class _Press:
    def __init__(self, pos, mods=Qt.NoModifier):
        self._pos, self._mods = pos, mods

    def pos(self):
        return self._pos

    def modifiers(self):
        return self._mods

    def accept(self):
        pass


def _setup():
    composer, host = _composer()
    ct = CotaItem(x_mm=40.0, y_mm=60.0, dx_mm=50.0, dy_mm=0.0, offset_mm=0.5)
    composer.comp.cotas.append(ct)
    composer._rebuild_canvas()
    items = composer.canvas.items()
    frame = next(it for it in items if isinstance(it, FrameItem))
    cota = next(it for it in items
                if isinstance(it, CotaCanvasItem) and it.model is ct)
    frame.setSelected(True)
    assert composer._selected_item() is frame
    on_text = cota._label_path().boundingRect().center()
    assert cota._label_path().contains(on_text)
    return composer, host, frame, cota, on_text


def test_pressing_the_text_shows_the_cota_in_the_panel():
    composer, _host, frame, cota, on_text = _setup()
    cota.mousePressEvent(_Press(on_text))
    assert composer.canvas.selectedItems() == [cota]
    assert composer._selected_item() is cota
    assert composer.props.currentIndex() == 9      # the cota's page


def test_ctrl_still_adds_it_to_the_selection():
    composer, _host, frame, cota, on_text = _setup()
    cota.mousePressEvent(_Press(on_text, Qt.ControlModifier))
    assert set(composer.canvas.selectedItems()) == {frame, cota}
