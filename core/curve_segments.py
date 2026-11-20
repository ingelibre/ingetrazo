# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Change the segment count of a circle, arc or polygon already drawn.

The «24s» of the Circle, Polygon and Arc tools only reaches the shape just
drawn. Entity Info lets the count of any of them change later: the curve is
read back from its edges (they only carry a shared curve id, no centre or
radius, so both are fitted from the vertices) and rebuilt in place.

The rebuild is surgery, not erase-and-redraw: every face the curve bounds
keeps its loop, its holes and its paint, with the curve's run of vertices
swapped for the new ones. An arc keeps its two ends, so whatever it is
joined to stays joined. Resegmenting requires a flat curve. Radius changes
on a non-flat closed curve move its shared vertices and adjacent faces.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtGui import QVector3D

from core.history import Command, CommandRejected, SnapshotMutation

#: The fewest segments a closed curve (a triangle) and an arc can have.
MIN_CLOSED = 3
MIN_OPEN = 2
#: Above this the panel's field stops: a curve this fine is a mistake.
MAX_SEGMENTS = 999

_REL_TOL = 1e-3      # radius and chord spread, relative to the radius
_F32_EPS = 2.0 ** -23  # a single-precision step, relative to the value
_F32_STEPS = 3         # the rounding a position and a difference carry


@dataclass
class CurveShape:
    """A regular curve read back from its edges."""
    edges: list            # the curve's edges, in walking order
    verts: list            # its vertices in walking order (ends included)
    closed: bool
    center: QVector3D
    normal: QVector3D
    u: QVector3D           # toward the first vertex
    v: QVector3D           # normal × u, turned so the walk runs +angle
    radius: float
    sweep: float           # 2π for a closed curve
    flat: bool             # every face it bounds lies in its plane

    @property
    def segments(self) -> int:
        return len(self.edges)

    @property
    def minimum(self) -> int:
        return MIN_CLOSED if self.closed else MIN_OPEN

    def points(self, n: int) -> list[QVector3D]:
        """``n`` segments along the same circle: n points closed (the first
        one kept), n + 1 open (both ends kept exactly)."""
        if self.closed:
            angles = [self.sweep * k / n for k in range(n)]
        else:
            angles = [self.sweep * k / n for k in range(n + 1)]
        pts = [self.center + (self.u * math.cos(a) + self.v * math.sin(a))
               * self.radius for a in angles]
        pts[0] = QVector3D(self.verts[0].position)
        if not self.closed:
            pts[-1] = QVector3D(self.verts[-1].position)
        return pts

    def points_at_radius(self, new_radius: float) -> list[QVector3D] | None:
        """``points(self.segments)`` scaled to ``new_radius``: the centre stays
        put for a closed curve; for an arc the two ends stay put and the
        centre moves along the perpendicular bisector (the bulge changes).
        ``None`` when the new radius cannot hold the arc's chord."""
        new_radius = float(new_radius)
        if new_radius <= 0:
            return None
        if self.closed:
            return [self.center + (self.u * math.cos(a) + self.v * math.sin(a))
                    * new_radius
                    for a in (self.sweep * k / self.segments
                              for k in range(self.segments))]
        p0 = QVector3D(self.verts[0].position)
        p1 = QVector3D(self.verts[-1].position)
        half = (p1 - p0).length() / 2.0
        if half > new_radius:
            return None
        mid = (p0 + p1) / 2.0
        to_center = self.center - mid
        if to_center.length() < 1e-9:
            return None
        perp = to_center.normalized()
        dist = math.sqrt(max(0.0, new_radius * new_radius - half * half))
        center = mid + perp * dist
        half_angle = math.asin(half / new_radius)
        sweep = (2.0 * half_angle if self.sweep <= math.pi
                 else 2.0 * math.pi - 2.0 * half_angle)
        u = (p0 - center).normalized()
        v = QVector3D.crossProduct(self.normal, u)
        n = self.segments
        pts = [center + (u * math.cos(sweep * k / n)
                         + v * math.sin(sweep * k / n)) * new_radius
               for k in range(n + 1)]
        pts[0] = p0
        pts[-1] = p1
        return pts


def _circumcenter(a: QVector3D, b: QVector3D, c: QVector3D):
    """Centre of the circle through three points, or ``None`` if collinear."""
    ab, ac = b - a, c - a
    n = QVector3D.crossProduct(ab, ac)
    nn = QVector3D.dotProduct(n, n)
    if nn < 1e-18:
        return None
    t = (QVector3D.crossProduct(n, ab) * QVector3D.dotProduct(ac, ac)
         + QVector3D.crossProduct(ac, n) * QVector3D.dotProduct(ab, ab))
    return a + t / (2.0 * nn)


def read_curve(mesh, edge) -> CurveShape | None:
    """The regular circle, arc or polygon ``edge`` belongs to, or ``None``
    when it is not one: no curve id, a curve that is not a simple chain, or
    points that are not evenly spaced on one circle (a freehand stroke)."""
    from core.edits import _order_chain
    if getattr(edge, "curve", None) is None:
        return None
    chain = mesh.curve_edges(edge)
    if len(chain) < 2 or edge not in chain:
        return None
    walk = _order_chain(chain, edge)
    if len(walk) != len(chain):
        return None                                  # not one simple chain
    verts = [walk[0][1]] + [w for _e, _v, w in walk]
    closed = verts[-1] is verts[0]
    if closed:
        verts = verts[:-1]
    if len({id(v) for v in verts}) != len(verts):
        return None                                  # crosses itself
    pts = [v.position for v in verts]
    if len(pts) < 3:
        return None
    # Worked out from the first vertex: positions are single precision,
    # and the centre computed from coordinates kilometres out lost the
    # few millimetres a small circle there is made of.
    origin = QVector3D(pts[0])
    rel = [p - origin for p in pts]
    k = len(rel)
    if closed:
        a, b, c = rel[0], rel[k // 3], rel[(2 * k) // 3]
    else:
        a, b, c = rel[0], rel[k // 2], rel[-1]
    c_rel = _circumcenter(a, b, c)
    if c_rel is None:
        return None
    radius = c_rel.length()
    if radius < 1e-9:
        return None
    # The positions themselves are rounded to their single-precision step,
    # which grows with the distance from the origin.
    far = max(abs(origin.x()), abs(origin.y()), abs(origin.z()))
    tol = max(_REL_TOL * radius, _F32_STEPS * _F32_EPS * far)
    if any(abs((p - c_rel).length() - radius) > tol for p in rel):
        return None
    loop = rel + [rel[0]] if closed else rel
    chords = [(q - p).length() for p, q in zip(loop, loop[1:])]
    if max(chords) - min(chords) > 2.0 * tol:
        return None                                  # unevenly spaced
    u = (rel[0] - c_rel).normalized()
    normal = QVector3D.crossProduct(u, rel[1] - c_rel).normalized()
    if normal.length() < 0.5:
        return None
    if any(abs(QVector3D.dotProduct(p - c_rel, normal)) > tol for p in rel):
        return None                                  # not in one plane
    v = QVector3D.crossProduct(normal, u)
    if closed:
        sweep = 2.0 * math.pi
    else:
        d = rel[-1] - c_rel
        sweep = math.atan2(QVector3D.dotProduct(d, v),
                           QVector3D.dotProduct(d, u))
        if sweep <= 1e-9:
            sweep += 2.0 * math.pi
        # The vertices must run evenly round to the far end, not the
        # short way back (a 300° arc read as its 60° complement).
        step = sweep / (len(rel) - 1)
        d1 = rel[1] - c_rel
        mid = math.atan2(QVector3D.dotProduct(d1, v),
                         QVector3D.dotProduct(d1, u))
        if abs(mid - step) > max(1e-3 * max(1.0, step), 4.0 * tol / radius):
            return None
    center = origin + c_rel
    flat = True
    for e in chain:
        for f in e.faces:
            fn = f.normal()
            if (abs(QVector3D.dotProduct(fn, normal)) < 0.999
                    or any(abs(QVector3D.dotProduct(p - origin - c_rel,
                                                    normal)) > tol
                           for p in f.vertices)):
                flat = False
                break
        if not flat:
            break
    return CurveShape([e for e, _f, _t in walk], verts, closed, center,
                      normal, u, v, radius, sweep, flat)


def _splice(loop, shape: CurveShape, new_pts):
    """``loop`` (vertices) with the curve's run swapped for ``new_pts``
    (positions), or ``None`` when the curve is not one run of it. The
    loop's own winding is kept."""
    verts = shape.verts
    L = len(loop)
    if verts[0] not in loop:
        return None
    if shape.closed:
        if L != len(verts) or {id(v) for v in loop} != {id(v) for v in verts}:
            return None
        i = loop.index(verts[0])
        forward = loop[(i + 1) % L] is verts[1]
        return list(new_pts) if forward else [new_pts[0]] + new_pts[:0:-1]
    i = loop.index(verts[0])
    pos = [p.position for p in loop]
    if loop[(i + 1) % L] is verts[1]:
        run = [loop[(i + j) % L] for j in range(L)]
        rest = [pos[(i + j) % L] for j in range(len(verts), L)]
        if run[:len(verts)] != verts:
            return None
        return list(new_pts) + rest
    if loop[(i - 1) % L] is verts[1]:
        run = [loop[(i - j) % L] for j in range(L)]
        rest = [pos[(i - j) % L] for j in range(len(verts), L)]
        if run[:len(verts)] != verts:
            return None
        return (list(new_pts) + rest)[::-1]
    return None


def _rebuild(mesh, shape: CurveShape, new_pts) -> bool:
    """Swap the curve's run for ``new_pts`` in every face it bounds, then
    rebuild its edges — the surgery :func:`resegment` and the radius edit
    share. Returns ``False`` (mesh untouched) when no face takes the run."""
    from core.mesh import edge_flags, stamp_edge_flags
    faces = []
    for e in shape.edges:
        for f in e.faces:
            if f not in faces:
                faces.append(f)
    plans = []
    for f in faces:
        outer = f.loop
        holes = list(f.hole_loops)
        new_outer = _splice(outer, shape, new_pts)
        new_holes = []
        touched = new_outer is not None
        if new_outer is None:
            new_outer = [v.position for v in outer]
        for h in holes:
            nh = _splice(h, shape, new_pts)
            touched = touched or nh is not None
            new_holes.append(nh if nh is not None else [v.position for v in h])
        if not touched:
            return False
        plans.append(([QVector3D(p) for p in new_outer],
                       [[QVector3D(p) for p in h] for h in new_holes],
                       dict(f.attrs), f.interior))
    flags = edge_flags(shape.edges[0])
    for f in faces:
        mesh.remove_face(f)
    for e in shape.edges:
        mesh.remove_edge(e)
    mesh.prune_orphan_vertices()
    pairs = list(zip(new_pts, new_pts[1:]))
    if shape.closed:
        pairs.append((new_pts[-1], new_pts[0]))
    for a, b in pairs:
        stamp_edge_flags(mesh.add_edge(a, b), flags)
    for outer, holes, attrs, interior in plans:
        f = mesh.add_face(outer, holes or None)
        f.attrs.update(attrs)
        f.interior = interior
    mesh._chunk_dirty = True
    mesh._mut_serial += 1
    return True


def resegment(mesh, shape: CurveShape, n: int) -> bool:
    """Rebuild the curve with ``n`` segments in ``mesh``. Returns ``False``
    (and leaves the mesh alone) when it cannot."""
    n = int(n)
    if n < shape.minimum or n == shape.segments or not shape.flat:
        return False
    return _rebuild(mesh, shape, shape.points(n))


def _rescale_nonflat_circle(mesh, shape: CurveShape, new_pts) -> bool:
    """Move the rim and its connected geometry without changing edge counts."""
    from core.mesh import Face
    from core.topology import (defects_near, fold_nonplanar_faces,
                               is_planar, loop_inside_face, new_defects, _key,
                               _loops_cross_2d)
    from core.triangulate import plane_axes

    vertices = shape.verts
    moving = set(vertices)
    target_keys = {_key(p) for p in new_pts}
    if (len(target_keys) != len(new_pts)
            or any(_key(v.position) in target_keys
                   for v in mesh.vertices if v not in moving)):
        return False
    affected = {f for v in vertices for f in v.faces()}
    before_defects = defects_near(vertices)
    before = mesh.capture_state()
    for vertex, point in zip(vertices, new_pts):
        mesh.place_vertex(vertex, point)

    for face in affected:
        if not face.hole_loops:
            continue
        u, v = plane_axes(face.normal())
        origin = face.vertices[0]

        def project(p):
            p = p - origin
            return (QVector3D.dotProduct(p, u), QVector3D.dotProduct(p, v))

        outer = [project(p) for p in face.vertices]
        for hole in face.hole_loops:
            other_holes = [h for h in face.hole_loops if h is not hole]
            boundary = Face(face.loop, other_holes)
            points = [v.position for v in hole]
            if (not loop_inside_face(boundary, points, outside_holes=True)
                    or _loops_cross_2d(outer, [project(p) for p in points])):
                mesh.restore_state(before)
                return False

    fold_nonplanar_faces(mesh, moved=target_keys, faces=affected)
    if (new_defects(before_defects, defects_near(vertices))
            or any(not is_planar(f.vertices + [p for h in f.holes for p in h])
                   for f in affected if f in mesh.faces)):
        mesh.restore_state(before)
        return False
    return True


def rescale_radius(mesh, shape: CurveShape, new_radius: float) -> bool:
    """Rebuild the curve at ``new_radius`` (metres) in ``mesh``. Returns
    ``False`` (and leaves the mesh alone) when the operation is invalid."""
    new_radius = float(new_radius)
    if (not math.isfinite(new_radius) or new_radius <= 0
            or new_radius == shape.radius):
        return False
    new_pts = shape.points_at_radius(new_radius)
    if new_pts is None:
        return False
    if not shape.flat:
        return (shape.closed
                and _rescale_nonflat_circle(mesh, shape, new_pts))
    return _rebuild(mesh, shape, new_pts)


class ResegmentCurveCommand(Command):
    """Entity Info's segment count: rebuild one curve, one undo step. The
    curve stays selected either way, so the field keeps showing it."""

    def __init__(self, edge, n: int) -> None:
        self.edge = edge
        self.n = int(n)
        self.cid = getattr(edge, "curve", None)

        def mutate(scene) -> None:
            shape = read_curve(scene.mesh, self.edge)
            if shape is None or not resegment(scene.mesh, shape, self.n):
                raise CommandRejected("curve cannot be rebuilt")
        self._inner = SnapshotMutation(mutate)

    def _select(self, scene) -> None:
        scene.selection.clear()
        for e in scene.mesh.edges:
            if e.curve == self.cid:
                scene.selection.add(e)

    def do(self, scene) -> None:
        self._inner.do(scene)
        self._select(scene)

    def undo(self, scene) -> None:
        self._inner.undo(scene)
        self._select(scene)


class RescaleCurveRadiusCommand(Command):
    """Entity Info's radius field: rebuild one circle, arc or polygon at a new
    radius, one undo step. The curve stays selected either way."""

    def __init__(self, edge, radius: float) -> None:
        self.edge = edge
        self.radius = float(radius)
        self.cid = getattr(edge, "curve", None)

        def mutate(scene) -> None:
            shape = read_curve(scene.mesh, self.edge)
            if shape is None or not rescale_radius(scene.mesh, shape,
                                                   self.radius):
                raise CommandRejected("curve cannot be rescaled")
        self._inner = SnapshotMutation(mutate)

    def _select(self, scene) -> None:
        scene.selection.clear()
        for e in scene.mesh.edges:
            if e.curve == self.cid:
                scene.selection.add(e)

    def do(self, scene) -> None:
        self._inner.do(scene)
        self._select(scene)

    def undo(self, scene) -> None:
        self._inner.undo(scene)
        self._select(scene)
