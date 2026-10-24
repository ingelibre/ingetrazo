# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Changing the accent colour must leave every widget alive.

Extension bench, 15-10: after Preferences ▸ Accent colour, the next Open
failed — «Internal C++ object (QComboBox / QCheckBox) already deleted» in
the Styles and Shadows panels — or the app segfaulted when F3's warm-up
walked the menus. The icons' repaint asked every top-level QMenu for its
QActions; with PySide 6.11.1 that walk leaves the wrappers of other
widgets dead (the same family as QAction.menu(), see command_search)."""
from __future__ import annotations

import gc
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DOC = (Path(__file__).resolve().parents[1] / "examples"
       / "banca-pergola-yanque.igz")


def _settle(app, rounds: int = 5) -> None:
    for _ in range(rounds):
        gc.collect()
        app.processEvents()


def test_the_accent_repaint_leaves_the_panels_and_menus_alive():
    from PySide6.QtWidgets import QApplication, QMenu
    from views import theme
    from views.command_search import menu_paths
    from views.main_window import MainWindow

    app = QApplication.instance()
    win = MainWindow()
    win.show()
    try:
        _settle(app)
        assert any(isinstance(w, QMenu) for w in app.topLevelWidgets())
        for _ in range(3):
            theme.save_accent("blue")
            theme.apply_accent(app)
            _settle(app)
            theme.save_accent(theme.ORANGE)
            theme.apply_accent(app)
            _settle(app)
        win._saved_version = win.viewport.scene.version
        assert win.open_path(DOC)               # Styles/Shadows refresh
        _settle(app)
        assert menu_paths(win)                  # F3 walks every menu
        win.styles_panel.refresh()
        win.shadows_panel.refresh()
    finally:
        theme.save_accent(theme.ORANGE)
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_accent_still_repaints_what_carries_an_icon_key():
    """Skipping the menus must not skip the icons: an action on a toolbar
    and a button in a panel both take the new accent."""
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QApplication, QToolButton
    from views import theme
    from views.icons import tool_icon
    from views.main_window import MainWindow

    app = QApplication.instance()
    win = MainWindow()
    win.show()
    act = QAction(tool_icon("line"), "probe", win)
    act.setProperty("icon_key", "line")
    win.addAction(act)
    btn = QToolButton(win.viewport)
    btn.setIcon(tool_icon("line"))
    btn.setProperty("icon_key", "line")

    def image(obj):
        return obj.icon().pixmap(32, 32).toImage()
    try:
        _settle(app)
        before = image(act), image(btn)
        theme.save_accent("blue")
        theme.apply_accent(app)
        _settle(app)
        assert image(act) != before[0]
        assert image(btn) != before[1]
        assert image(act) == tool_icon("line").pixmap(32, 32).toImage()
    finally:
        theme.save_accent(theme.ORANGE)
        win._saved_version = win.viewport.scene.version
        win.close()
