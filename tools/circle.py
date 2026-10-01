# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Circle and Polygon tools: a centre click, then a radius.

Both draw a regular N-gon on the work plane (a circle is just a many-sided one,
the classic way). First click sets the centre; moving sets the radius; a second
click (or typing the radius in the VCB) commits the loop + face. One vertex
points toward the cursor, so a hexagon's orientation follows the mouse.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import (
    AddFaceCommand,
    RebuildPlanarFacesCommand,
    TagCurveCommand,
)


def flat_drawing(scene, new_points) -> bool:
    """Whether the whole drawing (existing mesh + the new loop) shares one
    plane — the gate for the classic planar arrangement, which forms
    every intersection face deterministically. 3D models keep the naive path."""
    from core.arrangement import coplanar_plane
    verts = [v.position for v in scene.mesh.vertices] + list(new_points)
    return coplanar_plane(verts) is not None


def busy_plane(scene, new_points):
    """``(origin, normal)`` of the plane the new loop lies on, when that plane
    already carries mesh content (edges or faces) — the gate for the scoped
    per-plane arrangement in 3D scenes. As soon as ANY solid exists, the
    whole-mesh flat gate goes dark; without this, a circle drawn over another
    circle on the ground stacks two full discs instead of splitting into three
    areas. ``None`` when the plane is virgin (naive path is enough)."""
    from core.arrangement import coplanar_plane
    plane = coplanar_plane(list(new_points))
    if plane is None:
        return None
    origin, normal = plane
    tol = 1e-4
    for e in scene.mesh.edges:
        if (abs(QVector3D.dotProduct(e.a - origin, normal)) < tol
                and abs(QVector3D.dotProduct(e.b - origin, normal)) < tol):
            return origin, normal
    return None
from core.i18n import tr
from core.axes import plane_axes  # drawing axes (#44)
from tools.base import AxisMagnet, PlaneLock, Tool, ToolContext


class _RadialTool(AxisMagnet, PlaneLock, Tool):
    """Shared centre+radius regular-polygon tool. Subclasses set ``sides``."""

    sides: int = 24
    vcb_label = "Radius"

    def vcb_caption(self) -> str:
        """'Sides' before the centre, 'Radius' after.

        Returns the English source label; the status bar translates it.
        """
        return "Radius" if self.start_point is not None else "Sides"

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None   # centre (also drives work plane)
        self.hover_point: QVector3D | None = None
        self.work_plane: tuple[QVector3D, QVector3D] | None = None
        self._viewport = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        self.note_plane(ctx.viewport)
        if self.start_point is None:
            self.start_point = ctx.world
            if self.work_plane is None:
                self.work_plane = self.locked_work_plane(ctx.world)
            return
        pts = self._points(self.start_point, ctx.world)
        if pts:
            self._commit(ctx.viewport, pts)

    def on_hover(self, ctx: ToolContext) -> None:
        self.note_plane(ctx.viewport)
        self._viewport = ctx.viewport
        self.hover_point = ctx.world
        self.wireframe_color = self.lock_color()
        ctx.viewport.update()

    def on_segments_value(self, viewport, n: int) -> bool:
        """The classic "24s": the side count, typed at any moment."""
        n = int(n)
        if n < 3:
            return False
        self.sides = n
        viewport.flash_status(tr("{n} sides", n=n))
        viewport.update()
        return True

    def value_is_unitless(self) -> bool:
        """Before the centre the typed number is a side COUNT (#176);
        after it, the radius, a length in the document's unit."""
        return self.start_point is None

    def on_value(self, viewport, value) -> bool:
        """Before the centre is placed, a typed number sets the **side count**
        (type sides + Enter); after it, the number is the **radius**."""
        if isinstance(value, tuple):
            return False
        if self.start_point is None:
            n = int(round(value))
            if n >= 3:
                self.sides = n
                viewport.flash_status(tr("{n} sides", n=n))
                return True
            return False
        if self.hover_point is None or value <= 0.0:
            return False
        # Keep the cursor's direction, override only the radius.
        u, v = self._axes()
        d = self.hover_point - self.start_point
        ang = math.atan2(QVector3D.dotProduct(d, v), QVector3D.dotProduct(d, u))
        rim = self.start_point + (u * math.cos(ang) + v * math.sin(ang)) * value
        pts = self._points(self.start_point, rim)
        if pts:
            self._commit(viewport, pts)
        return True

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- Preview ------------------------------------------------------------
    def rubber_band_lines(self):
        if self.hover_point is None:
            return []
        if self.start_point is None:
            return self._cursor_preview()
        pts = self._points(self.start_point, self.hover_point)
        return [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))] \
            if pts else []

    def value_label(self):
        if self.start_point is None or self.hover_point is None:
            return None
        # The radius DRAWN — the rim projected onto the plane — not the
        # straight distance to the cursor, which a snap off the plane
        # made longer than the circle («R 4.44» on a 2.41 m circle).
        u, v = self._axes()
        d = self.hover_point - self.start_point
        r = math.hypot(QVector3D.dotProduct(d, u), QVector3D.dotProduct(d, v))
        from core.units import fmt_len
        return ("R " + fmt_len(r) + "  (" + tr("{n} sides", n=self.sides) + ")",
                self.hover_point)

    # ---- Internals ----------------------------------------------------------
    def _cursor_preview(self):
        """The ring on the cursor before the centre is placed: the
        shape at a fixed screen size, lying on the plane it would take —
        so an arrow-key lock (drawn in the axis colour) or a face under
        the cursor is visible before committing (Rafael's review: «pulsas
        flechita y el círculo se te va orientando»)."""
        vp = self._viewport
        if vp is None:
            return []
        point, normal = self.preview_plane(vp, self.hover_point)
        u, v = plane_axes(normal)
        scale = self.world_per_pixel(vp, self.hover_point, u)
        if scale is None:
            return []
        r = self.PREVIEW_PX * scale
        n = max(int(self.sides), 3)
        pts = [self.hover_point + u * (r * math.cos(2 * math.pi * i / n))
               + v * (r * math.sin(2 * math.pi * i / n)) for i in range(n)]
        return [(pts[i], pts[(i + 1) % n]) for i in range(n)]

    def _axes(self) -> tuple[QVector3D, QVector3D]:
        return plane_axes(self.drawing_plane()[1])

    def plane_points(self):
        """Centre and rim: a rim snapped off the plane turns the circle to
        the axis plane holding both (``PlaneLock.snapped_plane``)."""
        if self.start_point is None:
            return []
        return [self.start_point, self.hover_point]

    def _points(self, center: QVector3D, rim: QVector3D) -> list[QVector3D]:
        u, v = self._axes()
        d = rim - center
        du, dv = QVector3D.dotProduct(d, u), QVector3D.dotProduct(d, v)
        r = math.hypot(du, dv)
        if r < 1e-6:
            return []
        a0 = math.atan2(dv, du)  # one vertex toward the cursor
        out = []
        for k in range(self.sides):
            a = a0 + 2.0 * math.pi * k / self.sides
            out.append(center + (u * math.cos(a) + v * math.sin(a)) * r)
        return out

    def _commit(self, viewport, pts: list[QVector3D]) -> None:
        n = len(pts)
        segments = [(pts[i], pts[(i + 1) % n]) for i in range(n)]
        # The outline is drawn (a 24-segment circle reads round). What hides is
        # only a *swept* curve's vertical facets — done by Push/Pull, not here.
        if flat_drawing(viewport.scene, pts):
            # Flat drawing: rebuild the plane's faces from the edge graph — the
            # deterministic planar arrangement. A circle crossing a square
            # splits both and every region (the quarter inside, the rest of the
            # disc) becomes its own face; an isolated circle still yields the
            # disc. TagCurve first so the rebuild carries the curve id over.
            extra = [TagCurveCommand(list(pts), closed=True),
                     RebuildPlanarFacesCommand()]
        elif (plane := busy_plane(viewport.scene, pts)) is not None:
            # 3D scene, but the drawing plane already carries content: run the
            # SCOPED arrangement on just that plane. The disc face goes in
            # first so the new regions count as covered; the rebuild then
            # splits every intersection (circle over circle next to a solid).
            from core.history import RebuildPlaneFacesCommand
            extra = [AddFaceCommand(list(pts)),
                     TagCurveCommand(list(pts), closed=True),
                     RebuildPlaneFacesCommand(*plane)]
        else:
            extra = [AddFaceCommand(list(pts)),
                     TagCurveCommand(list(pts), closed=True)]
        cmd = build_add_edges(
            viewport.scene, segments, detect_faces=False, extra=extra)
        viewport.history.execute(cmd)
        self._reset()
        viewport.update()


    def on_key(self, viewport, key: int, modifiers) -> bool:
        return self.plane_lock_key(viewport, key)

    def _reset(self) -> None:
        self.start_point = None
        self.work_plane = None
        self.hover_plane = None
        self.wireframe_color = None
        self.clear_plane_lock()


class CircleTool(_RadialTool):
    name = "Circle"
    shortcut = "C"
    description = "Draw a circle from its centre and radius."
    sides = 24


class PolygonTool(_RadialTool):
    name = "Polygon"
    shortcut = None  # Polygon has no default; G = Make Component
    description = (
        "Draw a regular polygon from its centre and radius; type a "
        "number followed by «s» to change the sides.")
    sides = 6
