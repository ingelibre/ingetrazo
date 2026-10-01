# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Offset tool: offset a face's boundary in its plane (walls with thickness).

Offset (F): pick a face, drag (or type a distance) and a parallel
loop appears offset from the boundary. The face splits into a ring (the wall
footprint) and an inner face (the room), so the ring can then be pushed up into
walls with thickness — the casita's first hito.

Inward (toward the interior) is the common case for walls; dragging the cursor
outside the face offsets outward instead. The exact thickness is usually typed
into the VCB.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import (
    AddFaceCommand,
    DeleteFaceCommand,
    SnapshotCompound,
)
from core.i18n import tr
from core.mesh import Edge, Face
from core.offset import offset_chain, offset_regions
from core.topology import max_offset_distance, offset_loop
from core.units import fmt_len
from tools.base import Tool, ToolContext


def _point_segment_distance(p: QVector3D, a: QVector3D, b: QVector3D) -> float:
    ab = b - a
    length_sq = QVector3D.dotProduct(ab, ab)
    if length_sq < 1e-12:
        return (p - a).length()
    t = max(0.0, min(1.0, QVector3D.dotProduct(p - a, ab) / length_sq))
    return (p - (a + ab * t)).length()


class OffsetTool(Tool):
    name = "Offset"
    shortcut = "F"
    description = (
        "Draw a copy of a face's outline at an even distance inside "
        "or outside it — walls with thickness.")
    uses_snap = False  # picks a face; no snap markers
    vcb_label = "Offset"
    wireframe_color = (0.13, 0.17, 0.23, 1.0)
    wireframe_depth_tested = True

    def __init__(self) -> None:
        self.hovered_face: Face | None = None
        self.hovered_edge: Edge | None = None
        self.base_face: Face | None = None
        self.distance: float = 0.0  # signed; >0 inward, <0 outward
        self.dragging: bool = False
        self._loop: list[QVector3D] = []
        self._normal: QVector3D | None = None
        self._ref_point: QVector3D | None = None   # a point on the reference edge
        self._ref_inward: QVector3D | None = None   # its in-plane inward normal
        #: Edges mode (issue #40, @pacaeiro): ``_loop`` is a run of connected
        #: coplanar edges — open (a polyline) or closed (a loop with no
        #: face) — instead of a face's boundary. The offset is new edges.
        self._chain: bool = False
        self._closed: bool = True
        #: A run taken from the selection when the tool was picked up
        #: (select the edges, then Offset): the first click
        #: starts the offset instead of picking.
        self._armed: bool = False

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()
        self._arm_from_selection(viewport)

    def on_deactivate(self, viewport) -> None:
        viewport.set_hover(None)
        self._reset()
        viewport.update()

    # ---- Spatial input ------------------------------------------------------
    def on_hover(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        if not self.dragging:
            if self._armed:
                return                       # the run is chosen; click starts
            self.hovered_face = viewport.pick_face(ctx.screen.x(), ctx.screen.y())
            self.hovered_edge = None
            if self.hovered_face is None:
                # No face under the cursor: an edge is a run of edges.
                pick_edge = getattr(viewport, "pick_edge", None)
                self.hovered_edge = (pick_edge(ctx.screen.x(), ctx.screen.y())
                                     if pick_edge is not None else None)
            viewport.set_hover(self.hovered_face or self.hovered_edge)
            return
        cursor = self._cursor_on_plane(viewport, ctx.screen.x(), ctx.screen.y())
        if cursor is not None and self._ref_point is not None:
            self.distance = QVector3D.dotProduct(cursor - self._ref_point, self._ref_inward)
        viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        if not self.dragging:
            if self._armed:
                self._armed = False          # the run is already in _loop
            elif self.hovered_face is not None:
                face = self.hovered_face
                if len(face.vertices) < 3:
                    return
                self.base_face = face
                self._loop = [QVector3D(v) for v in face.vertices]
                self._normal = face.normal()
                self._chain, self._closed = False, True
            elif self.hovered_edge is not None:
                if not self._take_run(viewport, _run_from_edge(self.hovered_edge)):
                    return
            else:
                return
            self.distance = 0.0
            self.dragging = True
            self._pick_reference(viewport, ctx.screen.x(), ctx.screen.y())
            viewport.set_hover(None)
            viewport.update()
            return
        if abs(self.distance) < 1e-6:
            return
        self._commit(viewport)

    def on_value(self, viewport, value) -> bool:
        if isinstance(value, tuple):
            return False
        if not self.dragging or not self._loop or value <= 0.0:
            return False
        # Keep the side the user is dragging toward; default to inward.
        sign = -1.0 if self.distance < 0.0 else 1.0
        self.distance = sign * value
        self._commit(viewport)
        return True

    def on_cancel(self, viewport) -> None:
        viewport.set_hover(None)
        self._reset()
        viewport.update()

    # ---- Visual preview -----------------------------------------------------
    def rubber_band_lines(self):
        if not self.dragging or not self._loop or abs(self.distance) < 1e-6:
            return []
        off = self._offset_points()
        if off is None:
            return []
        return _segments(off, self._closed)

    def _offset_points(self):
        """The slid boundary / run at the current distance, or ``None``."""
        if self._closed:
            return offset_loop(self._loop, self._normal, self.distance)
        return offset_chain(self._loop, self._normal, self.distance)

    # ---- Internals ----------------------------------------------------------
    def _pick_reference(self, viewport, sx, sy) -> None:
        """Lock onto the boundary edge nearest the click; offset is measured as
        the cursor's perpendicular distance from it (so dragging across that edge
        flips inward/outward naturally)."""
        cursor = self._cursor_on_plane(viewport, sx, sy)
        segs = _segments(self._loop, self._closed)
        best_i, best_d = 0, float("inf")
        for i, (a, b) in enumerate(segs):
            d = _point_segment_distance(cursor, a, b) if cursor is not None else 0.0
            if d < best_d:
                best_d, best_i = d, i
        a, b = segs[best_i]
        e = (b - a).normalized()
        self._ref_point = QVector3D(a)
        self._ref_inward = QVector3D.crossProduct(self._normal.normalized(), e).normalized()

    def _cursor_on_plane(self, viewport, sx, sy):
        """Cast the cursor ray onto the base face's plane."""
        origin, direction = viewport._pixel_to_ray(sx, sy)
        if origin is None or direction is None:
            return None
        n = self._normal
        denom = QVector3D.dotProduct(direction, n)
        if abs(denom) < 1e-9:
            return None
        anchor = (self.base_face.centroid() if self.base_face is not None
                  else self._loop[0])
        t = QVector3D.dotProduct(anchor - origin, n) / denom
        return origin + direction * t

    # ---- Edges mode (issue #40) ----------------------------------------------
    def _arm_from_selection(self, viewport) -> None:
        """The other way in: the edges were selected BEFORE the tool
        was picked up. Two or more edges and nothing else → their run is
        the thing to offset, and the first click starts the drag."""
        scene = getattr(viewport, "scene", None)
        selection = list(getattr(scene, "selection", None) or ())
        edges = [e for e in selection if isinstance(e, Edge)]
        if len(edges) < 2 or len(edges) != len(selection):
            return
        run = _run_from_edges(edges)
        if run is None:
            return                     # not one connected run: say nothing yet
        if self._take_run(viewport, run):
            self._armed = True
            viewport.flash_status(tr(
                "{n} edges selected — click to start the offset",
                n=len(edges)), 4000)

    def _take_run(self, viewport, run) -> bool:
        """Adopt ``run`` = ``(points, closed)`` as the thing to offset, or
        say why it cannot be."""
        if run is None:
            viewport.flash_status(tr(
                "Offset needs one connected run of edges — a polyline, "
                "or a closed loop."), 5000)
            return False
        points, closed = run
        normal = _newell(points)
        if normal is None:
            if len(points) == 2 and not closed:
                # ONE line on its own: say so, and show it. Rafael clicked
                # his roof line, got the «not in line» message and could not
                # see why — the line it should have joined had been lost in
                # an undo, so there was only one (revision 4, 04:42–05:08).
                viewport.flash_status(tr(
                    "This line is on its own — nothing is joined to its "
                    "ends, so there is no chain to offset. Draw the "
                    "missing line, or select the edges to offset."), 6000)
                edge = getattr(self, "hovered_edge", None)
                if edge is not None and hasattr(viewport, "scene"):
                    viewport.scene.select([edge])
                return False
            viewport.flash_status(tr(
                "Offset needs at least two edges that are not in line — a "
                "straight run has no plane to offset in."), 5000)
            return False
        self.base_face = None
        self._loop = points
        self._normal = normal
        self._chain, self._closed = True, closed
        return True

    def _commit(self, viewport) -> None:
        if self._chain:
            self._commit_chain(viewport)
            return
        regions = offset_regions(self._loop, self._normal, self.distance)
        if not regions:
            # Safety net: the exact slide-and-intersect path still runs when
            # the arrangement finds nothing, so a bug here can only lose the
            # new cases, never the ones that already worked.
            fallback = offset_loop(self._loop, self._normal, self.distance)
            if fallback is not None:
                regions = [(fallback, [])]
        if not regions:
            self._refuse(viewport)
            return
        # Inward: the original boundary is the outer ring and each surviving
        # region is a hole in it — plural, because a shape pinched at the
        # waist really does come apart (a dumbbell with a 60 cm neck splits
        # in two at 40 cm). Outward: the biggest region is the ring and the
        # original is its single hole.
        attrs = dict(getattr(self.base_face, "attrs", None) or {})
        if self.distance > 0:
            outer = self._loop
            inners = [loop for loop, _holes in regions]
        else:
            outer = max((loop for loop, _holes in regions),
                        key=lambda lp: _loop_extent(lp))
            inners = [self._loop]
        commands = [DeleteFaceCommand(self.base_face),
                    AddFaceCommand(list(outer), auto=False,
                                   holes=[list(lp) for lp in inners],
                                   attrs=dict(attrs))]
        for loop in inners:
            commands.append(AddFaceCommand(list(loop), auto=False,
                                           attrs=dict(attrs)))
        # Curve ids only when the offset kept the source's shape one-to-one:
        # with the boundary re-arranged there is no run to mirror.
        if len(regions) == 1 and len(regions[0][0]) == len(self._loop):
            commands.extend(self._curve_tags(viewport.scene.mesh,
                                             list(regions[0][0])))
        # Snapshot undo: Delete/Add compose fine forward, but the hole edges
        # the ring creates don't reverse cleanly command-by-command (they
        # leaked on undo). One snapshot reverses exactly.
        viewport.history.execute(SnapshotCompound(commands))
        self._reset()
        viewport.update()

    def _commit_chain(self, viewport) -> None:
        """Edges mode: the slid run becomes new edges — nothing is deleted
        and no face is managed; a run that closes a planar loop gets its
        face from the ordinary edge detection, as if drawn by hand."""
        off = self._offset_points()
        if off is None:
            viewport.flash_status(tr(
                "{d} collapses this run — try a smaller offset",
                d=fmt_len(abs(self.distance))), 5000)
            self._reset()
            viewport.update()
            return
        cam = getattr(viewport, "camera", None)
        eye = cam.eye() if cam is not None and hasattr(cam, "eye") else None
        viewport.history.execute(
            build_add_edges(viewport.scene, _segments(off, self._closed),
                            eye=eye))
        self._reset()
        viewport.update()

    def _refuse(self, viewport) -> None:
        """Nothing survives the offset — say the limit instead of going quiet.
        A 20 cm kerb takes no 10 cm inward offset: 0.20 - 2 x 0.10 is zero."""
        sign = -1.0 if self.distance < 0 else 1.0
        room = max_offset_distance(self._loop, self._normal, sign)
        side = tr("inward") if sign > 0 else tr("outward")
        if room <= 1e-4:
            viewport.flash_status(tr(
                "{d} closes this face — it takes no offset {side}",
                d=fmt_len(abs(self.distance)), side=side), 5000)
        else:
            viewport.flash_status(tr(
                "{d} closes this face — {side} it takes at most "
                "{max}", d=fmt_len(abs(self.distance)), side=side,
                max=fmt_len(room)),
                5000)
        self._reset()
        viewport.update()

    def _curve_tags(self, mesh, off: list[QVector3D]) -> list:
        from core.history import TagCurveCommand

        loop = self._loop
        n = len(loop)
        ids: list = []
        for i in range(n):
            va = mesh.vertex_at(loop[i])
            vb = mesh.vertex_at(loop[(i + 1) % n])
            e = mesh.find_edge(va, vb) if va is not None and vb is not None \
                else None
            ids.append(e.curve if e is not None else None)
        if ids[0] is not None and all(c == ids[0] for c in ids):
            return [TagCurveCommand(list(off), closed=True)]  # full circle
        tags = []
        for k in range(n):
            if ids[k] is None or ids[(k - 1) % n] == ids[k]:
                continue                                       # not a run start
            pts, j = [off[k]], k
            while ids[j] == ids[k]:
                pts.append(off[(j + 1) % n])
                j = (j + 1) % n
            tags.append(TagCurveCommand(pts, closed=False))
        return tags

    def _reset(self) -> None:
        self.hovered_face = None
        self.hovered_edge = None
        self.base_face = None
        self.distance = 0.0
        self.dragging = False
        self._loop = []
        self._normal = None
        self._ref_point = None
        self._ref_inward = None
        self._chain = False
        self._closed = True
        self._armed = False


def _segments(points: list, closed: bool) -> list:
    """Consecutive pairs of ``points``, wrapping when ``closed``."""
    n = len(points)
    if n < 2:
        return []
    last = n if closed else n - 1
    return [(points[i], points[(i + 1) % n]) for i in range(last)]


def _newell(points: list):
    """The plane normal of a polyline by Newell's method (open runs
    included: the closing edge only adds a term), or ``None`` when the
    points are in line."""
    n = len(points)
    if n < 3:
        return None
    nx = ny = nz = 0.0
    for i in range(n):
        p, q = points[i], points[(i + 1) % n]
        nx += (p.y() - q.y()) * (p.z() + q.z())
        ny += (p.z() - q.z()) * (p.x() + q.x())
        nz += (p.x() - q.x()) * (p.y() + q.y())
    normal = QVector3D(nx, ny, nz)
    span = max((p - points[0]).length() for p in points) or 1.0
    if normal.length() < 1e-6 * span * span:
        return None
    return normal.normalized()


def _run_from_edges(edges: list):
    """Order a set of edges into one run: ``(points, closed)``. ``None``
    unless every vertex joins at most two of them and they form a single
    path or cycle."""
    nbrs: dict = {}
    for e in edges:
        for v in (e.v0, e.v1):
            nbrs.setdefault(id(v), (v, []))[1].append(e)
    if any(len(es) > 2 for _v, es in nbrs.values()):
        return None
    ends = [v for v, es in nbrs.values() if len(es) == 1]
    if len(ends) not in (0, 2):
        return None
    closed = not ends
    start = ends[0] if ends else edges[0].v0
    points = [QVector3D(start.position)]
    seen: set = set()
    v = start
    while True:
        nxt = next((e for e in nbrs[id(v)][1] if id(e) not in seen), None)
        if nxt is None:
            break
        seen.add(id(nxt))
        v = nxt.other(v)
        if closed and v is start:
            break
        points.append(QVector3D(v.position))
    if len(seen) != len(edges):
        return None                           # two separate runs
    return points, closed


def _run_from_edge(edge: Edge):
    """The run ``edge`` belongs to, walked both ways through vertices
    where exactly two edges meet (a corner of a polyline); a junction or a
    free end stops the walk. ``(points, closed)``."""
    def walk(v, e):
        out = []
        while len(v.edges) == 2:
            e = next(x for x in v.edges if x is not e)
            if e is edge:
                return out, True              # came round: a closed loop
            v = e.other(v)
            out.append(QVector3D(v.position))
        return out, False
    fwd, closed = walk(edge.v1, edge)
    if closed:
        return [QVector3D(edge.v0.position), QVector3D(edge.v1.position)] + fwd[:-1], True
    back, _ = walk(edge.v0, edge)
    return list(reversed(back)) + [QVector3D(edge.v0.position),
                                   QVector3D(edge.v1.position)] + fwd, False


def _loop_extent(loop) -> float:
    """A cheap size for picking the biggest region: the bounding box's
    diagonal. Area would need the plane; this only has to rank."""
    xs = [p.x() for p in loop]
    ys = [p.y() for p in loop]
    zs = [p.z() for p in loop]
    return ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2
            + (max(zs) - min(zs)) ** 2)
