# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The options of Export image: the picture's width and, for a format that
keeps an alpha channel, a transparent background."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel,
                               QSpinBox, QVBoxLayout)

from core.i18n import tr

#: The picture formats whose file keeps the alpha.
ALPHA_SUFFIXES = (".png",)


class ExportImageDialog(QDialog):
    def __init__(self, parent, suffix: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Export Image"))
        self.width_box = QSpinBox()
        self.width_box.setRange(640, 16384)
        self.width_box.setSingleStep(320)
        self.width_box.setValue(3840)
        self.transparent_box = QCheckBox(tr("Transparent background"))
        # Asked for each picture, like the width. A PNG starts with it on —
        # a picture to lay over a plan or a sheet wants no sky behind it —
        # and a JPEG, which cannot keep it, with it off and greyed.
        if suffix.lower() in ALPHA_SUFFIXES:
            self.transparent_box.setChecked(True)
        else:
            self.transparent_box.setEnabled(False)
            self.transparent_box.setToolTip(
                tr("Only PNG images keep transparency."))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Width in pixels:")))
        lay.addWidget(self.width_box)
        lay.addWidget(self.transparent_box)
        lay.addWidget(buttons)

    def transparent(self) -> bool:
        return (self.transparent_box.isEnabled()
                and self.transparent_box.isChecked())
