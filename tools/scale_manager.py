# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Scale Manager dialog and its temporary viewport pivot pickers."""
from __future__ import annotations

from PySide6.QtCore import QTimer

from core.i18n import tr
from tools.base import Tool
from tools.scale import ScaleTool


class _TargetBox(ScaleTool):
    def __init__(self, group) -> None:
        super().__init__()
        self._target = group

    def _selection_bounds(self, viewport, selection=None):
        return super()._selection_bounds(viewport, [self._target])


class ScaleManagerTool(Tool):
    name = "Scale Manager"

    def __init__(self) -> None:
        self.target = None
        self._dialog = None
        self._mode = None
        self._box = None

    @property
    def uses_snap(self) -> bool:
        return self._mode == "point"

    @property
    def dragging(self) -> bool:
        return self._mode is not None

    @property
    def cancel_before_constraints(self) -> bool:
        return self._mode is not None

    def on_activate(self, viewport) -> None:
        target, self.target = self.target, None
        if target is None:
            viewport.flash_status(tr("Select one group or component first"))
            return
        QTimer.singleShot(0, lambda: self._run(viewport, target))

    def on_deactivate(self, viewport) -> None:
        self.target = None
        self._mode = None
        self._box = None
        dialog, self._dialog = self._dialog, None
        if dialog is not None:
            dialog.reject()
            dialog.deleteLater()

    def _run(self, viewport, group) -> None:
        if viewport.active_tool is not self:
            return
        from views.scale_dialog import ScaleDialog
        window = viewport.window()
        dialog = ScaleDialog(window, group,
                             lambda mode: self._start_pick(viewport, group, mode))
        self._dialog = dialog
        dialog.finished.connect(lambda _result: self._closed(viewport, dialog))
        dialog.open()

    def _closed(self, viewport, dialog) -> None:
        if self._dialog is not dialog:
            return
        self._dialog = None
        self._mode = None
        self._box = None
        dialog.deleteLater()
        viewport.update()
        if viewport.active_tool is self:
            viewport.window()._activate_tool("select")

    def _start_pick(self, viewport, group, mode: str) -> None:
        self._mode = mode
        self._box = _TargetBox(group) if mode == "box" else None
        if self._box is not None:
            self._box.on_activate(viewport)
            viewport.flash_status(tr("Click a bounding box grip, or press Esc"))
        else:
            viewport.flash_status(tr("Click an inference point, or press Esc"))
        viewport.setFocus()
        viewport.update()

    def _finish_pick(self, viewport, point=None) -> None:
        self._mode = None
        self._box = None
        viewport.update()
        if self._dialog is not None:
            self._dialog.finish_pick(point)

    def on_click(self, ctx) -> None:
        if self._mode == "box" and self._box is not None:
            self._box._refresh_box(ctx.viewport)
            grip = self._box._grip_under(ctx.viewport, ctx.screen.x(),
                                         ctx.screen.y())
            if grip is not None:
                self._finish_pick(ctx.viewport, self._box._grip_pos(grip))
        elif self._mode == "point" and ctx.snap.kind != "none":
            self._finish_pick(ctx.viewport, ctx.world)

    def on_hover(self, ctx) -> None:
        if self._mode == "box" and self._box is not None:
            self._box.on_hover(ctx)

    def on_cancel(self, viewport) -> None:
        if self._mode is not None:
            self._finish_pick(viewport)

    def scale_box_state(self):
        return self._box.scale_box_state() if self._box is not None else None
