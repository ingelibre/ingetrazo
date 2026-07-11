# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Protractor tool (H): create ANGLED guide lines — SketchUp's Protractor.

Flow (SketchUp):
1. Click the VERTEX where the angle is measured (clicking on a face aligns
   the protractor plane to it; empty ground measures in plan).
2. Click along the BASE direction (snap to an edge endpoint — a roof eave,
   a lot line — to measure from it).
3. Move to sweep the angle and click: an infinite dashed GUIDE line through
   the vertex at that angle is created. Typing degrees + Enter (VCB) commits
   the exact angle — how a 27.5° roof pitch or a battered wall is set out.

Guides are scaffolding, not geometry: they feed the snap engine so Line /
Rectangle can lock onto the angled direction, and are deleted from Edit ▸
Delete Guides like the Tape Measure ones.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.guide import Guide
from core.history import AddGuideCommand
from core.triangulate import plane_axes
from tools.base import Tool, ToolContext


class ProtractorTool(Tool):
    name = "Protractor"
    shortcut = "H"
    vcb_label = "Angle"

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None   # the protractor centre
        self.ref_point: QVector3D | None = None     # base (0°) direction
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
        if self.ref_point is None:
            if (ctx.world - self.start_point).length() < 1e-6:
                return
            self.ref_point = ctx.world
            return
        deg = self._angle_to(ctx.world)
        if deg is not None:
            self._commit(ctx.viewport, deg)

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        ctx.viewport.update()

    def on_value(self, viewport, value) -> bool:
        if self.ref_point is None or isinstance(value, tuple):
            return False
        sign = 1.0
        if self.hover_point is not None:
            cur = self._angle_to(self.hover_point)
            if cur is not None and cur < 0:
                sign = -1.0
        self._commit(viewport, sign * abs(value))
        return True

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- Preview ------------------------------------------------------------
    def rubber_band_lines(self):
        if self.start_point is None or self.hover_point is None:
            return []
        segments = [(self.start_point, self.hover_point)]
        segments.extend(self._protractor_circle())
        if self.ref_point is not None:
            segments.append((self.start_point, self.ref_point))
            deg = self._angle_to(self.hover_point)
            if deg is not None:
                d = self._direction_at(deg)
                # Preview of the future guide, long enough to read as a line.
                segments.append((self.start_point - d * 50.0,
                                 self.start_point + d * 50.0))
        return segments

    def value_label(self):
        if self.ref_point is None or self.hover_point is None:
            return None
        deg = self._angle_to(self.hover_point)
        if deg is None:
            return None
        return (f"{deg:+.1f}°", self.hover_point)

    def vcb_caption(self) -> str:
        return "Angle" if self.ref_point is not None else "Radius"

    # ---- Internals ----------------------------------------------------------
    def _axis(self) -> QVector3D:
        if self.work_plane is not None:
            return self.work_plane[1].normalized()
        return QVector3D(0.0, 0.0, 1.0)

    def _angle_to(self, point: QVector3D) -> float | None:
        u, v = plane_axes(self._axis())
        a = self.ref_point - self.start_point
        b = point - self.start_point
        a2 = (QVector3D.dotProduct(a, u), QVector3D.dotProduct(a, v))
        b2 = (QVector3D.dotProduct(b, u), QVector3D.dotProduct(b, v))
        if math.hypot(*a2) < 1e-9 or math.hypot(*b2) < 1e-9:
            return None
        deg = math.degrees(math.atan2(b2[1], b2[0]) - math.atan2(a2[1], a2[0]))
        while deg <= -180.0:
            deg += 360.0
        while deg > 180.0:
            deg -= 360.0
        return deg

    def _direction_at(self, deg: float) -> QVector3D:
        """Unit direction of the base arm rotated by ``deg`` in the plane."""
        u, v = plane_axes(self._axis())
        a = self.ref_point - self.start_point
        a0 = math.atan2(QVector3D.dotProduct(a, v), QVector3D.dotProduct(a, u))
        t = a0 + math.radians(deg)
        return (u * math.cos(t) + v * math.sin(t)).normalized()

    def _protractor_circle(self):
        anchor = self.ref_point or self.hover_point
        if anchor is None:
            return []
        r = (anchor - self.start_point).length()
        if r < 1e-9:
            return []
        u, v = plane_axes(self._axis())
        pts = [self.start_point + (u * math.cos(2 * math.pi * k / 24)
                                   + v * math.sin(2 * math.pi * k / 24)) * r
               for k in range(24)]
        return [(pts[k], pts[(k + 1) % 24]) for k in range(24)]

    def _commit(self, viewport, deg: float) -> None:
        d = self._direction_at(deg)
        viewport.history.execute(
            AddGuideCommand(Guide(self.start_point, d)))
        # Stay on the same centre/base so several angles can be set out in a
        # row (SketchUp keeps the protractor placed); Esc resets.
        viewport.update()

    def _reset(self) -> None:
        self.start_point = None
        self.ref_point = None
        self.work_plane = None
