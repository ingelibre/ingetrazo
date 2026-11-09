# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fillet tool: round the edges of a solid (Rafael's «herramienta de
redondeo», review of 2026-09-10, C3).

Click an edge (or use the selected edges), move the cursor away from it
to set the radius — the rounded strip forms live — and click again; or
type the radius and Enter at any moment. «Ns» sets the segments of the
arc. The same tool bevels: tapping Ctrl walks how the size is read
(radius, distance on the faces, width or depth of the new face), «0.3p»
shapes the profile (0.5 round, 0.25 straight, toward 1 square, toward 0
a cove) and one segment is a flat chamfer. It bevels the corners
(vertices) instead of the edges too, see :mod:`core.vertex_bevel`. A
panel in the corner of the view holds all of it, box corners included
(round, or a flat cut), and follows the keys. Edges that meet are handled
as a chain (a slab's rim) or a corner (a box), see :mod:`core.fillet`;
what cannot be rounded says why in the status bar and leaves the model
untouched.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.fillet import CIRCULAR, apply_fillet, plan_fillet
from core.units import fmt_len_fine
from core.i18n import tr
from core.mesh import Edge, Face
from core.vertex_bevel import plan_vertex_bevel
from tools.base import Tool, ToolContext


class FilletTool(Tool):
    #: "3D" in the name on purpose: this rounds the edges of a SOLID.
    #: The 2-D fillet of a corner lives in the Arc tool (tangent-tangent),
    #: and the bare word sent people here for it (issue #49, @pacaeiro).
    name = "Fillet 3D"
    icon = "fillet"
    #: Shift+F, not F: plain F is Offset, and the tool that comes second
    #: keeps Shift+key (as Shift+O, Shift+H and Shift+P do).
    shortcut = "Shift+F"
    description = ("Round or bevel the edges of a solid; Ctrl changes the "
                   "measure, «0.3p» the profile.")
    uses_snap = False
    vcb_label = "Radius"
    wireframe_color = (0.13, 0.17, 0.23, 1.0)
    wireframe_depth_tested = True

    #: Last radius used — the next fillet starts from it (metres).
    radius: float = 0.10
    #: Arc segments of the strip.
    segments: int = 8
    #: Shape of the section — 0.5 is the circular arc (see core.fillet).
    profile: float = CIRCULAR
    #: How the size is read; Ctrl walks them in this order.
    measure: str = "radius"
    _MEASURES = (("radius", "Radius"), ("offset", "Distance"),
                 ("width", "Width"), ("depth", "Depth"))
    #: How a box corner closes: "round" (patch) or "cut" (flat).
    corners: str = "round"
    #: A drawn outline instead of the superellipse (core.bevel_profiles):
    #: a preset's name, the editor's control points (a tuple), or None.
    shape = None
    _SHAPES = (("steps", "Steps"), ("supports", "Round with supports"),
               ("cornice", "Cornice"), ("crown", "Crown moulding"))
    #: What is bevelled: "edges", or "vertices" (the corners alone, the
    #: size then running along their edges).
    affect: str = "edges"

    def __init__(self) -> None:
        self.edges: list = []
        self.sizing: bool = False          # the cursor sets the radius
        self.hover_edge = None
        self.hover_vertex = None
        self.hover_point: QVector3D | None = None
        self._plan = None
        self._plan_key = None
        self._message: str | None = None
        self._viewport = None

    @staticmethod
    def _corners_mode() -> bool:
        return FilletTool.affect == "vertices"

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._viewport = viewport
        self._reset()
        scene = getattr(viewport, "scene", None)
        sel = getattr(scene, "selection", None) or ()
        mesh = getattr(scene, "mesh", None)
        picked = [e for e in sel if isinstance(e, Edge)
                  and mesh is not None and e in getattr(e.v0, "edges", ())]
        if self._corners_mode():
            picked = self._corners_of(sel, mesh)
        if picked and self._corners_mode():
            self.edges = picked
            viewport.flash_status(tr(
                "{n} corner(s) selected — type the size, or click and move "
                "the cursor to set it.", n=len(picked)), 5000)
        elif picked:
            self.edges = picked
            viewport.flash_status(tr(
                "{n} edge(s) selected — type the size, or click and move "
                "the cursor to set it.", n=len(picked)), 5000)
        else:
            viewport.flash_status(tr(
                "Click an edge to round or bevel it; type the size and Enter."), 4000)
        self._replan()
        self._show_panel(viewport)

    def on_deactivate(self, viewport) -> None:
        self._reset()
        panel = getattr(viewport, "_bevel_panel", None)
        if panel is not None:
            panel.hide()
        set_hover = getattr(viewport, "set_hover", None)
        if set_hover is not None:
            set_hover(None)

    def _reset(self) -> None:
        self.edges = []
        self.sizing = False
        self.hover_edge = None
        self.hover_vertex = None
        self.hover_point = None
        self._plan = None
        self._plan_key = None
        self._message = None

    @staticmethod
    def _corners_of(items, mesh) -> list:
        """The vertices of the selected edges and faces, once each."""
        out: dict[int, object] = {}
        for it in items:
            if isinstance(it, Edge):
                if mesh is None or it not in getattr(it.v0, "edges", ()):
                    continue
                vs = (it.v0, it.v1)
            elif isinstance(it, Face):
                vs = it.loop
            else:
                continue
            for v in vs:
                out.setdefault(id(v), v)
        return list(out.values())

    @staticmethod
    def _nearest_end(edge, p):
        """The end of ``edge`` nearer the cursor ``p``."""
        if p is None:
            return edge.v0
        return min((edge.v0, edge.v1),
                   key=lambda v: (v.position - p).lengthSquared())

    # ---- Spatial input --------------------------------------------------------
    @property
    def start_point(self):
        """Esc cascade hook: an in-progress rounding to cancel."""
        if not self.edges:
            return None
        first = self.edges[0]
        return first.a if isinstance(first, Edge) else first.position

    def _target_edges(self, viewport, cursor=None):
        """The edges a click acts on: the hovered edge, joined by the
        selection when the click lands on a selected edge. Bevelling
        corners, the hovered edge's nearer end — or the selection's
        corners."""
        edge = getattr(viewport, "_hover_edge", None)
        if edge is None or not isinstance(edge, Edge):
            return []
        sel = getattr(getattr(viewport, "scene", None), "selection", None) or ()
        if self._corners_mode():
            if edge in sel:
                mesh = getattr(getattr(viewport, "scene", None), "mesh", None)
                return self._corners_of(sel, mesh)
            return [self._nearest_end(edge, cursor)]
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
            self.edges = self._target_edges(vp, ctx.world)
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
                self._sync_panel()
            self._replan()
            vp.update()
            return
        if not self.edges:
            edge = getattr(vp, "_hover_edge", None)
            self.hover_edge = edge if isinstance(edge, Edge) else None
            self.hover_vertex = (self._nearest_end(self.hover_edge, ctx.world)
                                 if self.hover_edge is not None else None)
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
        if self._corners_mode():
            dists = [(v.position - p).length() for v in self.edges
                     if not isinstance(v, Edge)]
            best = min(dists) if dists else None
            return best if best is not None and best >= 1e-4 else None
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

    # ---- Keyboard -------------------------------------------------------------
    def on_key(self, viewport, key: int, modifiers) -> bool:
        # Ctrl walks the measure on the RELEASE of a Ctrl pressed alone, as
        # the Tape's mode does: on the press, Ctrl+Z would switch it too.
        if key == Qt.Key_Control:
            return True
        return False

    # ---- What is bevelled -------------------------------------------------------
    def set_affect(self, viewport, affect: str) -> None:
        """Edges or vertices. Picked edges carry over as their corners;
        picked corners do not make edges, so they are let go."""
        if affect not in ("edges", "vertices") or affect == FilletTool.affect:
            return
        FilletTool.affect = affect
        mesh = getattr(getattr(viewport, "scene", None), "mesh", None)
        if affect == "vertices":
            FilletTool.shape = None      # outlines are drawn along edges
        if affect == "vertices" and self.edges:
            self.edges = self._corners_of(self.edges, mesh)
        elif affect == "edges":
            self.edges = []
            self.sizing = False
        self.hover_vertex = None
        viewport.flash_status(tr("Affect: {a}", a=tr(
            "Vertices" if affect == "vertices" else "Edges")))
        self._replan()
        self._refresh_readouts(viewport)
        viewport.update()

    def _refresh_readouts(self, viewport) -> None:
        """The status clause and the VCB caption name the mode: redraw them
        now, not on the next live value (with nothing picked there is
        none)."""
        hint = getattr(viewport, "refresh_status_hint", None)
        if hint is not None:
            hint()
        window = getattr(viewport, "window", None)
        vcb = getattr(window(), "_refresh_vcb", None) if callable(window) else None
        if vcb is not None:
            vcb()
        self._sync_panel()

    def on_key_release(self, viewport, key: int) -> bool:
        if key != Qt.Key_Control:
            return False
        tapped = getattr(viewport, "ctrl_tapped", None)
        if callable(tapped) and not tapped():
            return False                 # Ctrl was part of a shortcut
        if self._corners_mode():
            return True                  # corners: the size is a distance
        names = [m for m, _lbl in self._MEASURES]
        self.set_measure(viewport, names[(names.index(FilletTool.measure) + 1)
                                         % len(names)])
        return True

    def set_measure(self, viewport, measure: str) -> None:
        if measure not in dict(self._MEASURES):
            return
        FilletTool.measure = measure
        viewport.flash_status(tr("Measure: {m}", m=tr(self._measure_label())))
        self._replan()
        self._refresh_readouts(viewport)
        viewport.update()

    def set_size(self, viewport, value: float) -> None:
        """The panel's Amount: the size, without rounding yet."""
        FilletTool.radius = float(value)
        self._replan()
        self._sync_panel()
        viewport.update()

    def set_shape(self, viewport, shape) -> None:
        """A drawn outline (steps, mouldings…), or None for the
        superellipse."""
        from core import bevel_profiles
        if isinstance(shape, (list, tuple)):
            if not bevel_profiles.valid(shape):
                return
            shape = tuple((float(x), float(y), bool(sm)) for x, y, sm in shape)
        elif shape is not None and shape not in dict(self._SHAPES):
            return
        if shape is not None and self._corners_mode():
            viewport.flash_status(tr("Drawn profiles bevel edges only."))
            self._sync_panel()
            return
        FilletTool.shape = shape
        if isinstance(shape, str):
            viewport.flash_status(tr("Profile {p}", p=tr(self._shape_label())))
        self._replan()
        self._sync_panel()
        viewport.update()

    def set_corners(self, viewport, corners: str) -> None:
        if corners not in ("round", "cut"):
            return
        FilletTool.corners = corners
        viewport.flash_status(tr("Corners: {c}", c=tr(
            "Fill (triangle / cap)" if corners == "round" else "No fill (notch)")))
        self._replan()
        self._sync_panel()
        viewport.update()

    def apply_from_panel(self, viewport) -> None:
        """The panel's Apply: round what is picked, as Enter would."""
        if not self._current_edges():
            viewport.flash_status(tr("Click an edge to round or bevel it; "
                                     "type the size and Enter."), 4000)
            return
        self._commit(viewport)

    # ---- Panel ----------------------------------------------------------------
    def _show_panel(self, viewport) -> None:
        from PySide6.QtWidgets import QWidget
        if not isinstance(viewport, QWidget):
            return
        panel = getattr(viewport, "_bevel_panel", None)
        if panel is None:
            from views.bevel_panel import BevelPanel
            panel = viewport._bevel_panel = BevelPanel(viewport, self)
        panel.show_for(self)

    def _sync_panel(self) -> None:
        panel = getattr(self._viewport, "_bevel_panel", None)
        if panel is not None and not panel.isHidden() and panel.tool is self:
            panel.sync()

    def _measure_label(self) -> str:
        """English source label of the current measure."""
        return dict(self._MEASURES).get(FilletTool.measure, "Radius")

    def vcb_caption(self) -> str:
        return "Distance" if self._corners_mode() else self._measure_label()

    def status_clause(self) -> str:
        if self._corners_mode():
            return tr("Vertices: size along the edges")
        return tr("Ctrl = measure ({m})", m=tr(self._measure_label()))

    def on_value(self, viewport, value) -> bool:
        if isinstance(value, tuple) or value <= 0:
            return False
        FilletTool.radius = float(value)
        if self.edges:
            self._commit(viewport)
        else:
            viewport.flash_status(tr("{m} {r} — click an edge.",
                                     m=tr(self._measure_label()),
                                     r=fmt_len_fine(value)), 3000)
            self._replan()
            self._sync_panel()
            viewport.update()
        return True

    def on_segments_value(self, viewport, n: int) -> bool:
        n = int(n)
        if n < 1:
            return False
        FilletTool.segments = n
        viewport.flash_status(tr("{n} segments", n=n))
        self._replan()
        self._sync_panel()
        viewport.update()
        return True

    def on_profile_value(self, viewport, p: float) -> bool:
        """«0.3p»: the profile of the section."""
        if not 0.0 < p < 1.0:
            viewport.flash_status(tr("The profile must be between 0 and 1."))
            return False
        FilletTool.profile = float(p)
        FilletTool.shape = None          # a number is the superellipse
        viewport.flash_status(tr("Profile {p}", p=f"{p:.2f}"))
        self._replan()
        self._sync_panel()
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
        """What would be bevelled now: the picked edges (or corners), else
        the one under the cursor."""
        if self.edges:
            return self.edges
        if self._corners_mode():
            return [self.hover_vertex] if self.hover_vertex is not None else []
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
               FilletTool.segments, FilletTool.profile, FilletTool.measure,
               FilletTool.corners, FilletTool.affect, FilletTool.shape,
               getattr(mesh, "_mut_serial", 0))
        if key == self._plan_key:
            return
        self._plan_key = key
        if self._corners_mode():
            plan = plan_vertex_bevel(mesh, edges, FilletTool.radius,
                                     FilletTool.segments, FilletTool.profile)
        else:
            plan = plan_fillet(mesh, edges, FilletTool.radius,
                               FilletTool.segments, FilletTool.profile,
                               FilletTool.measure, FilletTool.corners,
                               FilletTool.shape)
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
        if self._corners_mode():
            said = tr("Bevelled {n} corner(s), distance {r}.", n=n,
                      r=fmt_len_fine(r))
        elif self._is_plain_fillet():
            said = tr("Rounded {n} edge(s), radius {r}.", n=n,
                      r=fmt_len_fine(r))
        else:
            said = tr("Bevelled {n} edge(s), {m} {r}.", n=n,
                      m=tr(self._measure_label()), r=fmt_len_fine(r))
        viewport.flash_status(said, 3000)
        self._sync_panel()
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
        mid = (e.a + e.b) * 0.5 if isinstance(e, Edge) else QVector3D(e.position)
        if self._message:
            return (self._message, mid)
        size = fmt_len_fine(FilletTool.radius)
        if self._corners_mode():
            head = tr("Distance") + " " + size
        elif FilletTool.measure == "radius":
            head = "R " + size
        else:
            head = tr(self._measure_label()) + " " + size
        extra = tr("{n} segments", n=FilletTool.segments)
        if FilletTool.shape is not None and not self._corners_mode():
            extra += ", " + tr(self._shape_label())
        elif abs(FilletTool.profile - CIRCULAR) > 1e-9:
            extra += ", " + tr("profile {p}", p=f"{FilletTool.profile:.2f}")
        return (head + "  (" + extra + ")", mid)

    def _shape_label(self) -> str:
        """English source label of the drawn outline in use."""
        if isinstance(FilletTool.shape, tuple):
            return "Custom (draw)"
        return dict(self._SHAPES).get(FilletTool.shape, "Curve (value 0–1)")

    def _is_plain_fillet(self) -> bool:
        return (FilletTool.measure == "radius" and FilletTool.shape is None
                and abs(FilletTool.profile - CIRCULAR) < 1e-9)
