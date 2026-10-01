# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Alt+X switches X-ray on and back off.

A look through the faces is a glance: the key goes into X-ray and, pressed
again, returns to the style you were in, edge and profile settings included.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def _window():
    from views.main_window import MainWindow
    return MainWindow()


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_alt_x_is_the_toggle_and_no_other_action_holds_it():
    from views.shortcuts import collect_actions
    win = _window()
    try:
        alt_x = QKeySequence("Alt+X")
        assert win._act_xray_toggle.shortcut() == alt_x
        holders = [a for a in collect_actions(win) if alt_x in a.shortcuts()]
        assert holders == [win._act_xray_toggle]
    finally:
        _close(win)


def test_the_toggle_goes_back_to_the_style_you_left():
    from core.style import style_by_name
    win = _window()
    try:
        win._apply_display_style(style_by_name("Shaded"))
        win._set_style_field("profiles", True)
        win._act_xray_toggle.trigger()
        style = win.viewport.scene.display_style
        assert style.face_mode == "xray"
        assert win._style_actions["X-ray"].isChecked()

        win._act_xray_toggle.trigger()
        style = win.viewport.scene.display_style
        assert style.name == "Shaded" and style.face_mode == "shaded"
        assert style.profiles is True              # your tweak came back too
        assert win._style_actions["Shaded"].isChecked()
    finally:
        _close(win)


def test_xray_picked_from_the_menu_toggles_out_to_default():
    from core.style import style_by_name
    win = _window()
    try:
        win._apply_display_style(style_by_name("X-ray"))
        win._act_xray_toggle.trigger()
        assert win.viewport.scene.display_style.name == "Default"
    finally:
        _close(win)
