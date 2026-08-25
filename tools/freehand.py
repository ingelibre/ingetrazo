# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Freehand tool — SketchUp's Freehand (the Line tool's flyout).

Press and DRAG to sketch: the stroke samples the cursor, gets simplified
(Ramer–Douglas–Peucker in screen space, so zoom level = detail level, like
SketchUp), and lands as ONE curve entity — a polyline sharing a curve id,
so it selects as a whole contour exactly like circles and arcs. A stroke
that ends back at its start closes, and a closed flat stroke becomes a
face through the shared curve pipeline.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from tools.arc import commit_arc
from tools.base import Tool, ToolContext

_MIN_SAMPLE_PX = 3.0     # cursor must travel this far to add a sample
_SIMPLIFY_PX = 1.6       # RDP tolerance, in screen pixels
_CLOSE_PX = 10.0         # release near the start → the stroke closes


def _rdp(idx0: int, idx1: int, spts, keep) -> None:
    """Mark the screen-space RDP survivors between idx0 and idx1."""
    ax, ay = spts[idx0]
    bx, by = spts[idx1]
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    worst, worst_d = -1, _SIMPLIFY_PX
    for i in range(idx0 + 1, idx1):
        px, py = spts[i]
        if l2 < 1e-12:
            d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        else:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
            d = ((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2) ** 0.5
        if d > worst_d:
            worst, worst_d = i, d
    if worst >= 0:
        keep[worst] = True
        _rdp(idx0, worst, spts, keep)
        _rdp(worst, idx1, spts, keep)


class FreehandTool(Tool):
    name = "Freehand"
    uses_snap = False        # the stroke follows the hand, not the magnets

    def __init__(self) -> None:
        self.work_plane: tuple[QVector3D, QVector3D] | None = None
        self.start_point: QVector3D | None = None   # dispatcher plane-lock
        self._world: list[QVector3D] = []
        self._screen: list[tuple[float, float]] = []
        self._stroke = False

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()

    # ---- Input --------------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        self._stroke = True
        self.start_point = ctx.world
        self._world = [QVector3D(ctx.world)]
        self._screen = [(ctx.screen.x(), ctx.screen.y())]

    def on_hover(self, ctx: ToolContext) -> None:
        if not self._stroke:
            return
        sx, sy = ctx.screen.x(), ctx.screen.y()
        lx, ly = self._screen[-1]
        if ((sx - lx) ** 2 + (sy - ly) ** 2) < _MIN_SAMPLE_PX ** 2:
            return
        self._world.append(QVector3D(ctx.world))
        self._screen.append((sx, sy))
        ctx.viewport.update()

    def on_release(self, viewport) -> None:
        if not self._stroke:
            return
        world, screen = self._world, self._screen
        self._reset()
        if len(world) < 3:
            viewport.update()
            return
        # Close the loop when the hand came back to the start (SketchUp).
        sx, sy = screen[0]
        ex, ey = screen[-1]
        closed = ((ex - sx) ** 2 + (ey - sy) ** 2) <= _CLOSE_PX ** 2
        keep = [False] * len(world)
        keep[0] = keep[-1] = True
        _rdp(0, len(world) - 1, screen, keep)
        pts = [world[i] for i, k in enumerate(keep) if k]
        if closed and len(pts) >= 3:
            pts[-1] = QVector3D(pts[0])     # weld the seam exactly
        if len(pts) >= 2:
            commit_arc(viewport, pts)
        viewport.update()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- Preview ------------------------------------------------------------
    def rubber_band_lines(self):
        if len(self._world) < 2:
            return []
        return list(zip(self._world, self._world[1:]))

    def _reset(self) -> None:
        self._stroke = False
        self.start_point = None
        self.work_plane = None
        self._world = []
        self._screen = []
