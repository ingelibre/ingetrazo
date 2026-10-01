# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Every colour picker is Qt's own dialog: on GNOME the native one is a
small GTK palette, and opened from a right-click menu it came back without
the colour chosen, so editing a material's colour did nothing (0.5.7)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QColorDialog  # noqa: E402

_app = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]


def test_the_picker_asks_for_qts_own_dialog(monkeypatch):
    from views import color_dialog
    seen = {}

    def fake(*args, **kwargs):
        seen.update(kwargs)
        return QColor(10, 20, 30)

    monkeypatch.setattr(color_dialog.QColorDialog, "getColor",
                        staticmethod(fake))
    assert color_dialog.get_color(QColor(0, 0, 0)).red() == 10
    assert seen["options"] == QColorDialog.ColorDialogOption.DontUseNativeDialog


def test_no_panel_opens_the_desktops_picker_directly():
    for rel in ("views", "plugins", "tools"):
        for path in (ROOT / rel).rglob("*.py"):
            if path.name == "color_dialog.py":
                continue
            assert "QColorDialog.getColor(" not in path.read_text("utf-8"), path


def test_a_menu_entrys_description_shows_in_the_status_bar():
    """#213: hovering a menu entry sends its status tip through Qt's own
    showMessage, which bypassed the bar's label — nothing showed."""
    from PySide6.QtGui import QStatusTipEvent
    from views.main_window import MainWindow
    w = MainWindow()
    try:
        bar = w.statusBar()
        bar.showMessage("standing hint")
        QApplication.sendEvent(w, QStatusTipEvent("Take back the last change to the model."))
        assert bar.currentMessage() == "Take back the last change to the model."
        QApplication.sendEvent(w, QStatusTipEvent(""))
        assert bar.currentMessage() == "standing hint"
    finally:
        w._saved_version = w.viewport.scene.version
        w.close()
