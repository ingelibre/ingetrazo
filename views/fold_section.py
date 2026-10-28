# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Pieces for panels that live in the narrow side tray: a section that
folds away with a click on its title, and helpers that let controls shrink
with the tray instead of forcing it wider (#181: a horizontal scroll bar
and cut-off buttons with room to spare). Shared by the Render and AI tabs."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QComboBox, QFormLayout, QFrame, QLabel,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)


class FoldSection(QWidget):
    """A titled part of a panel that folds away with a click on its title
    (Marco: «que los campos … se puedan contraer»); whether it is open is
    remembered under ``settings_key``. Fill ``body``."""

    def __init__(self, title: str, settings_key: str, parent=None,
                 default_open: bool = True) -> None:
        super().__init__(parent)
        self._key = settings_key
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.header = QToolButton()
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.setStyleSheet("QToolButton { border: none; "
                                  "font-weight: bold; text-align: left; "
                                  "padding: 3px 0; }")
        lay.addWidget(self.header)
        self.body = QFrame()
        self.body.setFrameShape(QFrame.StyledPanel)
        lay.addWidget(self.body, 1)
        stored = QSettings().value(self._key, "1" if default_open else "0")
        is_open = str(stored) != "0"
        self.header.setChecked(is_open)
        self._show(is_open)
        self.header.toggled.connect(self._toggled)

    def set_open(self, on: bool) -> None:
        self.header.setChecked(on)

    def _toggled(self, on: bool) -> None:
        QSettings().setValue(self._key, "1" if on else "0")
        self._show(on)

    def _show(self, on: bool) -> None:
        self.header.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.body.setVisible(on)


def narrow(*widgets) -> None:
    """Let each control shrink with a narrow side tray."""
    for w in widgets:
        if isinstance(w, QComboBox):
            w.setSizeAdjustPolicy(
                QComboBox.AdjustToMinimumContentsLengthWithIcon)
            w.setMinimumContentsLength(6)
        else:
            w.setSizePolicy(QSizePolicy.Ignored, w.sizePolicy().verticalPolicy())
            w.setMinimumWidth(40)


class WrapLabel(QLabel):
    """A word-wrapped label that asks for every line it wraps to.

    The tray's dock does not ask its panel for height-for-width, so a
    section was laid out with the label's ONE-line hint and the wrapped
    second line was cut in half (the key link of the AI tab in Korean,
    #998 review). The hint now carries the wrapped height at the current
    width. A hint, not a minimum: while Restore default panels stacks the
    trays the panel is briefly very narrow, and a minimum for that width
    grew the window and kept it grown."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self._hint_width = -1

    def sizeHint(self):  # noqa: N802 — Qt override
        hint = super().sizeHint()
        need = self.heightForWidth(self.width()) if self.text() else 0
        if need > hint.height():
            hint.setHeight(need)
        return hint

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt override
        super().resizeEvent(event)
        if self.width() != self._hint_width:
            self._hint_width = self.width()
            self.updateGeometry()


def wrapping_form(parent) -> QFormLayout:
    """A form that puts each label above its field when the tray is narrow."""
    form = QFormLayout(parent)
    form.setRowWrapPolicy(QFormLayout.WrapLongRows)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    return form
