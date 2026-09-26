"""Two-click placement survives a hand that moves a few pixels between
press and release on the first click (#95, @pacaeiro: «Add a model-view
frame (two clicks or drag) — the 2 clicks option do not work»): that used
to count as a tiny drag and drop a minimum-size frame at once."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


@pytest.mark.parametrize("mode", ["vista", "rect", "linea"])
def test_a_shaky_first_click_still_waits_for_the_second(monkeypatch, mode):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    try:
        comp.show()
        _app.processEvents()
        view, vp = comp._view, comp._view.viewport()
        f = comp.comp.frames[0]
        a = view.mapFromScene(f.x_mm + 20, f.y_mm + 20)
        b = view.mapFromScene(f.x_mm + 100, f.y_mm + 80)
        n0 = len(comp.comp.all_items())
        comp._tool_actions[mode].trigger()
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, a)
        QTest.mouseMove(vp, a + QPoint(3, 2))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, a + QPoint(3, 2))
        assert len(comp.comp.all_items()) == n0          # still waiting
        assert view._drag_start is not None
        QTest.mouseMove(vp, b)
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, b)
        assert len(comp.comp.all_items()) == n0 + 1
        if mode == "vista":
            new = comp.comp.frames[-1]
            assert new.w_mm > 70 and new.h_mm > 50        # the span clicked
        comp.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


@pytest.mark.parametrize("mode", ["vista", "flecha", "linea", "rect"])
def test_a_canvas_rebuild_between_the_clicks_keeps_the_first_one(
        monkeypatch, mode):
    """The rest of #95 (@pacaeiro, still in 0.5.2 for views and arrows):
    between the two clicks the canvas is rebuilt — the view just drawn
    finishes its render, a field refreshes — and every rebuild dropped the
    placement, so the first click was lost. The test above never saw it
    because it switches rendering off."""
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    try:
        comp.show()
        _app.processEvents()
        view, vp = comp._view, comp._view.viewport()
        f = comp.comp.frames[0]
        a = view.mapFromScene(f.x_mm + 20, f.y_mm + 20)
        mid = view.mapFromScene(f.x_mm + 60, f.y_mm + 50)
        b = view.mapFromScene(f.x_mm + 100, f.y_mm + 80)
        n0 = len(comp.comp.all_items())
        comp._tool_actions[mode].trigger()
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, a)
        QTest.mouseMove(vp, mid)                      # rubber band drawn
        comp._rebuild_canvas()                        # e.g. a render lands
        _app.processEvents()
        assert view._drag_start is not None           # first click kept
        QTest.mouseMove(vp, b)                        # band drawn again
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, b)
        assert len(comp.comp.all_items()) == n0 + 1
        comp.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
