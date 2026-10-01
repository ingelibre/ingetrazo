# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fillet tool: round the edges of a solid (Rafael's «herramienta de
redondeo», review of 2026-09-10, C3).

Click an edge (or use the selected edges), move the cursor away from it
to set the radius — the rounded strip forms live — and click again; or
type the radius and Enter at any moment. «Ns» sets the segments of the
arc. Edges that meet are handled as a chain (a slab's rim) or a corner (a
box), see :mod:`core.fillet`; what cannot be rounded says why in the
status bar and leaves the model untouched.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.fillet import apply_fillet, plan_fillet
from core.units import fmt_len_fine
from core.i18n import tr
from core.mesh import Edge
from tools.base import Tool, ToolContext


class FilletTool(Tool):
    #: "3D" in the name on purpose: this rounds the edges of a SOLID.
    #: The 2-D fillet of a corner lives in the Arc tool (tangent-tangent),
    #: and the bare word sent people here for it (issue #49, @pacaeiro).
    name = "Fillet 3D"
    icon = "fillet"
    shortcut = None
    description = "Round the edges of a solid to the radius you set."
    uses_snap = False
    vcb_label = "Radius"
    wireframe_color = (0.13, 0.17, 0.23, 1.0)
    wireframe_depth_tested = True

    #: Last radius used — the next fillet starts from it (metres).
    radius: float = 0.10
    #: Arc segments of the strip.
    segments: int = 8

    def __init__(self) -> None:
        self.edges: list = []
        self.sizing: bool = False          # the cursor sets the radius
        self.hover_edge = None
        self.hover_point: QVector3D | None = None
        self._plan = None
        self._plan_key = None
        self._message: str | None = None
        self._viewport = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._viewport = viewport
        self._reset()
        scene = getattr(viewport, "scene", None)
        sel = getattr(scene, "selection", None) or ()
        mesh = getattr(scene, "mesh", None)
        picked = [e for e in sel if isinstance(e, Edge)
                  and mesh is not None and e in getattr(e.v0, "edges", ())]
        if picked:
            self.edges = picked
            viewport.flash_status(tr(
                "{n} edge(s) selected — type the radius, or click and move "
                "the cursor to set it.", n=len(picked)), 5000)
        else:
            viewport.flash_status(tr(
                "Click an edge to round it; type the radius and Enter."), 4000)
        self._replan()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        set_hover = getattr(viewport, "set_hover", None)
        if set_hover is not None:
            set_hover(None)

    def _reset(self) -> None:
        self.edges = []
        self.sizing = False
        self.hover_edge = None
        self.hover_point = None
        self._plan = None
        self._plan_key = None
        self._message = None

    # ---- Spatial input --------------------------------------------------------
    @property
    def start_point(self):
        """Esc cascade hook: an in-progress rounding to cancel."""
        return self.edges[0].a if self.edges else None

    def _target_edges(self, viewport):
        """The edges a click acts on: the hovered edge, joined by the
        selection when the click lands on a selected edge."""
        edge = getattr(viewport, "_hover_edge", None)
        if edge is None or not isinstance(edge, Edge):
            return []
        sel = getattr(getattr(viewport, "scene", None), "selection", None) or ()
        if edge in sel:
            picked = [e for e in sel if isinstance(e, Edge)]
            if picked:
                return picked
        return [edge]

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        self._viewport = vp
        if self.sizing:
            self._commit(vp)
            return
        if not self.edges:
            self.edges = self._target_edges(vp)
            if not self.edges:
                return
        self.sizing = True
        self.hover_point = ctx.world
        self._replan()
        vp.update()

    def on_hover(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        self._viewport = vp
        self.hover_point = ctx.world
        if self.sizing:
            r = self._radius_from(ctx.world)
            if r is not None:
                FilletTool.radius = r
            self._replan()
            vp.update()
            return
        if not self.edges:
            edge = getattr(vp, "_hover_edge", None)
            self.hover_edge = edge if isinstance(edge, Edge) else None
            set_hover = getattr(vp, "set_hover", None)
            if set_hover is not None:
                set_hover(self.hover_edge)
            self._replan()
        vp.update()

    def _radius_from(self, p: QVector3D) -> float | None:
        """Perpendicular distance from the cursor to the nearest chosen
        edge's line — the radius while sizing."""
        if p is None or not self.edges:
            return None
        best = None
        for e in self.edges:
            a, b = e.a, e.b
            d = b - a
            ln = d.length()
            if ln < 1e-9:
                continue
            d /= ln
            off = (p - a) - d * QVector3D.dotProduct(p - a, d)
            r = off.length()
            if best is None or r < best:
                best = r
        if best is None or best < 1e-4:
            return None
        return best

    def on_value(self, viewport, value) -> bool:
        if isinstance(value, tuple) or value <= 0:
            return False
        FilletTool.radius = float(value)
        if self.edges:
            self._commit(viewport)
        else:
            viewport.flash_status(tr("Radius {r} — click an edge.",
                                     r=fmt_len_fine(value)), 3000)
            self._replan()
            viewport.update()
        return True

    def on_segments_value(self, viewport, n: int) -> bool:
        n = int(n)
        if n < 1:
            return False
        FilletTool.segments = n
        viewport.flash_status(tr("{n} segments", n=n))
        self._replan()
        viewport.update()
        return True

    def on_cancel(self, viewport) -> None:
        self._reset()
        set_hover = getattr(viewport, "set_hover", None)
        if set_hover is not None:
            set_hover(None)
        viewport.update()

    # ---- Planning / commit ----------------------------------------------------
    def _current_edges(self) -> list:
        if self.edges:
            return self.edges
        return [self.hover_edge] if self.hover_edge is not None else []

    def _replan(self) -> None:
        edges = self._current_edges()
        mesh = getattr(getattr(self._viewport, "scene", None), "mesh", None)
        if not edges or mesh is None:
            self._plan = None
            self._plan_key = None
            self._message = None
            return
        key = (tuple(id(e) for e in edges), round(FilletTool.radius, 6),
               FilletTool.segments, getattr(mesh, "_mut_serial", 0))
        if key == self._plan_key:
            return
        self._plan_key = key
        plan = plan_fillet(mesh, edges, FilletTool.radius, FilletTool.segments)
        if isinstance(plan, str):
            self._plan = None
            self._message = plan
        else:
            self._plan = plan
            self._message = None

    def _commit(self, viewport) -> None:
        self._replan()
        plan = self._plan
        if plan is None:
            viewport.flash_status(self._message or tr("Nothing to round."), 4000)
            return
        from core.history import SnapshotMutation
        mesh = viewport.scene.mesh
        n = len(self.edges)
        r = FilletTool.radius
        cmd = SnapshotMutation(lambda scene: apply_fillet(scene.mesh, plan),
                               mesh=mesh)
        viewport.history.execute(cmd)
        viewport.scene.clear_selection()
        self._reset()
        set_hover = getattr(viewport, "set_hover", None)
        if set_hover is not None:
            set_hover(None)
        viewport.flash_status(tr("Rounded {n} edge(s), radius {r}.",
                                 n=n, r=fmt_len_fine(r)), 3000)
        viewport.update()

    # ---- Preview --------------------------------------------------------------
    def preview_faces(self):
        if self._plan is None:
            return []
        from core.geometry import Face as PreviewFace
        return [PreviewFace(list(loop)) for loop in self._plan.new_faces]

    def rubber_band_lines(self):
        if self._plan is None:
            return []
        lines = []
        for pts in self._plan.curves:
            lines.extend((pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        return lines

    def value_label(self):
        edges = self._current_edges()
        if not edges:
            return None
        e = edges[0]
        mid = (e.a + e.b) * 0.5
        if self._message:
            return (self._message, mid)
        return ("R " + fmt_len_fine(FilletTool.radius) + "  ("
                + tr("{n} segments", n=FilletTool.segments) + ")", mid)
