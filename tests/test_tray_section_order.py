# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sidebar sections dragged into another order (PR #441): the order is kept
in the settings and the next stack built from the same sections comes up
in it; a stack with no saved order keeps the order it is given."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QTextEdit  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _titles(stack):
    lay = stack._layout
    return [lay.itemAt(i).widget()._btn.text().strip()
            for i in range(lay.count())]


def _sections():
    return [("Label", QLabel("a")), ("Line", QLineEdit()),
            ("Text", QTextEdit())]


def test_default_order_is_the_given_one():
    from views.tray import _SectionStack
    stack = _SectionStack(_sections())
    QSettings().remove(stack._order_key)
    stack = _SectionStack(_sections())
    assert [t.split()[-1] for t in _titles(stack)] == ["Label", "Line", "Text"]
    assert stack._layout.spacing() == 2


def test_a_saved_order_comes_back():
    from views.tray import _SectionStack
    stack = _SectionStack(_sections())
    try:
        QSettings().setValue(stack._order_key,
                             ["QTextEdit", "QLabel", "QLineEdit"])
        again = _SectionStack(_sections())
        assert [t.split()[-1] for t in _titles(again)] == ["Text", "Label",
                                                           "Line"]
    finally:
        QSettings().remove(stack._order_key)
