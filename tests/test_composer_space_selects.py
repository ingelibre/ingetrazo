# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Space ends the tool on the sheet as it does in the model (#83,
@pacaeiro: «in Model view Space ends a command, in Sheet Composer it is
Esc»)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def test_space_drops_the_placement_and_picks_select(monkeypatch):
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
        n0 = len(comp.comp.all_items())
        comp._tool_actions["linea"].trigger()
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier,
                         view.mapFromScene(f.x_mm + 20, f.y_mm + 20))
        assert view._drag_start is not None
        QTest.keyClick(view, Qt.Key_Space)
        assert view._drag_start is None                 # nothing half-placed
        assert comp.tool_mode == "select"
        assert comp._tool_actions["select"].isChecked()
        assert len(comp.comp.all_items()) == n0         # nothing placed
        comp.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
