"""Arc tool: two endpoints (the chord), then a bulge.

SketchUp's 2-point arc:
1. click the start point,
2. click the end point — the chord,
3. move to bulge the arc out from the chord, click to commit.

The arc is committed as a polyline of short edges (it auto-faces if it closes a
region with existing geometry). The bulge can be typed in the VCB.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.triangulate import plane_axes
from tools.base import Tool, ToolContext

_SEGMENTS = 16  # polyline segments approximating the arc


def _circumcenter2(a, b, c):
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    return (ux, uy)


def _wrap(a: float) -> float:
    while a <= -math.pi:
        a += 2.0 * math.pi
    while a > math.pi:
        a -= 2.0 * math.pi
    return a


class ArcTool(Tool):
    name = "Arc"
    shortcut = "A"
    vcb_label = "Bulge"

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None
        self.end_point: QVector3D | None = None
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
        if self.end_point is None:
            if (ctx.world - self.start_point).length() < 1e-6:
                return
            self.end_point = ctx.world
            return
        pts = self._points(ctx.world)
        if len(pts) >= 2:
            self._commit(ctx.viewport, pts)

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        ctx.viewport.update()

    def on_value(self, viewport, value) -> bool:
        if self.end_point is None or self.hover_point is None:
            return False
        if isinstance(value, tuple):
            return False
        sign = -1.0 if self._bulge_for(self.hover_point) < 0 else 1.0
        pts = self._points(None, bulge=sign * value)
        if len(pts) >= 2:
            self._commit(viewport, pts)
        return True

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- Preview ------------------------------------------------------------
    def rubber_band_lines(self):
        if self.start_point is None or self.hover_point is None:
            return []
        if self.end_point is None:
            return [(self.start_point, self.hover_point)]   # the chord
        pts = self._points(self.hover_point)
        return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]

    def value_label(self):
        if self.end_point is None or self.hover_point is None:
            return None
        b = self._bulge_for(self.hover_point)
        mid = (self.start_point + self.end_point) * 0.5
        return (f"Bulge {abs(b):.2f} m", mid)

    # ---- Internals ----------------------------------------------------------
    def _axes(self) -> tuple[QVector3D, QVector3D]:
        normal = (self.work_plane[1] if self.work_plane is not None
                  else QVector3D(0.0, 0.0, 1.0))
        return plane_axes(normal)

    def _to2(self, p, u, v):
        d = p - self.start_point
        return (QVector3D.dotProduct(d, u), QVector3D.dotProduct(d, v))

    def _bulge_for(self, cursor: QVector3D) -> float:
        """Signed perpendicular distance from the chord midpoint to the cursor."""
        u, v = self._axes()
        e2 = self._to2(self.end_point, u, v)
        length = math.hypot(*e2)
        if length < 1e-9:
            return 0.0
        px, py = -e2[1] / length, e2[0] / length
        mid = (e2[0] / 2.0, e2[1] / 2.0)
        c2 = self._to2(cursor, u, v)
        return (c2[0] - mid[0]) * px + (c2[1] - mid[1]) * py

    def _points(self, cursor, bulge: float | None = None) -> list[QVector3D]:
        u, v = self._axes()
        s2 = (0.0, 0.0)
        e2 = self._to2(self.end_point, u, v)
        length = math.hypot(*e2)
        if length < 1e-9:
            return []
        h = bulge if bulge is not None else self._bulge_for(cursor)
        if abs(h) < 1e-4:
            return [self.start_point, self.end_point]   # flat → straight chord
        px, py = -e2[1] / length, e2[0] / length
        mid = (e2[0] / 2.0, e2[1] / 2.0)
        apex = (mid[0] + px * h, mid[1] + py * h)
        center = _circumcenter2(s2, e2, apex)
        if center is None:
            return [self.start_point, self.end_point]
        cx, cy = center
        r = math.hypot(s2[0] - cx, s2[1] - cy)
        a0 = math.atan2(s2[1] - cy, s2[0] - cx)
        a1 = math.atan2(e2[1] - cy, e2[0] - cx)
        aa = math.atan2(apex[1] - cy, apex[0] - cx)
        d = _wrap(a1 - a0)
        da = _wrap(aa - a0)
        # Sweep the way that passes through the apex.
        if d >= 0 and not (0.0 <= da <= d):
            d -= 2.0 * math.pi
        elif d < 0 and not (d <= da <= 0.0):
            d += 2.0 * math.pi
        out = []
        for k in range(_SEGMENTS + 1):
            a = a0 + d * (k / _SEGMENTS)
            x = cx + r * math.cos(a)
            y = cy + r * math.sin(a)
            out.append(self.start_point + u * x + v * y)
        return out

    def _commit(self, viewport, pts: list[QVector3D]) -> None:
        segments = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        cmd = build_add_edges(viewport.scene, segments, detect_faces=True)
        viewport.history.execute(cmd)
        self._reset()
        viewport.update()

    def _reset(self) -> None:
        self.start_point = None
        self.end_point = None
        self.work_plane = None
