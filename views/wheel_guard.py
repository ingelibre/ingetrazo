# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fields in a scrolling panel answer the wheel only when they have the focus.

A panel of properties is nearly all fields: a wheel notch meant to scroll
it landed on whichever one was under the pointer, changed its value, and
the scrolling stopped there (#1163).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QAbstractSpinBox, QComboBox, QSlider,
                               QWidget)


class _WheelGuard(QObject):
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Wheel and not obj.hasFocus():
            # Ignored, not swallowed: Qt hands it on to the parents, up to
            # the scroll area that wanted it.
            event.ignore()
            return True
        return False


def guard_wheel(root: QWidget) -> None:
    """Every field under ``root`` as it stands. The default focus policy
    would also let the first notch give the field the focus, and the next
    ones change it, so they go to StrongFocus: the Tab key and a click."""
    guard = _WheelGuard(root)
    for kind in (QAbstractSpinBox, QComboBox, QSlider):
        for field in root.findChildren(kind):
            field.setFocusPolicy(Qt.StrongFocus)
            field.installEventFilter(guard)
