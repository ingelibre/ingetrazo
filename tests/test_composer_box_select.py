# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Box selection on the sheet (Marco, 2026-09-07: «falta seleccionar varios
objetos con el mouse haciendo un cuadro»): a drag from the empty page
selects what the box encloses (left→right, window) or touches
(right→left, crossing) — SketchUp's rule — with the model Select tool's
modifiers; locked items stay out; a click on the page still clears."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.composition import TextoItem
from views.composer import FrameItem, TextItem, _SheetItem

_app = QApplication.instance() or QApplication([])


def _composer(monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    f = comp.comp.frames[0]
    f.x_mm, f.y_mm, f.w_mm, f.h_mm = 20.0, 20.0, 100.0, 80.0
    comp.comp.texts.append(TextoItem(x_mm=150.0, y_mm=30.0, w_mm=30.0, text="A"))
    comp.comp.texts.append(TextoItem(x_mm=150.0, y_mm=60.0, w_mm=30.0, text="B"))
    comp._rebuild_canvas()
    comp.resize(900, 700)
    comp.show()
    _app.processEvents()
    comp.set_tool_mode("select") if hasattr(comp, "set_tool_mode") else None
    return comp, win


def _close(comp, win):
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def _items(comp):
    return {type(it).__name__ + ":" + getattr(it.model, "text", "frame"): it
            for it in comp.canvas.items() if isinstance(it, _SheetItem)}


def _selected(comp):
    return sorted(k for k, it in _items(comp).items() if it.isSelected())


def _drag(view, a_mm, b_mm, modifiers=Qt.NoModifier):
    from PySide6.QtCore import QPointF
    vp = view.viewport()
    a = view.mapFromScene(QPointF(*a_mm))
    b = view.mapFromScene(QPointF(*b_mm))
    QTest.mousePress(vp, Qt.LeftButton, modifiers, a)
    QTest.mouseMove(vp, a + QPoint(6, 6))
    QTest.mouseMove(vp, b)
    QTest.mouseRelease(vp, Qt.LeftButton, modifiers, b)
    _app.processEvents()


def test_a_left_to_right_box_selects_only_what_it_encloses(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        view = comp._view
        view.fitInView(QRectF(0, 0, 210, 297), Qt.KeepAspectRatio)
        _drag(view, (140.0, 10.0), (200.0, 100.0))       # around both texts
        assert _selected(comp) == ["TextItem:A", "TextItem:B"]
        _drag(view, (10.0, 10.0), (60.0, 60.0))          # a corner of the frame only
        assert _selected(comp) == []                      # window: not enclosed
        assert view._band_item is None                    # the band is gone
    finally:
        _close(comp, win)


def test_a_right_to_left_box_selects_what_it_touches(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        view = comp._view
        view.fitInView(QRectF(0, 0, 210, 297), Qt.KeepAspectRatio)
        _drag(view, (60.0, 60.0), (10.0, 10.0))          # crossing a frame corner
        assert _selected(comp) == ["FrameItem:frame"]
    finally:
        _close(comp, win)


def test_modifiers_follow_the_model_select_tool(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        view = comp._view
        view.fitInView(QRectF(0, 0, 210, 297), Qt.KeepAspectRatio)
        _drag(view, (140.0, 10.0), (200.0, 45.0))                       # A
        assert _selected(comp) == ["TextItem:A"]
        _drag(view, (140.0, 50.0), (200.0, 75.0), Qt.ControlModifier)   # + B
        assert _selected(comp) == ["TextItem:A", "TextItem:B"]
        _drag(view, (140.0, 10.0), (200.0, 45.0), Qt.ShiftModifier)     # toggle A off
        assert _selected(comp) == ["TextItem:B"]
        _drag(view, (140.0, 10.0), (200.0, 100.0),
              Qt.ShiftModifier | Qt.ControlModifier)                    # remove both
        assert _selected(comp) == []
    finally:
        _close(comp, win)


def test_a_locked_item_is_never_boxed_and_a_click_on_the_page_clears(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        view = comp._view
        view.fitInView(QRectF(0, 0, 210, 297), Qt.KeepAspectRatio)
        comp.comp.frames[0].locked = True
        comp._rebuild_canvas()
        _drag(view, (5.0, 5.0), (205.0, 150.0))          # everything
        assert _selected(comp) == ["TextItem:A", "TextItem:B"]
        vp = view.viewport()
        from PySide6.QtCore import QPointF
        p = view.mapFromScene(QPointF(190.0, 150.0))     # empty page
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, p)
        _app.processEvents()
        assert _selected(comp) == []
    finally:
        _close(comp, win)
