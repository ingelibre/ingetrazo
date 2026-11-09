# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Scale Manager: right-click a group or component ▸ Scale…, a modal with
its X, Y, Z scale, Blender style (views/scale_dialog.py). The tool only
opens the dialog for ``target`` — set by whoever activates it (the context
menu) — and hands the viewport back to Select when it closes."""
from __future__ import annotations

from PySide6.QtCore import QTimer

from core.i18n import tr
from tools.base import Tool


class ScaleManagerTool(Tool):
    name = "Scale Manager"

    def __init__(self) -> None:
        self.target = None

    def on_activate(self, viewport) -> None:
        target, self.target = self.target, None
        if target is None:
            viewport.flash_status(tr("Select one group or component first"))
            return
        QTimer.singleShot(0, lambda: self._run(viewport, target))

    def on_deactivate(self, viewport) -> None:
        self.target = None

    @staticmethod
    def _run(viewport, group) -> None:
        from views.scale_dialog import ask_scale
        window = viewport.window()
        ask_scale(window, group)
        viewport.update()
        window._activate_tool("select")
