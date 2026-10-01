# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Arc tool: two endpoints (the chord), then a bulge.

The classic 2-point arc:
1. click the start point,
2. click the end point — the chord,
3. move to bulge the arc out from the chord, click to commit.

The arc is committed as a polyline of short edges (it auto-faces if it closes a
region with existing geometry). The bulge can be typed in the VCB.

Rounding a corner (Rafael's review of 2026-09-10, C2): a
start point ON an edge makes the preview an arc **tangent to that edge**
(cyan, «Tangent to edge»); on the adjacent edge, at the same distance from
the shared corner, the arc turns **magenta** — tangent to both edges, the
fillet. A double-click there draws it and trims the corner; a double-click
near another two-edge corner repeats the last distance.
"""
from __future__ import annotations

import math

from core.i18n import tr

from PySide6.QtGui import QVector3D

from collections import namedtuple

from PySide6.QtCore import Qt

from core.edits import build_add_edges
from core.history import (DeleteEdgesCommand, RebuildPlanarFacesCommand,
                          TagCurveCommand)
from core.axes import plane_axes  # drawing axes (#44)
from tools.base import AxisMagnet, PlaneLock, Tool, ToolContext
from core.units import fmt_len

_SEGMENTS = 16  # polyline segments approximating the arc

#: Magenta of the arc that is tangent to BOTH edges of a corner (the classic
#: convention turns the turquoise tangent inference magenta «at the
#: point where it fillets a corner»).
COLOR_FILLET = (0.85, 0.30, 0.80)

_Seg = namedtuple("_Seg", "a b")


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


def _arc_3pts_2d(s, m, e, segments):
    """2D points of the circular arc from ``s`` to ``e`` passing through ``m``
    (the circumcircle of the three), sampled into ``segments`` spans. Falls back
    to the straight chord when the three points are collinear."""
    center = _circumcenter2(s, m, e)
    if center is None:
        return [s, e]
    cx, cy = center
    r = math.hypot(s[0] - cx, s[1] - cy)
    a0 = math.atan2(s[1] - cy, s[0] - cx)
    a1 = math.atan2(e[1] - cy, e[0] - cx)
    am = math.atan2(m[1] - cy, m[0] - cx)
    d = _wrap(a1 - a0)
    da = _wrap(am - a0)
    if d >= 0 and not (0.0 <= da <= d):
        d -= 2.0 * math.pi
    elif d < 0 and not (d <= da <= 0.0):
        d += 2.0 * math.pi
    return [(cx + r * math.cos(a0 + d * (k / segments)),
             cy + r * math.sin(a0 + d * (k / segments)))
            for k in range(segments + 1)]




def commit_arc(viewport, pts: list[QVector3D], close_to=None, trim=None):
    """Commit an arc polyline with the shared curve pipeline: planar
    arrangement on flat drawings, scoped per-plane arrangement when the
    drawing plane already carries content in a 3D scene, naive otherwise.
    Used by every arc variant. With ``close_to`` (a centre point) the two
    radius edges close the wedge — the classic Pie. ``trim`` is a list of
    ``(a, b)`` position pairs: edges to erase once the arc is in — the two
    corner stubs a fillet leaves behind, which the classic tool «cleans out»
    after the face has been split, so the rounded face survives and the corner
    sliver goes with its edges. Returns the executed command."""
    segments = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    if close_to is not None:
        segments = ([(close_to, pts[0])] + segments
                    + [(pts[-1], close_to)])
    after = []
    if trim:
        after.append(DeleteEdgesCommand([_Seg(QVector3D(a), QVector3D(b))
                                         for a, b in trim]))
    from tools.circle import busy_plane, flat_drawing
    if flat_drawing(viewport.scene, pts):
        cmd = build_add_edges(
            viewport.scene, segments, detect_faces=False,
            extra=[TagCurveCommand(list(pts), closed=False),
                   RebuildPlanarFacesCommand()] + after)
    elif (plane := busy_plane(viewport.scene, pts)) is not None:
        from core.history import RebuildPlaneFacesCommand
        cmd = build_add_edges(
            viewport.scene, segments, detect_faces=True,
            extra=[TagCurveCommand(list(pts), closed=False),
                   RebuildPlaneFacesCommand(*plane)] + after)
    else:
        cmd = build_add_edges(viewport.scene, segments, detect_faces=True,
                              extra=[TagCurveCommand(list(pts), closed=False)]
                              + after)
    viewport.history.execute(cmd)
    return cmd


class ArcTool(AxisMagnet, PlaneLock, Tool):
    name = "Arc"
    shortcut = "A"
    description = "Draw an arc from its two ends, then pull out its bulge."
    vcb_label = "Bulge"

    #: Within this many screen pixels of the tangent bulge, the arc snaps
    #: to it ("Tangent at Vertex", cyan).
    TANGENT_PX = 8.0
    #: Within this many screen pixels of the point on the adjacent edge at
    #: the same distance from the corner, the end point snaps to it and the
    #: arc turns magenta (a fillet).
    FILLET_PX = 10.0
    #: A double-click this close (px) to a two-edge corner repeats the last
    #: rounding on it.
    CORNER_PX = 20.0
    #: Polyline segments of the next arc; the usual "Ns" in the VCB.
    segments: int = _SEGMENTS
    #: Distance corner→tangent points of the last fillet (shared by every
    #: arc tool instance): a double-click near another corner repeats it.
    last_fillet_d: float | None = None

    def magnet_on(self) -> bool:
        # The chord end is a direction from the start; the bulge is not
        # (it is measured off the chord's midpoint), so the magnet would
        # flatten a shallow arc near an axis.
        return self.end_point is None

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None
        self.end_point: QVector3D | None = None
        self.hover_point: QVector3D | None = None
        self.work_plane: tuple[QVector3D, QVector3D] | None = None
        # Tangent direction of the arc this one starts from (at its end
        # vertex), and the bulge that keeps the new arc tangent to it.
        self._tangent_dir: QVector3D | None = None
        self._snap_bulge: float | None = None
        # What the bulge snapped to: "tangent" (cyan), "fillet" (magenta),
        # "half" (a half circle) or None.
        self._bulge_kind: str | None = None
        # The edge the start point sits on (interior), as ``(edge, P1)``.
        self._start_edge = None
        # End-point phase: the equidistant point on an adjacent edge the
        # cursor is snapped to, as ``(V, P2, edge B)``.
        self._equidistant = None
        # After the end click: ``(V, P1, P2)`` when the end point was the
        # equidistant one — the corner this arc rounds; and the corner's
        # second edge, so a typed radius can be checked against it.
        self._fillet = None
        self._fillet_edge_b = None
        # The last committed arc and its parameters, so "Ns" typed right
        # after can rebuild it with another segment count.
        self._last_cmd = None
        self._last_params = None
        self._viewport = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()
        self._last_cmd = None
        self._last_params = None

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None
        self._last_cmd = None
        self._last_params = None

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        self.note_plane(ctx.viewport)
        self._viewport = ctx.viewport
        if self.start_point is None:
            self._last_cmd = None
            self._last_params = None
            self.start_point = ctx.world
            if self.work_plane is None:
                self.work_plane = self.locked_work_plane(ctx.world)
            self._start_edge = self._edge_under(ctx.viewport, ctx.world)
            return
        if self.end_point is None:
            end = self._equidistant[1] if self._equidistant else ctx.world
            if (end - self.start_point).length() < 1e-6:
                return
            self.end_point = end
            self.adopt_snapped_plane()   # the bulge is read on the arc's plane
            self._fillet = None
            self._fillet_edge_b = None
            if self._equidistant is not None:
                V, P2, B = self._equidistant
                self._fillet = (QVector3D(V), QVector3D(self.start_point),
                                QVector3D(P2))
                self._fillet_edge_b = B
            self._equidistant = None
            self._tangent_dir = self._tangent_at_start(ctx.viewport)
            if self._tangent_dir is None:
                self._tangent_dir = self._edge_tangent(end)
            return
        pts = self._points(ctx.world)
        if len(pts) >= 2:
            self._commit(ctx.viewport, pts, trim=self._corner_trim(ctx.modifiers))

    def on_double_click(self, ctx: ToolContext) -> None:
        """A double-click on the magenta point draws the fillet
        with its tangent bulge and trims the corner in one gesture; a
        double-click near another two-edge corner repeats the last
        distance. Anything else is a plain click."""
        self._viewport = ctx.viewport
        if (self.start_point is not None and self.end_point is not None
                and self._fillet is not None):
            h = self._tangent_bulge()
            if h is not None:
                self._snap_bulge = h
                self._bulge_kind = "fillet"
                pts = self._points(None, bulge=h)
                if len(pts) >= 2:
                    self._commit(ctx.viewport, pts,
                                 trim=self._corner_trim(ctx.modifiers))
                    return
        if (self.start_point is not None and self.end_point is None
                and ArcTool.last_fillet_d):
            corner = self._corner_near(ctx.viewport, ctx.screen, ctx.world)
            if corner is not None:
                self._reset()
                self._round_corner(ctx.viewport, corner, ArcTool.last_fillet_d,
                                   ctx.modifiers)
                return
        self.on_click(ctx)

    def on_hover(self, ctx: ToolContext) -> None:
        self.note_plane(ctx.viewport)
        self._viewport = ctx.viewport
        self.hover_point = ctx.world
        self._snap_bulge = None
        self._bulge_kind = None
        self._equidistant = None
        self.wireframe_color = self.lock_color()
        if self.start_point is not None and self.end_point is None:
            # End-point phase: from an edge, the preview is the arc tangent
            # to it (cyan); at the equidistant point of the adjacent edge
            # it turns magenta.
            if self._start_edge is not None:
                from core.snap import COLOR_TANGENT
                self.wireframe_color = (*COLOR_TANGENT, 1.0)
                self._equidistant = self._equidistant_near(
                    ctx.viewport, ctx.screen, ctx.world)
                if self._equidistant is not None:
                    self.hover_point = QVector3D(self._equidistant[1])
                    self.wireframe_color = (*COLOR_FILLET, 1.0)
        elif self.end_point is not None:
            self._snap_bulge_for(ctx)
        ctx.viewport.update()

    def _snap_bulge_for(self, ctx: ToolContext) -> None:
        """Bulge-phase inferences: tangent to the edge/arc the start sits on
        (cyan, magenta when that also makes it tangent to the corner's
        other edge), and the half circle."""
        u, v = self._axes()
        e2 = self._to2(self.end_point, u, v)
        length = math.hypot(*e2)
        if length < 1e-9:
            return
        perp = u * (-e2[1] / length) + v * (e2[0] / length)
        mid = (self.start_point + self.end_point) * 0.5
        scale = self.world_per_pixel(ctx.viewport, mid, perp)
        if scale is None:
            return
        tol = scale * self.TANGENT_PX
        b = self._bulge_for(ctx.world)
        if self._tangent_dir is not None:
            h_t = self._tangent_bulge()
            if h_t is not None and abs(b - h_t) <= tol:
                self._snap_bulge = h_t
                self._bulge_kind = "fillet" if self._fillet is not None else "tangent"
                from core.snap import COLOR_TANGENT
                self.wireframe_color = (*(COLOR_FILLET if self._fillet is not None
                                          else COLOR_TANGENT), 1.0)
                return
        half = length / 2.0
        if abs(abs(b) - half) <= tol:
            self._snap_bulge = math.copysign(half, b if b else 1.0)
            self._bulge_kind = "half"
            from core.snap import COLOR_MIDPOINT
            self.wireframe_color = (*COLOR_MIDPOINT, 1.0)

    # ---- Corner rounding (fillet inference) ----------------------------------
    @staticmethod
    def _edge_under(viewport, P: QVector3D):
        """``(edge, P)`` when ``P`` lies on the interior of an edge of the
        mesh being drawn on — the hovered edge first, then a search."""
        scene = getattr(viewport, "scene", None)
        mesh = getattr(scene, "mesh", None)
        if mesh is None:
            return None
        from core.topology import _point_on_seg_incl

        def interior(e) -> bool:
            if not _point_on_seg_incl(P, e.a, e.b, 1e-4):
                return False
            return ((P - e.a).length() > 1e-4 and (P - e.b).length() > 1e-4
                    and e.length() > 1e-6)
        hovered = getattr(viewport, "_hover_edge", None)
        v0 = getattr(hovered, "v0", None)
        if v0 is not None and hovered in getattr(v0, "edges", ()) and interior(hovered):
            return hovered, QVector3D(P)
        for e in mesh.edges:
            if interior(e):
                return e, QVector3D(P)
        return None

    def _edge_tangent(self, toward: QVector3D) -> QVector3D | None:
        """Direction the arc leaves the start point along its edge, on the
        side of ``toward`` (the cursor / the end point)."""
        if self._start_edge is None:
            return None
        edge, P1 = self._start_edge
        d = (edge.b - edge.a)
        if d.length() < 1e-9:
            return None
        d = d.normalized()
        if QVector3D.dotProduct(d, toward - P1) < 0.0:
            d = -d
        return d

    def _equidistant_near(self, viewport, screen, cursor):
        """``(V, P2, B)``: the point on an edge ``B`` adjacent to the start
        edge at the start point's distance from their shared corner ``V``,
        when the cursor is within ``FILLET_PX`` of it."""
        if self._start_edge is None:
            return None
        edge, P1 = self._start_edge
        best = None
        for V in (edge.v0, edge.v1):
            d = (P1 - V.position).length()
            if d < 1e-6:
                continue
            for B in V.edges:
                if B is edge:
                    continue
                W = B.other(V).position
                span = (W - V.position).length()
                if span < 1e-9 or d > span + 1e-6:
                    continue
                P2 = V.position + (W - V.position) * (d / span)
                dist = self._pixel_distance(viewport, screen, cursor, P2)
                if dist is None or dist > self.FILLET_PX:
                    continue
                if best is None or dist < best[0]:
                    best = (dist, V.position, P2, B)
        if best is None:
            return None
        return QVector3D(best[1]), QVector3D(best[2]), best[3]

    def _pixel_distance(self, viewport, screen, cursor, P):
        """Cursor→``P`` distance in screen pixels (a world fallback, scaled
        to pixels, for viewports without a projection)."""
        to_px = getattr(viewport, "_world_to_pixel", None)
        if callable(to_px) and screen is not None:
            q = to_px(P)
            if q is None:
                return None
            return math.hypot(q[0] - screen.x(), q[1] - screen.y())
        along = cursor - P
        if along.length() < 1e-12:
            return 0.0
        scale = self.world_per_pixel(viewport, P, along.normalized())
        if not scale:
            return None
        return along.length() / scale

    def _corner_near(self, viewport, screen, cursor):
        """``(V, A, B)``: the two-edge corner within ``CORNER_PX`` of the
        cursor whose edges are both long enough for the last fillet."""
        scene = getattr(viewport, "scene", None)
        mesh = getattr(scene, "mesh", None)
        d = ArcTool.last_fillet_d
        if mesh is None or not d:
            return None
        best = None
        for V in mesh.vertices:
            edges = list(V.edges)
            if len(edges) != 2:
                continue
            A, B = edges
            if not (A.faces or B.faces):
                continue
            if A.length() < d - 1e-6 or B.length() < d - 1e-6:
                continue
            dist = self._pixel_distance(viewport, screen, cursor, V.position)
            if dist is None or dist > self.CORNER_PX:
                continue
            if best is None or dist < best[0]:
                best = (dist, V, A, B)
        if best is None:
            return None
        return best[1], best[2], best[3]

    def _round_corner(self, viewport, corner, d: float, modifiers) -> None:
        """Draw the fillet of distance ``d`` on ``corner`` and trim it."""
        V, A, B = corner
        P1 = V.position + (A.other(V).position - V.position).normalized() * d
        P2 = V.position + (B.other(V).position - V.position).normalized() * d
        self.start_point = QVector3D(P1)
        self.end_point = QVector3D(P2)
        self._start_edge = (A, QVector3D(P1))
        self._fillet = (QVector3D(V.position), QVector3D(P1), QVector3D(P2))
        self.hover_plane = self._corner_plane(V, A, B)
        self._tangent_dir = (V.position - P1).normalized()
        h = self._tangent_bulge()
        if h is None:
            self._reset()
            return
        self._snap_bulge = h
        self._bulge_kind = "fillet"
        pts = self._points(None, bulge=h)
        if len(pts) >= 2:
            self._commit(viewport, pts, trim=self._corner_trim(modifiers))
        else:
            self._reset()

    @staticmethod
    def _corner_plane(V, A, B):
        a = (A.other(V).position - V.position)
        b = (B.other(V).position - V.position)
        n = QVector3D.crossProduct(a, b)
        if n.length() < 1e-9:
            return None
        return QVector3D(V.position), n.normalized()

    def _corner_trim(self, modifiers):
        """The two corner stubs to erase once a fillet is committed: only
        for an arc that IS the fillet (magenta), on a face, at a corner
        where exactly the two edges meet — «if three edges come together it
        won't cut» — and never with Alt held (the usual way out)."""
        if self._fillet is None or self._bulge_kind != "fillet":
            return None
        if modifiers is not None and (modifiers & Qt.AltModifier):
            return None
        V, P1, P2 = self._fillet
        edge = self._start_edge[0] if self._start_edge else None
        if edge is None or not edge.faces:
            return None
        mesh = getattr(getattr(self._viewport, "scene", None), "mesh", None)
        vert = mesh.vertex_at(V) if mesh is not None else None
        if vert is None or len(vert.edges) != 2:
            return None
        return [(V, P1), (V, P2)]

    # ---- Tangent at vertex ---------------------------------------------------
    def _tangent_at_start(self, viewport) -> QVector3D | None:
        """The direction an existing arc leaves its END vertex when that
        vertex is our start point — the tangent this arc can continue."""
        scene = getattr(viewport, "scene", None)
        mesh = getattr(scene, "mesh", None)
        if mesh is None or self.start_point is None:
            return None
        # The loose mesh first, then every placed group / component in its
        # own space (inference reaches geometry inside them from outside).
        spaces = [(mesh, None)]
        placements = getattr(viewport, "_placements", None)
        if callable(placements):
            for g in placements():
                gm = getattr(g, "mesh", None)
                if gm is not None and gm.edges and not getattr(g, "billboard", False):
                    spaces.append((gm, getattr(g, "xform", None)))
        for gm, xf in spaces:
            inv = None
            if xf is not None:
                inv, ok = xf.inverted()
                if not ok:
                    continue
            P = inv.map(self.start_point) if inv is not None else self.start_point
            t = self._tangent_in_mesh(gm, P)
            if t is None:
                continue
            if xf is not None:
                t = xf.mapVector(t)
                if t.length() < 1e-9:
                    continue
                t = t.normalized()
            return t
        return None

    @staticmethod
    def _tangent_in_mesh(mesh, P: QVector3D) -> QVector3D | None:
        from core.snap import fit_circle
        for edge in mesh.edges:
            if getattr(edge, "curve", None) is None:
                continue
            if (edge.a - P).length() > 1e-6 and (edge.b - P).length() > 1e-6:
                continue
            chain = mesh.curve_edges(edge)
            incident = [e for e in chain
                        if (e.a - P).length() <= 1e-6 or (e.b - P).length() <= 1e-6]
            if len(incident) != 1:
                continue                       # not the arc's end
            e = incident[0]
            Q = e.b if (e.a - P).length() <= 1e-6 else e.a
            pts: dict = {}
            for c in chain:
                for vv in (c.v0, c.v1):
                    pts[id(vv)] = vv.position
            fit = fit_circle(list(pts.values())) if len(pts) >= 3 else None
            if fit is None:
                continue
            radial = (P - fit[0])
            if radial.length() < 1e-9:
                continue
            r_hat = radial.normalized()
            leaving = P - Q
            t = leaving - r_hat * QVector3D.dotProduct(leaving, r_hat)
            if t.length() < 1e-9:
                continue
            return t.normalized()
        return None

    def _tangent_bulge(self, end: QVector3D | None = None,
                       tangent: QVector3D | None = None) -> float | None:
        """The signed bulge that makes this arc leave the start along
        ``tangent`` (default: ``_tangent_dir``) toward ``end`` (default:
        the end point): for a chord of length L meeting the tangent at
        angle a, the sagitta is (L/2)·tan(a/2), on the tangent's side."""
        tangent = self._tangent_dir if tangent is None else tangent
        end = self.end_point if end is None else end
        if tangent is None or end is None:
            return None
        u, v = self._axes()
        e2 = self._to2(end, u, v)
        length = math.hypot(*e2)
        if length < 1e-9:
            return None
        cx, cy = e2[0] / length, e2[1] / length
        tx = QVector3D.dotProduct(tangent, u)
        ty = QVector3D.dotProduct(tangent, v)
        tl = math.hypot(tx, ty)
        if tl < 1e-6:
            return None                        # tangent leaves the plane
        tx, ty = tx / tl, ty / tl
        angle = math.atan2(cx * ty - cy * tx, cx * tx + cy * ty)
        if abs(abs(angle) - math.pi) < 1e-3:
            return None                        # doubling back: no arc
        return (length / 2.0) * math.tan(angle / 2.0)

    def on_value(self, viewport, value) -> bool:
        if self.end_point is None or self.hover_point is None:
            return False
        if isinstance(value, tuple):
            return False
        if self._fillet is not None:
            # Both tangencies fixed — the corner is being rounded — so the
            # number is the fillet's RADIUS, the one thing a drafter means
            # there (@pacaeiro, issue #43: «when Tangent to Edge is fixed
            # on both sides and we write a value it is directed to bulge,
            # instead of Arc radius, keeping the tangencies»).
            return self._fillet_with_radius(viewport, float(value))
        sign = -1.0 if self._bulge_for(self.hover_point) < 0 else 1.0
        self._bulge_kind = None
        pts = self._points(None, bulge=sign * value)
        if len(pts) >= 2:
            self._commit(viewport, pts)
        return True

    def _fillet_with_radius(self, viewport, radius: float) -> bool:
        """Redraw the armed fillet with ``radius``: the tangent points move
        to ``d = r / tan(θ/2)`` from the corner along each edge (θ the
        angle the edges make), the arc stays tangent to both, the corner
        is trimmed. A radius the edges cannot hold is refused, and said."""
        V, P1, P2 = self._fillet
        a = P1 - V
        b = P2 - V
        if radius <= 0 or a.length() < 1e-9 or b.length() < 1e-9:
            return False
        ua, ub = a.normalized(), b.normalized()
        cos_t = max(-1.0, min(1.0, QVector3D.dotProduct(ua, ub)))
        theta = math.acos(cos_t)
        if theta < 1e-3 or abs(theta - math.pi) < 1e-3:
            return False                       # no corner to round
        d = radius / math.tan(theta / 2.0)
        edge_a = self._start_edge[0] if self._start_edge else None
        edge_b = self._fillet_edge_b
        reach = []
        for e in (edge_a, edge_b):
            if e is None:
                continue
            reach.append((e.v0.position - e.v1.position).length())
        if reach and d > min(reach) + 1e-6:
            viewport.flash_status(tr(
                "Radius {r} needs {d} of edge on each side of the "
                "corner; the shorter one is {e}",
                r=fmt_len(radius), d=fmt_len(d), e=fmt_len(min(reach))))
            return True
        self.start_point = V + ua * d
        self.end_point = V + ub * d
        if self._start_edge is not None:
            self._start_edge = (self._start_edge[0], QVector3D(self.start_point))
        self._fillet = (QVector3D(V), QVector3D(self.start_point),
                        QVector3D(self.end_point))
        self._tangent_dir = (V - self.start_point).normalized()
        h = self._tangent_bulge()
        if h is None:
            return False
        self._snap_bulge = h
        self._bulge_kind = "fillet"
        pts = self._points(None, bulge=h)
        if len(pts) < 2:
            return False
        self._commit(viewport, pts, trim=self._corner_trim(None))
        return True

    def on_radius_value(self, viewport, radius: float) -> bool:
        """The usual "2r": type the RADIUS instead of the bulge. The minor
        arc is taken (as usual); a radius smaller than half the chord
        is impossible and is refused with a status message."""
        if self.end_point is None or radius <= 0:
            return False
        half = (self.end_point - self.start_point).length() * 0.5
        if half < 1e-9:
            return False
        if radius < half - 1e-9:
            viewport.flash_status(tr(
                "Radius {r} is smaller than half the chord ({h})",
                r=fmt_len(radius), h=fmt_len(half)))
            return True
        radius = max(radius, half)
        h = radius - math.sqrt(max(radius * radius - half * half, 0.0))
        sign = 1.0
        if self.hover_point is not None and self._bulge_for(self.hover_point) < 0:
            sign = -1.0
        # A typed radius while the arc is magenta keeps the fillet's trim
        # only when it IS the fillet radius («enter the radius
        # while the radius is still magenta»).
        trim = None
        if self._fillet is not None:
            h_t = self._tangent_bulge()
            if h_t is not None and abs(abs(h_t) - h) <= 1e-6 * max(1.0, radius):
                sign = math.copysign(1.0, h_t)
                self._bulge_kind = "fillet"
                trim = self._corner_trim(None)
        pts = self._points(None, bulge=sign * h)
        if len(pts) >= 2:
            self._commit(viewport, pts, trim=trim)
        return True

    def on_segments_value(self, viewport, n: int) -> bool:
        """The usual "Ns": the segment count of the arc — the one being
        drawn, or the one just drawn, which is rebuilt in place."""
        n = int(n)
        if n < 2:
            return False
        self.segments = n
        cmd, params = self._last_cmd, self._last_params
        stack = getattr(getattr(viewport, "history", None), "undo_stack", None)
        if cmd is not None and params is not None and stack and stack[-1] is cmd:
            viewport.history.undo()
            pts, trim = params
            start, end, apex = pts
            pts2 = _arc_3pts_2d((0.0, 0.0), apex[0], apex[1], self.segments)
            u, v, origin = apex[2]
            points = [origin + u * x + v * y for x, y in pts2]
            self._last_cmd = commit_arc(viewport, points, trim=trim)
            self._last_params = params
            viewport.update()
        viewport.flash_status(tr("{n} segments", n=n))
        return True

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- Preview ------------------------------------------------------------
    def rubber_band_lines(self):
        if self.start_point is None or self.hover_point is None:
            return []
        if self.end_point is None:
            if self._start_edge is not None:
                # Tangent to the start edge, through the cursor
                # («a tangent arc vs a dotted line»).
                tangent = self._edge_tangent(self.hover_point)
                h = self._tangent_bulge(end=self.hover_point, tangent=tangent)
                if h is not None:
                    pts = self._points(None, bulge=h, end=self.hover_point)
                    if len(pts) >= 2:
                        return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
            return [(self.start_point, self.hover_point)]   # the chord
        pts = self._points(self.hover_point)
        return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]

    def value_label(self):
        if self.start_point is None or self.hover_point is None:
            return None
        if self.end_point is None:
            if self._start_edge is not None:
                return (tr("Tangent to edge"),
                        (self.start_point + self.hover_point) * 0.5)
            return None
        mid = (self.start_point + self.end_point) * 0.5
        if self._snap_bulge is not None:
            if self._bulge_kind == "half":
                return (tr("Half circle") + "  " + fmt_len(abs(self._snap_bulge)), mid)
            if self._bulge_kind == "fillet":
                return (tr("Tangent to edge") + "  " + fmt_len(abs(self._snap_bulge)), mid)
            return (tr("Tangent at vertex") + "  " + fmt_len(abs(self._snap_bulge)), mid)
        b = self._bulge_for(self.hover_point)
        return ("Bulge " + fmt_len(abs(b)), mid)

    # ---- Internals ----------------------------------------------------------
    def _axes(self) -> tuple[QVector3D, QVector3D]:
        normal = self.drawing_plane()[1]
        return plane_axes(normal)

    def plane_points(self):
        """Start and end: an end snapped off the plane turns the arc to the
        axis plane holding both (``PlaneLock.snapped_plane``) — before, it
        ended on the end's projection, nowhere near the point clicked."""
        if self.start_point is None:
            return []
        return [self.start_point,
                self.end_point if self.end_point is not None
                else self.hover_point]

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

    def _points(self, cursor, bulge: float | None = None,
                end: QVector3D | None = None) -> list[QVector3D]:
        end = self.end_point if end is None else end
        u, v = self._axes()
        s2 = (0.0, 0.0)
        e2 = self._to2(end, u, v)
        length = math.hypot(*e2)
        if length < 1e-9:
            return []
        if bulge is not None:
            h = bulge
        elif self._snap_bulge is not None:
            h = self._snap_bulge                        # tangent to the arc before
        else:
            h = self._bulge_for(cursor)
        if abs(h) < 1e-4:
            return [self.start_point, end]              # flat → straight chord
        px, py = -e2[1] / length, e2[0] / length
        mid = (e2[0] / 2.0, e2[1] / 2.0)
        apex = (mid[0] + px * h, mid[1] + py * h)
        self._last_apex = (apex, e2, (u, v, QVector3D(self.start_point)))
        pts2 = _arc_3pts_2d(s2, apex, e2, self.segments)
        return [self.start_point + u * x + v * y for x, y in pts2]

    def _commit(self, viewport, pts: list[QVector3D], trim=None) -> None:
        apex = getattr(self, "_last_apex", None)
        if trim and self._fillet is not None:
            V, P1, _P2 = self._fillet
            ArcTool.last_fillet_d = (P1 - V).length()
        self._last_cmd = commit_arc(viewport, pts, trim=trim)
        self._last_params = None
        if apex is not None and len(pts) >= 3:
            self._last_params = ((None, None, apex), trim)
        self._reset()
        viewport.update()

    def on_key(self, viewport, key: int, modifiers) -> bool:
        return self.plane_lock_key(viewport, key)

    def _reset(self) -> None:
        self.start_point = None
        self.end_point = None
        self.work_plane = None
        self.hover_plane = None
        self.clear_plane_lock()
        self._tangent_dir = None
        self._snap_bulge = None
        self._bulge_kind = None
        self._start_edge = None
        self._equidistant = None
        self._fillet = None
        self._fillet_edge_b = None
        self._last_apex = None
        self.wireframe_color = None


class ThreePointArcTool(AxisMagnet, PlaneLock, Tool):
    """3-point arc: the arc passes through all three clicked points.

    Click start, click a second point the arc runs through, then move and click
    the end point. The circle through the three points defines the arc.
    """
    name = "3-Point Arc"
    shortcut = "J"
    description = "Draw an arc that passes through three points."

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None
        self.mid_point: QVector3D | None = None
        self.hover_point: QVector3D | None = None
        self.work_plane: tuple[QVector3D, QVector3D] | None = None

    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    def on_click(self, ctx: ToolContext) -> None:
        self.note_plane(ctx.viewport)
        if self.start_point is None:
            self.start_point = ctx.world
            if self.work_plane is None:
                self.work_plane = self.locked_work_plane(ctx.world)
            return
        if self.mid_point is None:
            if (ctx.world - self.start_point).length() < 1e-6:
                return
            self.mid_point = ctx.world
            self.adopt_snapped_plane()
            return
        pts = self._points(ctx.world)
        if len(pts) >= 2:
            self._commit(ctx.viewport, pts)

    def on_hover(self, ctx: ToolContext) -> None:
        self.note_plane(ctx.viewport)
        self.hover_point = ctx.world
        ctx.viewport.update()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def rubber_band_lines(self):
        if self.start_point is None or self.hover_point is None:
            return []
        if self.mid_point is None:
            return [(self.start_point, self.hover_point)]
        pts = self._points(self.hover_point)
        return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]

    def _axes(self):
        normal = self.drawing_plane()[1]
        return plane_axes(normal)

    def plane_points(self):
        """The arc's own points: with all three, a snapped one off the plane
        takes the plane through them (``PlaneLock.snapped_plane``)."""
        if self.start_point is None:
            return []
        if self.mid_point is None:
            return [self.start_point, self.hover_point]
        return [self.start_point, self.mid_point, self.hover_point]

    def _points(self, end: QVector3D) -> list[QVector3D]:
        u, v = self._axes()

        def to2(p):
            d = p - self.start_point
            return (QVector3D.dotProduct(d, u), QVector3D.dotProduct(d, v))

        s2, m2, e2 = (0.0, 0.0), to2(self.mid_point), to2(end)
        if math.hypot(*e2) < 1e-9 or math.hypot(*m2) < 1e-9:
            return []
        pts2 = _arc_3pts_2d(s2, m2, e2, _SEGMENTS)
        return [self.start_point + u * x + v * y for x, y in pts2]

    def _commit(self, viewport, pts: list[QVector3D]) -> None:
        commit_arc(viewport, pts)
        self._reset()
        viewport.update()


    def on_key(self, viewport, key: int, modifiers) -> bool:
        return self.plane_lock_key(viewport, key)

    def _reset(self) -> None:
        self.start_point = None
        self.mid_point = None
        self.work_plane = None
        self.hover_plane = None
        self.clear_plane_lock()


class CenterArcTool(AxisMagnet, PlaneLock, Tool):
    """Compass arc (the classic protractor 'Arc'): centre → start point (the
    radius and 0° arm) → sweep angle. The polyline samples at the same 15°
    pitch as the 24-side circle, so a centre arc drawn concentric with a
    circle lands on the exact same lattice and welds cleanly."""

    name = "Center Arc"
    #: Shift+O, not O: by convention plain O is Orbit and the centre arc has no
    #: default key at all. Sharing O made Qt call the shortcut ambiguous and
    #: fire NEITHER — see tests/test_shortcuts.py.
    shortcut = "Shift+O"
    description = (
        "Draw an arc from its centre: the centre, where the arc "
        "starts, then the angle it sweeps.")
    vcb_label = "Angle"

    _PITCH_DEG = 15.0

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None   # the centre
        self.arm_point: QVector3D | None = None     # radius + 0° direction
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
        self.note_plane(ctx.viewport)
        if self.start_point is None:
            self.start_point = ctx.world
            if self.work_plane is None:
                self.work_plane = self.locked_work_plane(ctx.world)
            return
        if self.arm_point is None:
            if (ctx.world - self.start_point).length() < 1e-6:
                return
            self.arm_point = ctx.world
            self.adopt_snapped_plane()   # the sweep is read on the arc's plane
            return
        pts = self._points(self._sweep_to(ctx.world))
        if len(pts) >= 2:
            self._commit(ctx.viewport, pts)

    def on_hover(self, ctx: ToolContext) -> None:
        self.note_plane(ctx.viewport)
        self.hover_point = ctx.world
        ctx.viewport.update()

    def on_value(self, viewport, value) -> bool:
        if self.arm_point is None or isinstance(value, tuple):
            return False
        sign = -1.0
        if self.hover_point is not None:
            sweep = self._sweep_to(self.hover_point)
            sign = -1.0 if sweep < 0 else 1.0
        pts = self._points(sign * abs(value))
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
        if self.arm_point is None:
            return [(self.start_point, self.hover_point)]     # the radius arm
        segments = [(self.start_point, self.arm_point),
                    (self.start_point, self.hover_point)]
        pts = self._points(self._sweep_to(self.hover_point))
        segments.extend(zip(pts, pts[1:]))
        return segments

    def value_label(self):
        if self.hover_point is None or self.start_point is None:
            return None
        if self.arm_point is None:
            u, v = self._axes()          # the radius drawn, as the circle's
            d = self.hover_point - self.start_point
            r = math.hypot(QVector3D.dotProduct(d, u),
                           QVector3D.dotProduct(d, v))
            return ("R " + fmt_len(r), self.hover_point)
        return (f"{self._sweep_to(self.hover_point):+.1f}°", self.hover_point)

    def vcb_caption(self) -> str:
        return "Angle" if self.arm_point is not None else "Radius"

    # ---- Internals ----------------------------------------------------------
    def _axes(self):
        normal = self.drawing_plane()[1]
        return plane_axes(normal)

    def plane_points(self):
        """Centre and arm: an arm snapped off the plane turns the arc to the
        axis plane holding both (``PlaneLock.snapped_plane``). The sweep
        point is only an angle, so it never moves the plane."""
        if self.start_point is None:
            return []
        return [self.start_point,
                self.arm_point if self.arm_point is not None
                else self.hover_point]

    def _sweep_to(self, cursor: QVector3D) -> float:
        """Signed sweep (degrees) from the 0° arm to the cursor."""
        u, v = self._axes()
        a = self.arm_point - self.start_point
        b = cursor - self.start_point
        a0 = math.atan2(QVector3D.dotProduct(a, v), QVector3D.dotProduct(a, u))
        b0 = math.atan2(QVector3D.dotProduct(b, v), QVector3D.dotProduct(b, u))
        deg = math.degrees(b0 - a0)
        while deg <= -180.0:
            deg += 360.0
        while deg > 180.0:
            deg -= 360.0
        return deg

    def _points(self, sweep_deg: float) -> list[QVector3D]:
        if abs(sweep_deg) < 1e-6:
            return []
        u, v = self._axes()
        a = self.arm_point - self.start_point
        r = math.hypot(QVector3D.dotProduct(a, u), QVector3D.dotProduct(a, v))
        if r < 1e-6:
            return []
        a0 = math.atan2(QVector3D.dotProduct(a, v), QVector3D.dotProduct(a, u))
        steps = max(1, round(abs(sweep_deg) / self._PITCH_DEG))
        out = []
        for k in range(steps + 1):
            t = a0 + math.radians(sweep_deg) * k / steps
            out.append(self.start_point
                       + (u * math.cos(t) + v * math.sin(t)) * r)
        return out

    def _commit(self, viewport, pts: list[QVector3D]) -> None:
        commit_arc(viewport, pts)
        self._reset()
        viewport.update()


    def on_key(self, viewport, key: int, modifiers) -> bool:
        return self.plane_lock_key(viewport, key)

    def _reset(self) -> None:
        self.start_point = None
        self.arm_point = None
        self.work_plane = None
        self.hover_plane = None
        self.clear_plane_lock()


class PieTool(CenterArcTool):
    """The classic Pie: the centre arc whose wedge CLOSES — the two radius
    edges join the arc's ends to the centre and the slice becomes a face.
    Same clicks as Center Arc: centre, radius arm, sweep."""

    name = "Pie"
    shortcut = None
    description = (
        "Draw an arc from its centre whose two radii close it into a "
        "slice-shaped face.")

    def _commit(self, viewport, pts: list[QVector3D]) -> None:
        centre = QVector3D(self.start_point)
        commit_arc(viewport, pts, close_to=centre)
        self._reset()
        viewport.update()
