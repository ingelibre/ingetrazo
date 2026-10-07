# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The colour picker every panel opens: Qt's own dialog, not the desktop's.

On GNOME the native picker is GTK's small palette, and opened from a
right-click menu it came back without the colour chosen — editing a
material's colour did nothing (Marco, testing 0.5.7). Qt's dialog is the
same on Linux, Windows and macOS: a colour wheel, RGB, HSV, a hex field
and custom colours."""
from __future__ import annotations

from core.i18n import tr
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QColorDialog, QHBoxLayout, QLabel, QSlider, QWidget


def get_color(*args, **kwargs):
    """``QColorDialog.getColor`` with Qt's own dialog."""
    checker_preview = kwargs.pop("checker_preview", False)
    if checker_preview:
        dialog = _TransparencyColorDialog(args[0], args[1] if len(args) > 1 else None)
        if len(args) > 2:
            dialog.setWindowTitle(args[2])
        if dialog.exec() == QColorDialog.Accepted:
            return dialog.color_with_transparency()
        return QColor()
    kwargs.setdefault("options",
                      QColorDialog.ColorDialogOption.DontUseNativeDialog)
    return QColorDialog.getColor(*args, **kwargs)


def paint_color_swatch(painter, rect, color, tile=4):
    """Composite translucent color over a neutral checkerboard."""
    rect = QRectF(rect)
    painter.save()
    clip = QPainterPath()
    clip.addRoundedRect(rect, 2, 2)
    painter.setClipPath(clip)
    if color.alpha() < 255:
        for row, y in enumerate(range(int(rect.top()), int(rect.bottom()) + 1, tile)):
            for column, x in enumerate(range(int(rect.left()), int(rect.right()) + 1, tile)):
                painter.fillRect(QRectF(x, y, tile, tile),
                                 QColor("#eeeeee" if (row + column) % 2 else "#aaaaaa"))
    painter.fillRect(rect, color)
    painter.restore()


class _ColorPreview(QWidget):
    def __init__(self, color, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setMinimumHeight(36)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        paint_color_swatch(painter, self.rect().adjusted(0, 2, 0, -2), self._color, tile=8)


class _TransparencyColorDialog(QColorDialog):
    """A percentage slider with 0% opaque, independent of Qt's alpha field."""
    def __init__(self, initial, parent=None):
        opaque = QColor(initial)
        opaque.setAlpha(255)
        super().__init__(opaque, parent)
        self.setOptions(QColorDialog.ColorDialogOption.DontUseNativeDialog)
        self._transparency = QSlider(Qt.Horizontal, self)
        self._transparency.setRange(0, 100)
        self._transparency.setValue(round((1. - initial.alphaF()) * 100))
        self._transparency.setAccessibleName(tr("Transparency"))
        self._value = QLabel(self)
        self._preview = _ColorPreview(initial, self)
        for title, controls in ((tr("Transparency:"), (self._transparency, self._value)),
                                (tr("Preview"), (self._preview,))):
            row = QWidget(self)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(QLabel(title, row))
            for control in controls:
                layout.addWidget(control, 1 if control is not self._value else 0)
            self.layout().insertWidget(self.layout().count() - 1, row)
        self._transparency.valueChanged.connect(self._update_preview)
        self.currentColorChanged.connect(self._update_preview)
        self._update_preview()

    def color_with_transparency(self):
        color = QColor(self.currentColor())
        color.setAlphaF(1. - self._transparency.value() / 100.)
        return color

    def _update_preview(self, *_):
        self._value.setText(f"{self._transparency.value()}%")
        self._preview.set_color(self.color_with_transparency())
