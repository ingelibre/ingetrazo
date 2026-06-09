"""Planar arrangement: rebuild the minimal faces of a plane from its edges.

Given a tangle of segments lying in one plane (hand-drawn walls, slivers,
crossings, T-junctions, doubled lines), recompute the *minimal bounded faces* —
the robust, deterministic replacement for the heuristic heal pass.

Classic DCEL face extraction:

1. Project the segments to the plane's 2D coordinates.
2. Split every segment at its intersections / overlaps with the others, snapping
   endpoints to a quantised grid so coincident points become one vertex.
3. Prune dangling (degree-1) chains — they border no face.
4. At each vertex, sort the outgoing half-edges by angle; trace each face by
   always taking the *next edge clockwise* (interior kept on the left), which
   yields bounded faces wound CCW and the unbounded face wound CW.
5. Keep the CCW cycles as faces; nest each CW cycle (a hole) inside the smallest
   CCW face that contains it; drop the one CW cycle that contains everything
   (the unbounded outer face).

The result is returned in 3D as ``(outer_loop, [hole_loops])`` per face, ready to
hand to ``AddFaceCommand``. Self-overlapping pathologies aside, this is exact for
the room/notch/hole geometry a floor plan is made of.
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtGui import QVector3D

# Position quantisation (~0.1 mm at metre scale) — coincident points within this
# collapse to one vertex, matching the rest of the engine's welding tolerance.
_TOL = 1e-4
_EPS = 1e-7
# Perpendicular slack for "point lies on segment".
_ON_SEG = 1e-4


def _key(x: float, y: float) -> tuple[int, int]:
    return (round(x / _TOL), round(y / _TOL))


def plane_basis(normal: QVector3D) -> tuple[QVector3D, QVector3D]:
    """Two orthonormal in-plane axes for ``normal`` (stable choice of reference)."""
    n = normal.normalized()
    ref = QVector3D(1.0, 0.0, 0.0)
    if abs(QVector3D.dotProduct(ref, n)) > 0.9:
        ref = QVector3D(0.0, 1.0, 0.0)
    u = (ref - n * QVector3D.dotProduct(ref, n)).normalized()
    v = QVector3D.crossProduct(n, u).normalized()
    return u, v


# ---- 2D geometry helpers ---------------------------------------------------

def _on_seg(p, a, b) -> Optional[float]:
    """Parameter ``t`` of ``p`` on segment ``a``–``b`` (clamped to [0,1]) if it
    lies on it within ``_ON_SEG``, else ``None``."""
    abx, aby = b[0] - a[0], b[1] - a[1]
    l2 = abx * abx + aby * aby
    if l2 < 1e-12:
        return None
    t = ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / l2
    px, py = a[0] + t * abx, a[1] + t * aby
    if (p[0] - px) ** 2 + (p[1] - py) ** 2 > _ON_SEG * _ON_SEG:
        return None
    if t < -_EPS or t > 1.0 + _EPS:
        return None
    return min(1.0, max(0.0, t))


def _intersections(a, b, c, d) -> list:
    """All meeting points of segments ``a``–``b`` and ``c``–``d``: the proper
    crossing, or the overlap endpoints when collinear."""
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    rxs = rx * sy - ry * sx
    qpx, qpy = c[0] - a[0], c[1] - a[1]
    pts = []
    if abs(rxs) > 1e-9:
        t = (qpx * sy - qpy * sx) / rxs
        u = (qpx * ry - qpy * rx) / rxs
        if -_EPS <= t <= 1.0 + _EPS and -_EPS <= u <= 1.0 + _EPS:
            pts.append((a[0] + t * rx, a[1] + t * ry))
    elif abs(qpx * ry - qpy * rx) < 1e-9:  # collinear
        for p in (c, d):
            if _on_seg(p, a, b) is not None:
                pts.append(p)
        for p in (a, b):
            if _on_seg(p, c, d) is not None:
                pts.append(p)
    return pts


def _signed_area(loop: list) -> float:
    s = 0.0
    n = len(loop)
    for i in range(n):
        x0, y0 = loop[i]
        x1, y1 = loop[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s * 0.5


def _point_in_polygon(p, poly: list) -> bool:
    """Ray-cast even-odd test; ``poly`` is a list of (x, y)."""
    x, y = p
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi
        ):
            inside = not inside
        j = i
    return inside


# ---- Arrangement -----------------------------------------------------------

def _build_graph(segments_2d):
    """Split all segments at intersections and return ``(coords, adjacency)``:
    ``coords`` maps a vertex key to its (x, y); ``adjacency`` maps a key to the
    set of neighbour keys (undirected, deduplicated, no self-loops)."""
    n = len(segments_2d)
    split_pts = [list(seg) for seg in segments_2d]  # seed with endpoints
    for i in range(n):
        a, b = segments_2d[i]
        for j in range(n):
            if i == j:
                continue
            c, d = segments_2d[j]
            for p in _intersections(a, b, c, d):
                if _on_seg(p, a, b) is not None:
                    split_pts[i].append(p)

    coords: dict = {}
    adj: dict = {}

    def vert(p):
        k = _key(p[0], p[1])
        if k not in coords:
            coords[k] = (p[0], p[1])
            adj[k] = set()
        return k

    for i in range(n):
        a, b = segments_2d[i]
        pts = split_pts[i]
        pts.sort(key=lambda p: _on_seg(p, a, b) or 0.0)
        for k in range(len(pts) - 1):
            ka, kb = vert(pts[k]), vert(pts[k + 1])
            if ka != kb:
                adj[ka].add(kb)
                adj[kb].add(ka)
    return coords, adj


def _prune_dangling(adj):
    """Iteratively drop degree-1 vertices (and their edges): a dangling chain
    borders no face, so it must not appear in a traced loop."""
    changed = True
    while changed:
        changed = False
        for k in list(adj.keys()):
            if len(adj[k]) == 1:
                (other,) = tuple(adj[k])
                adj[other].discard(k)
                del adj[k]
                changed = True
            elif len(adj[k]) == 0:
                del adj[k]
                changed = True


def _trace_faces(coords, adj) -> list:
    """Trace every face as a vertex-key loop via the next-edge-clockwise rule.
    Bounded faces come out CCW; the unbounded face comes out CW."""
    # Sort each vertex's neighbours by angle (ascending).
    order: dict = {}
    for k, nbrs in adj.items():
        kx, ky = coords[k]
        order[k] = sorted(
            nbrs, key=lambda m: math.atan2(coords[m][1] - ky, coords[m][0] - kx)
        )

    def next_he(u, v):
        # Arriving at v from u: take the neighbour of v just clockwise from u.
        ring = order[v]
        idx = ring.index(u)
        return ring[idx - 1]  # previous in CCW-sorted == clockwise next

    visited: set = set()
    loops = []
    for u in adj:
        for v in adj[u]:
            if (u, v) in visited:
                continue
            loop = []
            cu, cv = u, v
            while (cu, cv) not in visited:
                visited.add((cu, cv))
                loop.append(cu)
                cu, cv = cv, next_he(cu, cv)
                if len(loop) > 100000:  # pathological guard
                    break
            if len(loop) >= 3:
                loops.append(loop)
    return loops


def _arrange(segments_3d, origin, normal):
    """Shared core: project, split, and trace. Returns
    ``(coords, full_adj, faces_xy, to3d)`` where ``full_adj`` is the split edge
    graph *before* dangling pruning and ``faces_xy`` is ``[(outer, [holes])]`` in
    plane coords. ``coords``/``faces_xy`` are empty when there's nothing to do."""
    u, v = plane_basis(normal)

    def to2d(p):
        d = p - origin
        return (QVector3D.dotProduct(d, u), QVector3D.dotProduct(d, v))

    def to3d(xy):
        return origin + u * xy[0] + v * xy[1]

    segs = []
    for a, b in segments_3d:
        pa, pb = to2d(a), to2d(b)
        if (pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2 > _TOL * _TOL:
            segs.append((pa, pb))
    if not segs:
        return {}, {}, [], to3d

    coords, full_adj = _build_graph(segs)
    adj = {k: set(ns) for k, ns in full_adj.items()}  # copy; prune the copy
    _prune_dangling(adj)
    loops = _trace_faces(coords, adj)
    faces_xy = _classify(loops, coords)
    return coords, full_adj, faces_xy, to3d


def _classify(loops, coords) -> list:

    # Split into CCW faces and CW cycles (holes / the unbounded outer).
    faces = []   # (loop_xy, area)
    holes = []   # (loop_xy, area)
    for loop in loops:
        xy = [coords[k] for k in loop]
        area = _signed_area(xy)
        if area > _TOL:
            faces.append((xy, area))
        elif area < -_TOL:
            holes.append((xy, -area))

    if not faces:
        return []

    # The unbounded outer face is the CW cycle that encloses everything — the
    # one with the largest magnitude. Drop it; the rest are real holes.
    if holes:
        holes.sort(key=lambda h: h[1], reverse=True)
        holes = holes[1:]  # discard the all-enclosing outer

    # Nest each hole inside the smallest face that *strictly* contains it. The
    # area guard skips the face the hole coincides with (the inner square that
    # fills the opening) so the hole lands on the surrounding ring instead.
    faces.sort(key=lambda f: f[1])  # smallest first
    face_holes: list = [[] for _ in faces]
    for hxy, harea in holes:
        hp = _interior_point(hxy)
        for fi, (fxy, farea) in enumerate(faces):
            if farea > harea + _TOL and _point_in_polygon(hp, fxy):
                face_holes[fi].append(hxy)
                break

    return [(fxy, hls) for (fxy, _a), hls in zip(faces, face_holes)]


def planar_arrangement(segments_3d, origin: QVector3D, normal: QVector3D) -> list:
    """Rebuild minimal faces from coplanar ``segments_3d`` (list of
    ``(QVector3D, QVector3D)``). Returns ``[(outer_loop, [hole_loops]), …]`` with
    every loop a list of ``QVector3D`` on the plane."""
    _coords, _adj, faces_xy, to3d = _arrange(segments_3d, origin, normal)
    return [
        ([to3d(p) for p in outer], [[to3d(p) for p in h] for h in holes])
        for outer, holes in faces_xy
    ]


def planar_rebuild(segments_3d, origin: QVector3D, normal: QVector3D):
    """Full planar rebuild: returns ``(edges_3d, faces_3d)`` where ``edges_3d`` is
    the complete split edge set (so nothing is lost, including spurs) and
    ``faces_3d`` is ``[(outer, [holes])]`` — exactly what the command re-adds."""
    coords, full_adj, faces_xy, to3d = _arrange(segments_3d, origin, normal)
    edges = []
    seen = set()
    for k, nbrs in full_adj.items():
        for m in nbrs:
            key = frozenset((k, m))
            if key in seen:
                continue
            seen.add(key)
            edges.append((to3d(coords[k]), to3d(coords[m])))
    faces = [
        ([to3d(p) for p in outer], [[to3d(p) for p in h] for h in holes])
        for outer, holes in faces_xy
    ]
    return edges, faces


def coplanar_plane(points, tol: float = 1e-4):
    """``(origin, normal)`` of the plane through ``points`` (a list of
    ``QVector3D``) if they're all coplanar, else ``None``. Collinear or
    degenerate input returns a horizontal plane (the arrangement then yields no
    face), so the caller can still run safely."""
    pts = list(points)
    if len(pts) < 3:
        return (pts[0] if pts else QVector3D(0, 0, 0), QVector3D(0, 0, 1))
    o = pts[0]
    d1 = None
    for p in pts[1:]:
        if (p - o).length() > 1e-6:
            d1 = (p - o).normalized()
            break
    if d1 is None:
        return (o, QVector3D(0, 0, 1))
    n = None
    for p in pts[1:]:
        c = QVector3D.crossProduct(d1, p - o)
        if c.length() > 1e-6:
            n = c.normalized()
            break
    if n is None:  # all collinear — pick any plane containing the line
        return (o, QVector3D(0, 0, 1))
    for p in pts:
        if abs(QVector3D.dotProduct(n, p - o)) > tol:
            return None  # not coplanar
    return (o, n)


def _interior_point(loop: list):
    """A point safely inside the polygon ``loop`` (average of a triangle fan
    vertex that tests inside), good enough for containment nesting."""
    n = len(loop)
    cx = sum(p[0] for p in loop) / n
    cy = sum(p[1] for p in loop) / n
    if _point_in_polygon((cx, cy), loop):
        return (cx, cy)
    # Centroid outside (non-convex) — nudge from the first edge's midpoint inward.
    ax, ay = loop[0]
    bx, by = loop[1]
    mx, my = (ax + bx) / 2, (ay + by) / 2
    return (mx * 0.999 + cx * 0.001, my * 0.999 + cy * 0.001)
