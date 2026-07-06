# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Rotated Rectangle tool: a rectangle at any angle on the work plane.

Three clicks, SketchUp-style:
1. first corner,
2. second corner — sets the base edge's **direction and length** (the rotation),
3. move to set the perpendicular width, click to commit.

The width can also be typed in the VCB after the base edge is set.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import AddFaceCommand
from core.triangulate import plane_axes
from tools.base import Tool, ToolContext


class RotatedRectangleTool(Tool):
    name = "Rotated Rect"
    shortcut = "K"
    vcb_label = "Width"

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None   # first corner (drives plane)
        self.base_point: QVector3D | None = None     # second corner
        self.hover_point: QVector3D | None = None
        self.work_plane: tuple[QVector3D, QVector3D] | None = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        if self.start_point is None:
            self.start_point = ctx.world
            return
        if self.base_point is None:
            if (ctx.world - self.start_point).length() < 1e-6:
                return
            self.base_point = ctx.world
            return
        corners = self._corners(self._width_for(ctx.world))
        if corners:
            self._commit(ctx.viewport, corners)

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        ctx.viewport.update()

    def on_value(self, viewport, value) -> bool:
        if self.base_point is None or self.hover_point is None:
            return False
        if isinstance(value, tuple) or value == 0.0:
            return False
        # Keep the side the cursor is on; override the magnitude.
        sign = -1.0 if self._width_for(self.hover_point) < 0 else 1.0
        corners = self._corners(sign * value)
        if corners:
            self._commit(viewport, corners)
        return True

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- Preview ------------------------------------------------------------
    def rubber_band_lines(self):
        if self.start_point is None or self.hover_point is None:
            return []
        if self.base_point is None:
            return [(self.start_point, self.hover_point)]   # drawing the base
        c = self._corners(self._width_for(self.hover_point))
        if not c:
            return [(self.start_point, self.base_point)]
        return [(c[i], c[(i + 1) % 4]) for i in range(4)]

    def value_label(self):
        if self.start_point is None or self.hover_point is None:
            return None
        if self.base_point is None:
            length = (self.hover_point - self.start_point).length()
            mid = (self.start_point + self.hover_point) * 0.5
            return (f"{length:.2f} m", mid)
        w = self._width_for(self.hover_point)
        length = (self.base_point - self.start_point).length()
        c = self._corners(w)
        mid = (self.start_point + c[2]) * 0.5 if c else self.base_point
        return (f"{length:.2f} × {abs(w):.2f} m", mid)

    # ---- Internals ----------------------------------------------------------
    def _perp(self) -> QVector3D:
        """In-plane unit vector perpendicular to the base edge."""
        normal = (self.work_plane[1] if self.work_plane is not None
                  else QVector3D(0.0, 0.0, 1.0))
        e = (self.base_point - self.start_point)
        if e.length() < 1e-9:
            return QVector3D(0.0, 0.0, 0.0)
        return QVector3D.crossProduct(normal.normalized(), e.normalized()).normalized()

    def _width_for(self, cursor: QVector3D) -> float:
        perp = self._perp()
        return QVector3D.dotProduct(cursor - self.base_point, perp)

    def _corners(self, width: float) -> list[QVector3D]:
        perp = self._perp()
        if perp.length() < 1e-6:
            return []
        off = perp * width
        return [self.start_point, self.base_point,
                self.base_point + off, self.start_point + off]

    def _commit(self, viewport, corners: list[QVector3D]) -> None:
        segments = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
        cmd = build_add_edges(
            viewport.scene, segments, detect_faces=False,
            extra=[AddFaceCommand(list(corners))])
        viewport.history.execute(cmd)
        self._reset()
        viewport.update()

    def _reset(self) -> None:
        self.start_point = None
        self.base_point = None
        self.work_plane = None
