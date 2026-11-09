# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Esc while dragging a view on the sheet puts it back where it was, with
no undo step (#504, @pacaeiro: the view stayed where Esc caught it)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.composition import MarcoVista  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def composer(monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    comp.resize(1200, 800)
    comp.show()
    _app.processEvents()
    yield comp
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def _frame(comp):
    from views.composer import FrameItem
    frame = MarcoVista(x_mm=40.0, y_mm=40.0, w_mm=80.0, h_mm=60.0)
    comp.comp.frames.append(frame)
    comp._rebuild_canvas()
    item = next(i for i in comp.canvas.items()
                if isinstance(i, FrameItem) and i.model is frame)
    return frame, item


def _px(comp, x_mm, y_mm) -> QPoint:
    return comp._view.mapFromScene(QPointF(x_mm, y_mm))


def test_esc_during_a_drag_puts_the_view_back(composer):
    comp = composer
    frame, item = _frame(comp)
    steps = len(comp.history.undo_stack) if hasattr(comp.history, "undo_stack") else None
    vp = comp._view.viewport()
    start = _px(comp, 80.0, 70.0)                     # inside the view
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, start)
    for k in range(1, 6):
        QTest.mouseMove(vp, start + QPoint(30 * k, 12 * k))
    _app.processEvents()
    assert (frame.x_mm, frame.y_mm) != (40.0, 40.0)   # it is being dragged
    QTest.keyClick(comp._view, Qt.Key_Escape)
    assert (frame.x_mm, frame.y_mm) == (40.0, 40.0)
    assert (item.pos().x(), item.pos().y()) == (40.0, 40.0)
    # moving on and letting go no longer drags nor commits anything
    QTest.mouseMove(vp, start + QPoint(200, 90))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, start + QPoint(200, 90))
    _app.processEvents()
    assert (frame.x_mm, frame.y_mm) == (40.0, 40.0)
    if steps is not None:
        assert len(comp.history.undo_stack) == steps


def test_esc_with_no_drag_still_drops_the_selection(composer):
    comp = composer
    _frame_model, item = _frame(comp)
    item.setSelected(True)
    QTest.keyClick(comp._view, Qt.Key_Escape)
    assert not item.isSelected()
