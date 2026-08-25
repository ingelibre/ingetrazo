# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Window title: an imported .skp/.dae/.obj shows ITS name until the model
is saved as .igz (user report: opening a SketchUp file left "Untitled")."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def test_title_shows_imported_name_until_igz_takes_over():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        assert "Untitled" in win.windowTitle() or "Sin título" in win.windowTitle()

        win._import_name = "casa bueno.skp"     # what a .skp import sets
        win._update_title()
        assert "casa bueno.skp" in win.windowTitle()

        win._current_path = Path("/tmp/obra.igz")   # Save As wins over it
        win._update_title()
        assert "obra.igz" in win.windowTitle()
        assert "casa bueno" not in win.windowTitle()

        win._current_path = None                 # New clears the import name
        win._import_name = None
        win._update_title()
        assert "obra.igz" not in win.windowTitle()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
