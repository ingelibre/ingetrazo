# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Every colour picker is Qt's own dialog: on GNOME the native one is a
small GTK palette, and opened from a right-click menu it came back without
the colour chosen, so editing a material's colour did nothing (0.5.7)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QColorDialog, QDialog  # noqa: E402

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


def test_the_picker_keeps_positional_options_positional(monkeypatch):
    from views import color_dialog
    seen = {}

    def fake(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return QColor(10, 20, 30)

    monkeypatch.setattr(color_dialog.QColorDialog, "getColor", fake)
    color_dialog.get_color(QColor(0, 0, 0), None, "Colour",
                           QColorDialog.ColorDialogOption.NoButtons)
    assert len(seen["args"]) == 4 and "options" not in seen["kwargs"]
    assert seen["args"][3] & \
        QColorDialog.ColorDialogOption.DontUseNativeDialog


def test_alpha_uses_the_opacity_slider_and_keeps_qts_own_dialog(monkeypatch):
    from views import color_dialog
    seen = []

    def fake_exec(dialog):
        seen.append(dialog)
        dialog.setCurrentColor(QColor(10, 20, 30))
        dialog.opacity_slider.setValue(25)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(color_dialog._OpacityColorDialog, "exec", fake_exec)
    alpha = QColorDialog.ColorDialogOption.ShowAlphaChannel
    picked = color_dialog.get_color(QColor(0, 0, 0, 128), options=alpha)
    assert seen and picked.alphaF() == pytest.approx(0.25, abs=0.01)
    dialog = seen[0]
    assert dialog.testOption(
        QColorDialog.ColorDialogOption.DontUseNativeDialog)
    assert not dialog.testOption(alpha)       # replaced by the percent row


def test_opacity_slider_and_number_stay_in_sync():
    from views.color_dialog import _OpacityColorDialog
    dialog = _OpacityColorDialog(QColor(20, 120, 200, 64))
    assert dialog.opacity_slider.value() == dialog.opacity_spin.value() == 25
    assert dialog.opacity_spin.suffix() == " %"
    dialog.opacity_spin.setValue(37)
    assert dialog.opacity_slider.value() == 37
    dialog.opacity_slider.setValue(62)
    assert dialog.opacity_spin.value() == 62
    assert "qlineargradient" in dialog.opacity_slider.styleSheet()


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
