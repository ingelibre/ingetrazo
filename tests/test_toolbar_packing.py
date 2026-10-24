# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Docked toolbars pack tight after a restored layout.

DriveMeca's video of a fresh install (2026-09-20) showed the Walkthrough
icons stranded at the bottom of the left column, a hole above them —
Marco saw the same. A saved layout keeps each toolbar's LENGTH, and
``restoreState`` applied the Annotate bar's old, longer one (saved with
bigger icons) whatever it holds today."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "prefs.ini"
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    import PySide6.QtCore as qc
    import views.main_window as mw
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory)
    return path


def _bars_in(win, area):
    return sorted((tb for tb in win.toolbars.values()
                   if win.toolBarArea(tb) == area),
                  key=lambda tb: (tb.geometry().y(), tb.geometry().x()))


def test_a_fresh_install_packs_the_left_column_and_keeps_the_top_order(
        settings_file):
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.resize(1280, 800)
        win.show()
        for _ in range(3):
            _app.processEvents()
        left = _bars_in(win, Qt.LeftToolBarArea)
        names = [tb.objectName() for tb in left]
        assert names == ["draw", "annotate", "walkthrough"]
        for above, below in zip(left, left[1:]):
            g, h = above.geometry(), below.geometry()
            assert h.y() == g.y() + g.height()            # no hole between
            assert g.height() == above.sizeHint().height()  # its own length
        top = [tb.objectName() for tb in _bars_in(win, Qt.TopToolBarArea)]
        assert top.index("view") < top.index("sections")  # the factory order
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_toolbars_that_do_not_fit_on_the_screen_go_to_a_new_row(
        settings_file):
    """With the 52 catalog extensions installed, 34 toolbars shared the top
    row and the window could not be narrower than 2205 px on a 1477 px
    screen: Marco could not resize it (18-10). A row that stops fitting is
    wrapped; the rows that fit stay as they were."""
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QToolBar
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.resize(800, 600)
        win.show()
        for _ in range(3):
            _app.processEvents()
        before = {tb.objectName(): win.toolBarBreak(tb)
                  for tb in win.toolbars.values()}
        avail = win.screen().availableGeometry().width()
        own_min = win.minimumSizeHint().width()
        extra = []
        n = avail // 40 + 5          # far more than one row can hold
        for i in range(n):
            tb = QToolBar(f"Extension {i}", win)
            tb.setObjectName(f"ext_{i}")
            for k in range(4):
                tb.addAction(QAction(f"a{k}", tb))
            win.addToolBar(Qt.TopToolBarArea, tb)
            extra.append(tb)
        for _ in range(4):
            _app.processEvents()
        # the extra bars add rows, not width (the offscreen screen is
        # narrower than the window's own minimum, hence the max)
        assert win.minimumSizeHint().width() <= max(own_min, avail)
        assert any(win.toolBarBreak(tb) for tb in extra)
        # the window's own bars keep their rows
        assert {tb.objectName(): win.toolBarBreak(tb)
                for tb in win.toolbars.values()} == before
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
