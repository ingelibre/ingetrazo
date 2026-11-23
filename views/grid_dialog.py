# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""View ▸ Grid Settings… (#780): the drawing grid of the document.

Spacing in the document's units (``50cm``, ``1m``, ``1'`` are all taken),
how many divisions between two major lines and the line colour, automatic
by default (it follows the ground or the background behind it).
"""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QFormLayout, QHBoxLayout, QPushButton,
                               QSpinBox, QWidget)

from core import grid as gridmod
from core.i18n import tr
from views.length_field import LengthSpinBox


class GridDialog(QDialog):
    """Edits a copy of the grid settings; :meth:`settings` is the result."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Grid Settings"))
        self._color = settings.get("color")
        form = QFormLayout(self)

        self.visible_box = QCheckBox(tr("Show the grid"))
        self.visible_box.setChecked(bool(settings.get("visible")))
        form.addRow(self.visible_box)
        self.snap_box = QCheckBox(tr("Snap to Grid"))
        self.snap_box.setChecked(bool(settings.get("snap")))
        form.addRow(self.snap_box)

        self.spacing = LengthSpinBox(self, minimum=gridmod.MIN_SPACING,
                                     maximum=gridmod.MAX_SPACING)
        self.spacing.setValue(float(settings.get("spacing", 1.0)))
        self.spacing.setAccessibleName(tr("Spacing:"))
        form.addRow(tr("Spacing:"), self.spacing)

        self.major = QSpinBox(self)
        self.major.setRange(gridmod.MIN_MAJOR, gridmod.MAX_MAJOR)
        self.major.setValue(int(settings.get("major", gridmod.DEFAULT_MAJOR)))
        self.major.setAccessibleName(tr("Major line every:"))
        self.major.setSuffix(" " + tr("divisions"))
        form.addRow(tr("Major line every:"), self.major)

        row = QWidget(self)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        self.auto_color = QCheckBox(tr("Automatic"))
        self.auto_color.setChecked(self._color is None)
        self.color_button = QPushButton(tr("Choose…"))
        self.color_button.clicked.connect(self._pick_color)
        self.auto_color.toggled.connect(self._sync_color)
        lay.addWidget(self.auto_color)
        lay.addWidget(self.color_button)
        lay.addStretch(1)
        form.addRow(tr("Line color:"), row)
        self._sync_color()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _sync_color(self) -> None:
        auto = self.auto_color.isChecked()
        self.color_button.setEnabled(not auto)
        rgb = self._color if self._color is not None else (0.5, 0.5, 0.5)
        swatch = QColor.fromRgbF(*rgb)
        self.color_button.setStyleSheet(
            "" if auto else f"background:{swatch.name()};")

    def _pick_color(self) -> None:
        from views.color_dialog import get_color
        rgb = self._color if self._color is not None else (0.5, 0.5, 0.5)
        chosen = get_color(QColor.fromRgbF(*rgb), self, tr("Line color:"))
        if chosen.isValid():
            self._color = (chosen.redF(), chosen.greenF(), chosen.blueF())
            self._sync_color()

    def settings(self) -> dict:
        return {"visible": self.visible_box.isChecked(),
                "snap": self.snap_box.isChecked(),
                "spacing": float(self.spacing.value()),
                "major": int(self.major.value()),
                "color": (None if self.auto_color.isChecked()
                          else self._color)}
