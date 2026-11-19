# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The colour picker every panel opens: Qt's own dialog, not the desktop's.

On GNOME the native picker is GTK's small palette, and opened from a
right-click menu it came back without the colour chosen — editing a
material's colour did nothing (Marco, testing 0.5.7). Qt's dialog is the
same on Linux, Windows and macOS: a colour wheel, RGB, HSV, a hex field
and custom colours.

For materials and layer colours it also gets an Opacity row: a 0–100
slider and spin box, easier to work with than Qt's lone 0–255 alpha field.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QDialog, QHBoxLayout, QLabel,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from core.i18n import tr


class _OpacityColorDialog(QColorDialog):
    """Qt's cross-platform picker with a percent opacity control."""

    def __init__(self, initial: QColor, parent=None, title: str = "",
                 options=QColorDialog.ColorDialogOption(0)) -> None:
        initial = QColor(initial)
        opacity = round(initial.alphaF() * 100.0) if initial.isValid() else 100
        super().__init__(initial, parent)
        if title:
            self.setWindowTitle(title)
        self.setOptions(
            options | QColorDialog.ColorDialogOption.DontUseNativeDialog)
        # The percent slider replaces Qt's small 0–255 Alpha channel box.
        self.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)

        panel = QWidget(self)
        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 8, 0, 4)
        column.setSpacing(4)
        label = QLabel(tr("Opacity"), panel)
        column.addWidget(label)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.opacity_slider = QSlider(Qt.Horizontal, panel)
        self.opacity_slider.setObjectName("colour_opacity_slider")
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setMinimumWidth(220)
        self.opacity_spin = QSpinBox(panel)
        self.opacity_spin.setObjectName("colour_opacity_spin")
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setSuffix(" %")
        self.opacity_spin.setFixedWidth(76)
        self.opacity_slider.valueChanged.connect(self.opacity_spin.setValue)
        self.opacity_spin.valueChanged.connect(self.opacity_slider.setValue)
        self.opacity_slider.setValue(opacity)
        row.addWidget(self.opacity_slider, 1)
        row.addWidget(self.opacity_spin)
        column.addLayout(row)

        layout = self.layout()
        if isinstance(layout, QVBoxLayout):
            layout.insertWidget(max(0, layout.count() - 1), panel)
        else:                              # defensive: another Qt style
            layout.addWidget(panel)
        self.currentColorChanged.connect(self._refresh_opacity_track)
        self._refresh_opacity_track(initial)

    def _refresh_opacity_track(self, color: QColor) -> None:
        """Gradient from clear to opaque in the colour being edited."""
        color = QColor(color)
        r, g, b = color.red(), color.green(), color.blue()
        pal = self.opacity_slider.palette()
        dark = pal.window().color().lightness() < 128
        border = "#8b929d" if dark else "#9aa1ad"
        handle = "#f1f2f4" if dark else "#ffffff"
        self.opacity_slider.setStyleSheet(
            "QSlider::groove:horizontal {"
            " height:16px;"
            f" background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 rgba({r},{g},{b},0),"
            f" stop:1 rgba({r},{g},{b},255));"
            f" border:1px solid {border}; border-radius:2px; }}"
            "QSlider::handle:horizontal {"
            f" background:{handle}; border:1px solid {border};"
            " width:7px; margin:-4px 0; border-radius:1px; }")
        self.opacity_slider.setMinimumHeight(26)

    def picked_color(self) -> QColor:
        color = QColor(self.currentColor())
        color.setAlphaF(self.opacity_slider.value() / 100.0)
        return color


def get_color(*args, **kwargs):
    """``QColorDialog.getColor`` with Qt's own dialog.

    ``ShowAlphaChannel`` requests the friendlier opacity row above instead
    of Qt's built-in alpha spin box.
    """
    own = QColorDialog.ColorDialogOption.DontUseNativeDialog
    options = (kwargs.get("options") if "options" in kwargs else
               args[3] if len(args) > 3 else None)
    options = options if options is not None else \
        QColorDialog.ColorDialogOption(0)
    alpha = QColorDialog.ColorDialogOption.ShowAlphaChannel
    if options & alpha:
        initial = args[0] if args else kwargs.get("initial", QColor("white"))
        parent = args[1] if len(args) > 1 else kwargs.get("parent")
        title = args[2] if len(args) > 2 else kwargs.get("title", "")
        dialog = _OpacityColorDialog(initial, parent, title, options)
        return (dialog.picked_color()
                if dialog.exec() == QDialog.DialogCode.Accepted else QColor())
    # Preserve the static method's positional calling convention too: adding
    # a second ``options`` value as a keyword would fail at runtime.
    if len(args) > 3 and "options" not in kwargs:
        args = (*args[:3], options | own, *args[4:])
    else:
        kwargs["options"] = options | own
    return QColorDialog.getColor(*args, **kwargs)
