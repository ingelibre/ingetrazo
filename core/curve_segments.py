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
joined to stays joined. Only a flat curve qualifies — one whose faces all
lie in its own plane; the rim of a pushed cylinder also drives its side
faces, which this does not rebuild.
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


def resegment(mesh, shape: CurveShape, n: int) -> bool:
    """Rebuild the curve with ``n`` segments in ``mesh``. Returns ``False``
    (and leaves the mesh alone) when it cannot."""
    from core.mesh import edge_flags, stamp_edge_flags
    n = int(n)
    if n < shape.minimum or n == shape.segments or not shape.flat:
        return False
    new_pts = shape.points(n)
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
