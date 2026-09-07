# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheet can be panned even when it fits the window whole (Marco,
2026-09-07: «cuando hago pan con la rueda del mouse no hace, solo hace
cuando la hoja es muy grande que no cabe en la ventana»). A QGraphicsView
only scrolls inside its scene rect; the composer's is now the page grown by
the viewport on every side, at every zoom, keeping a 20 mm strip in view."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _composer(monkeypatch):
    """A composer over a real MainWindow — the offscreen fake viewport
    segfaults inside fitInView after show(), before any of this code."""
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    comp.resize(1100, 850)
    comp.show()
    _app.processEvents()
    comp.zoom_fit_page()
    _app.processEvents()
    return comp, win


def _close(comp, win):
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def test_a_sheet_that_fits_the_window_still_pans(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        view = comp._view
        pw, ph = comp.comp.page_size_mm()
        scale = view.transform().m11()
        assert ph * scale < view.viewport().height()          # the sheet fits
        hbar, vbar = view.horizontalScrollBar(), view.verticalScrollBar()
        assert hbar.maximum() > hbar.minimum()                 # …and still pans
        assert vbar.maximum() > vbar.minimum()
        # fitted = centred on the page
        c = view.mapFromScene(QPointF(pw / 2, ph / 2))
        vc = view.viewport().rect().center()
        assert abs(c.x() - vc.x()) < 3 and abs(c.y() - vc.y()) < 3
        # a wheel's worth of scrolling moves the page
        before = view.mapFromScene(QPointF(0, 0))
        vbar.setValue(vbar.value() + 120)
        after = view.mapFromScene(QPointF(0, 0))
        assert after.y() < before.y()
        # …but never all the way out: a strip of the page stays visible
        vbar.setValue(vbar.maximum())
        _app.processEvents()
        bottom = view.mapFromScene(QPointF(0, ph)).y()
        assert bottom > 0                                      # still on screen
    finally:
        _close(comp, win)


def test_the_range_follows_the_zoom_and_the_paper(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        view = comp._view
        r0 = view.sceneRect()
        comp.set_zoom(400.0)
        _app.processEvents()
        assert view.sceneRect().width() < r0.width()   # zoomed in: less room needed
        comp.comp.paper = "A1"
        comp._rebuild_canvas()
        pw, _ph = comp.comp.page_size_mm()
        assert view.sceneRect().width() > pw           # the bigger paper fits inside
    finally:
        _close(comp, win)
