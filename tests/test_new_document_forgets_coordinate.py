# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""#759, second half: after File ▸ New the status bar kept showing the
previous model's UTM easting/northing — the viewport only clears the
readout on the next hover over it."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from views.main_window import MainWindow  # noqa: E402


def test_file_new_clears_the_utm_readout():
    win = MainWindow()
    try:
        win._coord_label.setText("E 211234.5  N 8212345.6")
        win._coord_label.setToolTip("E 211,234.50  N 8,212,345.60  19L")
        win.viewport._last_coordinate = "E 211234.5  N 8212345.6"
        win._saved_version = win.viewport.scene.version   # nothing to discard
        win._on_new()
        QApplication.processEvents()
        assert win._coord_label.text() == ""
        assert win._coord_label.toolTip() == ""
        assert win.viewport._last_coordinate == ""
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
