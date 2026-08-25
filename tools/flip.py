# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Flip tool — SketchUp 2023+'s Flip (mirror).

Official flow (help.sketchup.com "Flipping, Mirroring, Rotating and
Arrays"): with a selection, three semi-transparent planes appear over it —
red, green and blue, one per axis. Hovering highlights a plane; ONE CLICK
flips the selection about it. The arrow keys pick a plane (Right = red,
Left = green, Up = blue); tapping Ctrl toggles COPY mode, which leaves the
original and creates the flipped duplicate.

Deferred (documented): dragging a plane to reposition it, Alt
parent-context axes, and the magenta custom plane from hovering a face.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen, QPolygonF, QVector3D
from PySide6.QtCore import QPointF

from core.group import Group, copy_group, transformed_attrs
from core.history import (
    AddEdgeCommand,
    AddFaceCommand,
    CompoundCommand,
    FlipGroupsCommand,
    FlipVerticesCommand,
    InsertGroupCommand,
    mirror_matrix,
)
from core.i18n import tr
from core.mesh import Edge, Face, Mesh
from tools.base import Tool, ToolContext

_AXES = {"x": QVector3D(1, 0, 0), "y": QVector3D(0, 1, 0),
         "z": QVector3D(0, 0, 1)}
_PLANE_RGBA = {"x": (216, 56, 68), "y": (40, 158, 90), "z": (52, 102, 198)}


class FlipTool(Tool):
    name = "Flip"
    uses_snap = False

    def __init__(self) -> None:
        self.hover_point: QVector3D | None = None
        self._hover_axis: str | None = None
        self._lock_axis: str | None = None      # arrow-key pick
        self._copy = False

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._hover_axis = None
        self._lock_axis = None
        self._copy = False
        if not self._targets(viewport)[0]:
            viewport.flash_status(
                tr("Select the geometry to flip first"))

    def on_deactivate(self, viewport) -> None:
        self._hover_axis = None

    # ---- Input --------------------------------------------------------------
    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Control:
            self._copy = not self._copy
            viewport.flash_status(tr("Flip a copy: on") if self._copy
                                  else tr("Flip a copy: off"))
            viewport.update()
            return True
        picks = {Qt.Key_Right: "x", Qt.Key_Left: "y", Qt.Key_Up: "z"}
        axis = picks.get(key)
        if axis is None:
            return False
        self._lock_axis = None if self._lock_axis == axis else axis
        viewport.update()
        return True

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        self._hover_axis = self._plane_under_cursor(
            ctx.viewport, ctx.screen.x(), ctx.screen.y())
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        axis = self._lock_axis or self._hover_axis
        if axis is None:
            return
        ok, groups, positions, faces, edges, centre = \
            self._targets(viewport, full=True)
        if not ok:
            viewport.flash_status(tr("Select the geometry to flip first"))
            return
        n = _AXES[axis]
        cmds: list = []
        if self._copy:
            m = mirror_matrix(centre, n)
            for g in groups:
                copy = copy_group(g)
                cmds.append(InsertGroupCommand(copy))
                cmds.append(FlipGroupsCommand([copy], centre, n))
            id_map: dict[int, int] = {}
            for f in faces:
                # Mirrored loops are re-reversed so the copy faces OUT.
                loop = [m.map(QVector3D(v)) for v in f.vertices][::-1]
                holes = [[m.map(QVector3D(v)) for v in h][::-1]
                         for h in f.holes] or None
                cmds.append(AddFaceCommand(
                    loop, holes=holes, auto=False,
                    attrs=transformed_attrs(f.attrs, m)))
            for e in edges:
                curve = getattr(e, "curve", None)
                if curve is not None and curve not in id_map:
                    id_map[curve] = Mesh.next_curve_id()
                cmds.append(AddEdgeCommand(
                    m.map(QVector3D(e.a)), m.map(QVector3D(e.b)),
                    soft=getattr(e, "soft", False) or None,
                    curve=id_map.get(curve)))
        else:
            if groups:
                cmds.append(FlipGroupsCommand(groups, centre, n))
            if positions:
                cmds.append(FlipVerticesCommand(
                    positions, centre, n, faces=faces))
        if not cmds:
            return
        viewport.history.execute(
            cmds[0] if len(cmds) == 1 else CompoundCommand(cmds))
        self._copy = False           # the modifier arms ONE flip (SketchUp)
        viewport.update()

    def on_cancel(self, viewport) -> None:
        self._lock_axis = None
        viewport.update()

    # ---- Overlay ------------------------------------------------------------
    def draw_overlay(self, viewport, painter) -> None:
        """The three semi-transparent axis planes over the selection; the
        hovered / arrow-locked one highlights (SketchUp)."""
        ok, _g, _p, _f, _e, centre = self._targets(viewport, full=True)
        if not ok:
            return
        lo, hi = self._bounds(viewport)
        if lo is None:
            return
        half = (hi - lo) * 0.5
        margin = 1.15
        for axis, n in _AXES.items():
            quad = self._plane_quad(axis, centre, half, margin)
            pts = [viewport._world_to_pixel(q) for q in quad]
            if any(p is None for p in pts):
                continue
            poly = QPolygonF([QPointF(*p) for p in pts])
            r, g, b = _PLANE_RGBA[axis]
            active = axis == (self._lock_axis or self._hover_axis)
            painter.setPen(QPen(QColor(r, g, b), 2.2 if active else 1.2))
            painter.setBrush(QColor(r, g, b, 90 if active else 36))
            painter.drawPolygon(poly)
        painter.setBrush(Qt.NoBrush)

    # ---- Internals ----------------------------------------------------------
    def _bounds(self, viewport):
        sel = viewport.scene.selection
        pts: list[QVector3D] = []
        for ent in sel:
            if isinstance(ent, Group):
                xf = getattr(ent, "xform", None)
                for v in ent.mesh.vertices:
                    p = v.position
                    pts.append(xf.map(p) if xf is not None else QVector3D(p))
            elif isinstance(ent, Face):
                pts.extend(QVector3D(v) for v in ent.vertices)
            elif isinstance(ent, Edge):
                pts.append(QVector3D(ent.a))
                pts.append(QVector3D(ent.b))
        if not pts:
            return None, None
        lo = QVector3D(min(p.x() for p in pts), min(p.y() for p in pts),
                       min(p.z() for p in pts))
        hi = QVector3D(max(p.x() for p in pts), max(p.y() for p in pts),
                       max(p.z() for p in pts))
        return lo, hi

    def _targets(self, viewport, full: bool = False):
        sel = viewport.scene.selection
        groups = [g for g in sel if isinstance(g, Group)]
        faces = [f for f in sel if isinstance(f, Face)]
        edges = [e for e in sel if isinstance(e, Edge)]
        ok = bool(groups or faces or edges)
        if not full:
            return ok, groups
        positions: list[QVector3D] = []
        seen = set()
        for f in faces:
            for v in f.vertices:
                k = (round(v.x(), 6), round(v.y(), 6), round(v.z(), 6))
                if k not in seen:
                    seen.add(k)
                    positions.append(QVector3D(v))
        for e in edges:
            for v in (e.a, e.b):
                k = (round(v.x(), 6), round(v.y(), 6), round(v.z(), 6))
                if k not in seen:
                    seen.add(k)
                    positions.append(QVector3D(v))
        lo, hi = self._bounds(viewport)
        centre = ((lo + hi) * 0.5 if lo is not None
                  else QVector3D(0, 0, 0))
        return ok, groups, positions, faces, edges, centre

    def _plane_quad(self, axis: str, centre: QVector3D, half: QVector3D,
                    margin: float):
        hx = max(half.x(), 0.3) * margin
        hy = max(half.y(), 0.3) * margin
        hz = max(half.z(), 0.3) * margin
        c = centre
        if axis == "x":      # YZ plane
            return [QVector3D(c.x(), c.y() - hy, c.z() - hz),
                    QVector3D(c.x(), c.y() + hy, c.z() - hz),
                    QVector3D(c.x(), c.y() + hy, c.z() + hz),
                    QVector3D(c.x(), c.y() - hy, c.z() + hz)]
        if axis == "y":      # XZ plane
            return [QVector3D(c.x() - hx, c.y(), c.z() - hz),
                    QVector3D(c.x() + hx, c.y(), c.z() - hz),
                    QVector3D(c.x() + hx, c.y(), c.z() + hz),
                    QVector3D(c.x() - hx, c.y(), c.z() + hz)]
        return [QVector3D(c.x() - hx, c.y() - hy, c.z()),
                QVector3D(c.x() + hx, c.y() - hy, c.z()),
                QVector3D(c.x() + hx, c.y() + hy, c.z()),
                QVector3D(c.x() - hx, c.y() + hy, c.z())]

    def _plane_under_cursor(self, viewport, sx: float, sy: float):
        """Which of the three planes the cursor is inside (projected); ties
        break toward the plane whose centre is nearest on screen."""
        lo, hi = self._bounds(viewport)
        if lo is None:
            return None
        centre = (lo + hi) * 0.5
        half = (hi - lo) * 0.5
        w2p = getattr(viewport, "_world_to_pixel", None)
        if w2p is None:
            return None
        best = None
        best_d = float("inf")
        for axis in _AXES:
            quad = self._plane_quad(axis, centre, half, 1.15)
            pts = [w2p(q) for q in quad]
            if any(p is None for p in pts):
                continue
            poly = QPolygonF([QPointF(*p) for p in pts])
            if not poly.containsPoint(QPointF(sx, sy), Qt.OddEvenFill):
                continue
            cpx = w2p(centre)
            mid = (sum(p[0] for p in pts) / 4.0, sum(p[1] for p in pts) / 4.0)
            d = (mid[0] - sx) ** 2 + (mid[1] - sy) ** 2
            if cpx is not None and d < best_d:
                best_d = d
                best = axis
        return best
