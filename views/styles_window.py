# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Persistent window for browsing and editing the model's display style."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout

from core.i18n import tr
from views.icons import tool_icon


class StylesWindow(QDialog):
    """Keep the live style editor available while working in the viewport."""

    def __init__(self, window, panel) -> None:
        super().__init__(window)
        self.setObjectName("styles_window")
        self.setWindowTitle(tr("Styles"))
        self.setWindowIcon(tool_icon("styles"))
        self.setModal(False)
        self.setSizeGripEnabled(True)
        self.resize(400, 560)
        self.setMinimumSize(340, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(panel)
