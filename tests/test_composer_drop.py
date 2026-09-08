# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Dropping a dragged item is cheap: the item already shows its model, so
the canvas is NOT rebuilt (that repainted every item cold — an 80 ms hitch
per drop on a full sheet; Marco, 2026-09-07: «cierto lag cuando arrastro
un leader»). A frame drop still rebuilds: cotas anchored to it and texts
bound to it must follow."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.composition import EtiquetaItem
from views.composer import EtiquetaCanvasItem, FrameItem, _SheetItem

_app = QApplication.instance() or QApplication([])


def _composer(monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    comp.comp.etiquetas.append(EtiquetaItem(x_mm=50.0, y_mm=50.0, text="Pileta"))
    comp._rebuild_canvas()
    return comp, win


def _close(comp, win):
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def _items(comp):
    return {id(it): it for it in comp.canvas.items() if isinstance(it, _SheetItem)}


def test_dropping_a_label_keeps_the_canvas_items_and_records_the_step(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        before_items = _items(comp)
        label = comp.comp.etiquetas[0]
        it = next(i for i in before_items.values() if isinstance(i, EtiquetaCanvasItem))
        n_undo = len(comp.history._undo)
        # what mouseReleaseEvent does after a drag: model already moved
        it.setPos(60.0, 55.0)
        comp.push_geometry_edit(label, {"x_mm": 60.0, "y_mm": 55.0},
                                {"x_mm": 50.0, "y_mm": 50.0})
        _app.processEvents()                      # a deferred rebuild would fire here
        assert set(_items(comp)) == set(before_items)   # same items: no rebuild
        assert len(comp.history._undo) == n_undo + 1      # …but one undo step
        assert win._is_dirty()                            # …and the document is dirty
        comp.history.undo()
        _app.processEvents()
        assert (label.x_mm, label.y_mm) == (50.0, 50.0)   # undo still works
    finally:
        _close(comp, win)


def test_dropping_a_frame_still_rebuilds_for_what_follows_it(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        before_items = _items(comp)
        frame = comp.comp.frames[0]
        comp.push_geometry_edit(frame, {"x_mm": frame.x_mm + 5.0, "y_mm": frame.y_mm},
                                {"x_mm": frame.x_mm, "y_mm": frame.y_mm})
        # The rebuild is deferred to the event loop: it must not clear the
        # canvas from inside the dropped item's own mouseReleaseEvent.
        assert set(_items(comp)) == set(before_items)     # not yet
        _app.processEvents()
        assert set(_items(comp)) != set(before_items)     # rebuilt
        it = next(i for i in _items(comp).values() if isinstance(i, FrameItem))
        assert it.isSelected()                             # and picked back up
    finally:
        _close(comp, win)


def test_two_sheet_edits_between_two_paints_do_not_stale_the_frames(monkeypatch):
    """The viewport reports scene versions as it paints. Two sheet edits in
    a row bump the version twice; when the viewport then reported the
    FIRST of them, it was taken for a model change and every frame went
    stale (snap sets dropped, exact pass redone — the ~1 s freeze)."""
    comp, win = _composer(monkeypatch)
    try:
        scene = win.viewport.scene
        comp._on_model_version(scene.version)
        comp._stale.clear()
        comp._mark_dirty()
        v1 = scene.version
        comp._mark_dirty()
        v2 = scene.version
        comp.snap_cache[id(comp.comp.frames[0])] = "kept"
        comp._on_model_version(v1)             # the viewport painted in between
        comp._on_model_version(v2)
        assert not comp._stale                 # no frame went stale
        assert comp.snap_cache.get(id(comp.comp.frames[0])) == "kept"
        scene.version += 1                     # a REAL model change still counts
        comp._on_model_version(scene.version)
        assert comp._stale
    finally:
        _close(comp, win)


def test_a_rebuilt_canvas_forgets_the_inline_editor(monkeypatch):
    """The editor item dies with the canvas; a later double-click must not
    touch the dead wrapper («Internal C++ object already deleted»)."""
    comp, win = _composer(monkeypatch)
    try:
        label_item = next(i for i in _items(comp).values()
                          if isinstance(i, EtiquetaCanvasItem))
        comp.begin_inline_edit(label_item)
        assert comp._inline_editor is not None
        comp._rebuild_canvas()                      # an undo, a paste, a drop…
        assert comp._inline_editor is None
        label_item = next(i for i in _items(comp).values()
                          if isinstance(i, EtiquetaCanvasItem))
        comp.begin_inline_edit(label_item)          # used to raise here
        comp.end_inline_edit(None, None)
        assert comp._inline_editor is None
    finally:
        _close(comp, win)
