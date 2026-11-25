# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Status-bar boxes that do not shrink while their number runs.

Every new text of a QLabel asks its layout to run again, even when the
width it wants stays the same; in the status bar that lays the whole bar
out and repaints the window under it — ~5 ms in one frame of six of a Line
in a group of the Plaza (19-11). A label whose size is fixed asks nothing.
So while a measurement runs its box holds the widest width it has needed
(it grows when a longer number comes, never shrinks), and lets go when the
text empties or the tool changes (Marco, 19-11: «sí, hazlo con las casillas
que no encojan»)."""
from __future__ import annotations

QWIDGETSIZE_MAX = (1 << 24) - 1


def is_held(label) -> bool:
    return (label.minimumWidth() == label.maximumWidth()
            and label.minimumHeight() == label.maximumHeight())


def release(label, floor: int = 0) -> None:
    """The box sizes to its text again (``floor`` its minimum width)."""
    if is_held(label):
        label.setMinimumSize(floor, 0)
        label.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)


def set_text_held(label, text: str, floor: int = 0) -> None:
    """``label.setText(text)``, the box held at its widest width so far.
    An empty text lets it go. A label not laid out yet (hidden, or no
    height) just takes the text."""
    if label.text() == text:
        return
    if not text:
        release(label, floor)
        label.setText(text)
        return
    if not is_held(label):
        h = label.height()
        if not label.isVisible() or h <= 0:
            label.setText(text)
            return
        label.setFixedSize(max(label.width(), floor), h)
    label.setText(text)
    need = label.sizeHint().width()
    if need > label.width():
        label.setFixedWidth(need)          # a longer number: grow, once
