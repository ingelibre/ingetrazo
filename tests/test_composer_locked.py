# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A locked sheet item is out of the mouse's reach: not selectable on the
canvas, by click or by box, so the cotas and texts over a locked view frame
are what a click gets. It is picked from the panel's Items list only — the
one door to reach it and unlock it (Marco, 2026-09-07)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QApplication, QGraphicsItem

from core.composition import CotaItem
from views.composer import CotaCanvasItem, FrameItem, _SheetItem

_app = QApplication.instance() or QApplication([])


def _composer(monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    comp.show()
    _app.processEvents()
    return comp, win


def _close(comp, win):
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def _frame_item(comp):
    return next(it for it in comp.canvas.items() if isinstance(it, FrameItem))


def test_a_locked_frame_is_not_reachable_from_the_canvas(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        frame = comp.comp.frames[0]
        # a cota drawn over the frame, where a click used to grab the frame
        comp.comp.cotas.append(CotaItem(x_mm=frame.x_mm + 30, y_mm=frame.y_mm + 30,
                                        dx_mm=40.0, dy_mm=0.0))
        frame.locked = True
        comp._rebuild_canvas()
        it = _frame_item(comp)
        assert not (it.flags() & QGraphicsItem.ItemIsSelectable)
        assert it.acceptedMouseButtons() == Qt.NoButton
        assert not it.acceptHoverEvents()
        # the frame is neither in a box selection…
        path = QPainterPath()
        path.addRect(frame.x_mm - 5, frame.y_mm - 5, frame.w_mm + 10, frame.h_mm + 10)
        comp.canvas.setSelectionArea(path)
        picked = [i for i in comp.canvas.selectedItems() if isinstance(i, _SheetItem)]
        assert it not in picked
        assert any(isinstance(i, CotaCanvasItem) for i in picked)  # …but the cota is
        # …nor under the mouse: the topmost item at a point inside it is not it
        under = comp.canvas.itemAt(QPointF(frame.x_mm + 30, frame.y_mm + 30),
                                   comp._view.transform())
        assert under is not it or not (it.flags() & QGraphicsItem.ItemIsSelectable)
    finally:
        _close(comp, win)


def test_the_items_list_is_the_door_to_a_locked_item(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        frame = comp.comp.frames[0]
        frame.locked = True
        comp._rebuild_canvas()
        it = _frame_item(comp)
        comp._refresh_items_list()
        row = next(r for r in (comp.items_list.item(i)
                               for i in range(comp.items_list.count()))
                   if r.data(Qt.UserRole) == id(frame))
        comp.items_list.setCurrentItem(row)
        row.setSelected(True)
        comp._on_list_select()
        assert it.isSelected()                                 # picked from the list
        assert comp._selected_item() is it                      # the panel shows it
        comp.canvas.clearSelection()                            # selection moves on…
        assert not (it.flags() & QGraphicsItem.ItemIsSelectable)  # …door closed again
        # unlock from the list pick: it becomes an ordinary item
        comp.items_list.setCurrentItem(row)
        row.setSelected(True)
        comp._on_list_select()
        assert it.isSelected()
        comp.lock_selected()
        _app.processEvents()
        assert not frame.locked
        it2 = _frame_item(comp)
        assert it2.flags() & QGraphicsItem.ItemIsSelectable
        assert it2.acceptedMouseButtons() != Qt.NoButton
    finally:
        _close(comp, win)


def test_locking_keeps_the_item_selected_for_the_panel(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        it = _frame_item(comp)
        it.setSelected(True)
        comp.toggle_lock(it)
        _app.processEvents()
        it2 = _frame_item(comp)
        assert it2.model.locked and it2.isSelected()            # still on the panel
    finally:
        _close(comp, win)
