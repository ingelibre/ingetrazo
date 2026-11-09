# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A shortcut recorded with Shift on the digit row keeps the digit (#493,
@pacaeiro): Qt reports the symbol the layout types — Shift+5 arrives as
«%» — and the shortcut was saved as «Shift+%». Qt fires «Shift+5» on a
real Shift+5 (checked by hand on xcb and Wayland, 10-10)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _press(key, text, scan, mods=Qt.ShiftModifier):
    from views.shortcuts import _KeyCapture
    box = _KeyCapture()
    box.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, mods, scan, 0, 0, text))
    return box.keySequence().toString(QKeySequence.PortableText)


def test_shift_on_the_digit_row_keeps_the_digit():
    # xkb keycode 14 is the «5» key, whatever the layout prints on it
    assert _press(Qt.Key_Percent, "%", 14) == "Shift+5"
    assert _press(Qt.Key_Exclam, "!", 10) == "Shift+1"
    assert _press(Qt.Key_ParenRight, ")", 19) == "Shift+0"


def test_ctrl_shift_on_the_digit_row_too():
    mods = Qt.ShiftModifier | Qt.ControlModifier
    assert _press(Qt.Key_Percent, "%", 14, mods) == "Ctrl+Shift+5"


def test_other_shifted_keys_are_left_alone():
    assert _press(Qt.Key_Question, "?", 61) == "Shift+?"        # «/» key
    assert _press(Qt.Key_A, "A", 38) == "Shift+A"
    assert _press(Qt.Key_5, "5", 14, Qt.NoModifier) == "5"
