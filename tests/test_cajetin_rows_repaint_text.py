# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A text that reads a title-block row shows the new value as the row is edited.

Text items keep a device-coordinate cache, so the view has to be read back:
looking at the model alone would pass with the old picture still on screen.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from core.composition import Cajetin, Composicion, TextoItem


def _settle(ms: int = 80) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    QApplication.processEvents()


def _pixels(view, item):
    rect = view.mapFromScene(item.sceneBoundingRect()).boundingRect()
    rect = rect.intersected(view.viewport().rect())
    _settle()
    return view.viewport().grab(rect).toImage()


@pytest.fixture
def composer(monkeypatch, tmp_path):
    QApplication.instance() or QApplication([])
    from views.composer import ComposerWindow, TextItem, CajetinItem
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    monkeypatch.setattr(ComposerWindow, "templates_dir",
                        staticmethod(lambda: tmp_path))
    win = MainWindow()
    sheet = Composicion(name="L-01")
    sheet.cajetin = Cajetin(campos=[["PROYECTO", "Casa"], ["PLANO", "A-1"]])
    sheet.texts.append(TextoItem(text="Obra: {proyecto}", x_mm=60, y_mm=60,
                                 w_mm=120))
    win.viewport.scene.compositions = [sheet]
    comp = ComposerWindow(win)
    comp.resize(1200, 800)
    comp.show()
    comp.comp = sheet
    comp._rebuild_canvas()
    _settle(150)
    canvas = comp.canvas
    text = next(i for i in canvas.items() if isinstance(i, TextItem))
    block = next(i for i in canvas.items() if isinstance(i, CajetinItem))
    assert text.cacheMode() == text.CacheMode.DeviceCoordinateCache
    yield comp, canvas.views()[0], text, block
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def test_editing_a_row_repaints_the_text_that_reads_it(composer):
    comp, view, text, block = composer
    block.setSelected(True)
    _settle()
    before = _pixels(view, text)
    comp.caj_table.item(0, 1).setText("Plaza nueva")
    assert _pixels(view, text) != before


def test_undo_of_a_row_repaints_the_text_too(composer):
    comp, view, text, block = composer
    block.setSelected(True)
    _settle()
    original = _pixels(view, text)
    comp.caj_table.item(0, 1).setText("Plaza nueva")
    edited = _pixels(view, text)
    comp.history.undo()
    _settle()
    canvas = comp.canvas
    from views.composer import TextItem
    text = next(i for i in canvas.items() if isinstance(i, TextItem))
    assert _pixels(view, text) == original != edited


def test_a_row_edit_leaves_a_text_without_fields_alone(composer):
    comp, view, text, block = composer
    text.model.text = "Sin campos"
    text.update()
    block.setSelected(True)
    _settle()
    before = _pixels(view, text)
    comp.caj_table.item(0, 1).setText("Plaza nueva")
    assert _pixels(view, text) == before
