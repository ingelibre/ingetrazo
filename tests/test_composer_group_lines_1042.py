# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Two drawn lines on a sheet group with Ctrl+G (#1042)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.composition import FormaItem  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _composer(monkeypatch, tmp_path):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    monkeypatch.setattr(ComposerWindow, "templates_dir",
                        staticmethod(lambda: tmp_path))
    win = MainWindow()
    comp = ComposerWindow(win)
    return win, comp


def _close(win, comp):
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def test_two_lines_group_and_stay_grouped_on_a_click(monkeypatch, tmp_path):
    """Grouping worked, but a plain click on one member then left it alone
    selected (Qt clears the rest on a release that did not move), so the
    group looked undone and the next drag moved one line only."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    win, comp = _composer(monkeypatch, tmp_path)
    try:
        a = FormaItem(kind="linea", x_mm=100, y_mm=100, w_mm=20, h_mm=30)
        b = FormaItem(kind="linea", x_mm=115, y_mm=112, w_mm=15, h_mm=30)
        comp.comp.shapes += [a, b]
        comp._rebuild_canvas()
        comp.resize(1400, 1000)
        comp.show()
        QTest.qWaitForWindowExposed(comp)
        view = comp.canvas.views()[0]
        vp = view.viewport()

        def at(x, y):
            return view.mapFromScene(QPointF(x, y))
        on_a, on_b = at(110, 115), at(122.5, 127)
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, on_a)
        QTest.mouseClick(vp, Qt.LeftButton, Qt.ControlModifier, on_b)
        assert len(comp.canvas.selectedItems()) == 2
        act = next(x for x in comp._arrange_tb.actions()
                   if x.property("icon_key") == "arr_group")
        act.trigger()
        assert a.group_id and a.group_id == b.group_id
        comp.canvas.clearSelection()
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, on_a)
        assert {it.model.group_id for it in comp.canvas.selectedItems()} \
            == {a.group_id}
        assert len(comp.canvas.selectedItems()) == 2
        # and a click elsewhere still drops the group from the selection
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, at(200, 40))
        assert not any(getattr(it.model, "group_id", "")
                       for it in comp.canvas.selectedItems())
    finally:
        _close(win, comp)
