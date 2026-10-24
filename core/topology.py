# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Topology helpers — graph queries over the scene's edge network.

Used by tools (today: ``LineTool``) to find polygons that close when a new
edge is added. Modeled after the classic behaviour: as soon as a new edge
completes a planar cycle in the edge graph — using any combination of
existing edges — that cycle becomes a face automatically.

Position equality is tolerant: two vertices within ``_KEY_DECIMALS``
decimal places (≈ 0.1 mm at metric scale) are treated as the same node.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Iterable, Optional

from PySide6.QtGui import QVector3D

from core.geometry import Edge, Face


_KEY_DECIMALS = 4
_PLANAR_TOLERANCE = 1e-3
# Two points closer than this weld together; also the gate for deciding a
# crossing is real (skew lines whose closest approach exceeds it don't touch).
_SPLIT_TOLERANCE = 1e-4


def _key(p: QVector3D) -> tuple[float, float, float]:
    return (round(p.x(), _KEY_DECIMALS),
            round(p.y(), _KEY_DECIMALS),
            round(p.z(), _KEY_DECIMALS))


class KeyMemo:
    """``_key`` memoised per point OBJECT for the length of one scan. A push
    on a 25 797-face group called ``_key`` 655 000 times (2 M ``round``) —
    each vertex once per face and edge it belongs to. Only for a scan that
    moves nothing: a position mutated in place keeps its object."""

    __slots__ = ("_seen",)

    def __init__(self) -> None:
        self._seen: dict = {}

    def __call__(self, p: QVector3D) -> tuple:
        hit = self._seen.get(id(p))
        if hit is not None and hit[0] is p:
            return hit[1]
        k = _key(p)
        self._seen[id(p)] = (p, k)
        return k


def same_position(p: QVector3D, q: QVector3D) -> bool:
    """Whether two points coincide within the welding tolerance (≈ 0.1 mm)."""
    return _key(p) == _key(q)


def find_duplicate_edge(
    edges: Iterable[Edge], a: QVector3D, b: QVector3D
) -> Optional[Edge]:
    """Return an existing edge whose endpoints coincide with segment ``a``–``b``.

    Orientation-independent: an edge stored as ``b``–``a`` still matches.
    Coincidence uses the same tolerant position key as the cycle finder, so
    two endpoints within ≈ 0.1 mm weld to the same node. A degenerate
    (zero-length) query never matches. Returns ``None`` if no duplicate
    exists. This is the primitive behind the classic auto-merge: drawing
    an edge that already exists reuses it instead of stacking a duplicate.
    """
    ka, kb = _key(a), _key(b)
    if ka == kb:
        return None
    target = frozenset((ka, kb))
    for edge in edges:
        ea, eb = _key(edge.a), _key(edge.b)
        if ea == eb:
            continue
        if frozenset((ea, eb)) == target:
            return edge
    return None


def find_smallest_cycle_through(
    edges: Iterable[Edge],
    a: QVector3D,
    b: QVector3D,
    max_len: int = 32,
) -> Optional[list[QVector3D]]:
    """Smallest simple cycle in the edge graph that contains segment ``a-b``.

    The segment is *virtual*: it does not need to exist in ``edges`` yet.
    Returns the cycle as an ordered list of vertices starting at ``a`` and
    walking back to ``b`` through existing edges (so the full polygon loop
    is the returned list with the implicit closing segment back to ``a``).
    Returns ``None`` if no cycle exists or it would exceed ``max_len`` nodes.
    """
    ka, kb = _key(a), _key(b)
    if ka == kb:
        return None
    return _smallest_cycle(_cycle_adjacency(edges, ka, kb), a, b, ka, kb,
                           max_len)


def _cycle_adjacency(edges, ka, kb, key=_key) -> dict:
    """``adj[u] -> [(v_key, v_pos), …]`` of the edge graph, in edge order,
    without an existing copy of segment ``ka``–``kb`` (the cycle would just
    find itself, a length-2 loop a→b→a)."""
    adj: dict[tuple, list[tuple[tuple, QVector3D]]] = {}
    for edge in edges:
        ea, eb = key(edge.a), key(edge.b)
        if ea == eb:
            continue
        if {ea, eb} == {ka, kb}:
            continue
        adj.setdefault(ea, []).append((eb, edge.b))
        adj.setdefault(eb, []).append((ea, edge.a))
    return adj


def _smallest_cycle(adj, a, b, ka, kb, max_len: int = 32,
                    skip=frozenset()):
    """Breadth-first search from ``b`` to ``a`` over ``adj``, never entering a
    node of ``skip`` — the same search ``adj`` built without the edges that
    touch those nodes would make (adjacency lists keep the edge order)."""
    if ka not in adj or kb not in adj:
        return None
    if skip and not (any(v not in skip for v, _p in adj[ka])
                     and any(v not in skip for v, _p in adj[kb])):
        return None             # an end with no edge left once ``skip`` goes

    parent: dict = {kb: None}
    parent_pos: dict = {kb: b}
    q = deque([kb])
    found = False
    while q:
        u = q.popleft()
        if u == ka:
            found = True
            break
        for v_key, v_pos in adj.get(u, ()):
            if v_key not in parent and v_key not in skip:
                parent[v_key] = u
                parent_pos[v_key] = v_pos
                q.append(v_key)

    if not found:
        return None

    path: list[QVector3D] = []
    cur = ka
    while cur is not None:
        path.append(parent_pos[cur])
        cur = parent[cur]
    # path is [a, ..., b]. Cycle = path + implicit closing a–b.
    if len(path) < 3 or len(path) > max_len:
        return None
    return path


def is_planar(vertices: list[QVector3D], tolerance: float = _PLANAR_TOLERANCE) -> bool:
    """Whether ``vertices`` all lie on a common plane within ``tolerance``."""
    n = len(vertices)
    if n < 3:
        return False
    if n == 3:
        # Any 3 distinct points are coplanar by definition. Reject degenerate
        # (collinear) triangles so we don't try to face them.
        e1 = vertices[1] - vertices[0]
        e2 = vertices[2] - vertices[0]
        return QVector3D.crossProduct(e1, e2).length() > 1e-6

    # The plane is the one through the first vertex and the two that span
    # the widest triangle with it, worked out in double precision. It used
    # to be the first pair whose cross product passed 1e-6 — on a circle,
    # two neighbours nearly in line — in single precision, so the plane
    # tilted with the distance from the origin and at 1000 m a third of
    # flat tilted circles came out "not planar" (#571). Measuring against
    # a plane through real vertices, and not a best-fit one, keeps what is
    # refused: a best fit would share a corner lifted 1.5 mm out as
    # ±0.4 mm and call the warped quad flat.
    pts = [(v.x(), v.y(), v.z()) for v in vertices]
    ax, ay, az = pts[0]
    rel = [(x - ax, y - ay, z - az) for x, y, z in pts]
    ux, uy, uz = max(rel, key=lambda p: p[0] * p[0] + p[1] * p[1] + p[2] * p[2])
    nx = ny = nz = 0.0
    best = 0.0
    for vx, vy, vz in rel:
        cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        size = cx * cx + cy * cy + cz * cz
        if size > best:
            best, nx, ny, nz = size, cx, cy, cz
    length = math.sqrt(best)
    if length <= 1e-6:
        return False                      # every vertex in one line
    nx, ny, nz = nx / length, ny / length, nz / length
    return all(abs(nx * x + ny * y + nz * z) <= tolerance for x, y, z in rel)


def segment_intersection(
    p1: QVector3D,
    p2: QVector3D,
    p3: QVector3D,
    p4: QVector3D,
    tol: float = _SPLIT_TOLERANCE,
) -> Optional[QVector3D]:
    """Where segment ``p1-p2`` meets segment ``p3-p4`` in 3D, or ``None``.

    Uses the closest-points-between-two-lines solution and accepts the hit
    only when (a) the lines are not parallel, (b) their closest approach is
    within ``tol`` (so genuinely skew segments that merely *look* crossed in
    a 2D projection are rejected), and (c) both parameters land on their
    segment (endpoints included). The returned point is the midpoint of the
    closest approach, so an X-crossing yields one shared vertex for both
    edges. Collinear overlaps return ``None`` — those are a merge problem,
    handled separately, not a crossing.
    """
    d1 = p2 - p1
    d2 = p4 - p3
    len1 = d1.length()
    len2 = d2.length()
    if len1 < tol or len2 < tol:
        return None

    # Solve with unit directions. Guide lines are represented as segments of
    # +/- 10 km; using the raw vectors makes ``a*c - b*b`` subtract values
    # around 1e17 in float32 and loses the determinant for ordinary crossings.
    # Keeping the direction products near one avoids that cancellation while
    # preserving the segment parameters below in world units.
    components = lambda vector: (float(vector.x()), float(vector.y()),
                                 float(vector.z()))
    d1c = components(d1)
    d2c = components(d2)
    u1 = tuple(component / len1 for component in d1c)
    u2 = tuple(component / len2 for component in d2c)
    dot = lambda left, right: sum(left[i] * right[i] for i in range(3))
    a = dot(u1, u1)
    b = dot(u1, u2)
    c = dot(u2, u2)
    w0 = p1 - p3
    w = components(w0)
    d = dot(u1, w)
    e = dot(u2, w)
    denom = a * c - b * b
    if denom < 1e-12:
        return None  # parallel or collinear

    s = (b * e - c * d) / denom
    t = (a * e - b * d) / denom

    # Allow a hair past the endpoints (proportional to length) so a touch
    # exactly at a vertex still registers; same_position decides interior
    # vs endpoint later.
    margin1 = tol / len1
    margin2 = tol / len2
    if not (-margin1 <= s / len1 <= 1.0 + margin1):
        return None
    if not (-margin2 <= t / len2 <= 1.0 + margin2):
        return None

    p1c = components(p1)
    p3c = components(p3)
    point_on_1 = tuple(p1c[i] + u1[i] * s for i in range(3))
    point_on_2 = tuple(p3c[i] + u2[i] * t for i in range(3))
    gap = sum((point_on_1[i] - point_on_2[i]) ** 2 for i in range(3)) ** 0.5
    # QVector3D stores endpoints as float32. Long guide segments therefore
    # carry a small, length-dependent rounding error after normalization.
    distance_tol = max(tol, 1.0e-7 * max(len1, len2))
    if gap > distance_tol:
        return None  # skew: lines pass without meeting
    return QVector3D(*((point_on_1[i] + point_on_2[i]) * 0.5
                       for i in range(3)))


def _order_along(a: QVector3D, b: QVector3D, points: list[QVector3D]) -> list[QVector3D]:
    """Deduplicate ``points`` and order them by their projection along a→b,
    dropping any that coincide with an endpoint.

    Coincidence is by real distance, not the rounded ``same_position`` key —
    two points can sit 1e-5 apart yet straddle a rounding cell, and a chain
    piece that short welds to a degenerate edge downstream."""
    d = b - a
    uniq: list[QVector3D] = []
    for p in points:
        if (p - a).length() <= _SPLIT_TOLERANCE or (p - b).length() <= _SPLIT_TOLERANCE:
            continue
        if not any((p - q).length() <= _SPLIT_TOLERANCE for q in uniq):
            uniq.append(p)
    uniq.sort(key=lambda p: QVector3D.dotProduct(p - a, d))
    return uniq


def plan_edge_split(
    edges: Iterable[Edge], a: QVector3D, b: QVector3D
) -> tuple[list[tuple[QVector3D, QVector3D]], dict[Edge, QVector3D]]:
    """Plan the splits caused by adding segment ``a-b`` to ``edges``.

    Returns a pair:

    - ``new_segments`` — the new edge broken at every interior crossing,
      ordered from ``a`` to ``b`` (just ``[(a, b)]`` when nothing is crossed);
    - ``edge_cuts`` — existing edge → the interior point where the new edge
      crosses it (those edges must be replaced by two sub-edges).

    A crossing at a shared *endpoint* produces no split on that side (the
    weld already shares that vertex). A straight segment meets another at
    most once, so each existing edge maps to a single cut point.
    """
    new_cuts: list[QVector3D] = []
    edge_cuts: dict[Edge, QVector3D] = {}
    for e in edges:
        point = segment_intersection(a, b, e.a, e.b)
        if point is None:
            continue
        # Snap a graze to the vertex it grazes. A float32 tangency (circle
        # vertex snapped onto an edge endpoint) lands the crossing a hair past
        # the vertex; the rounded ``same_position`` key can miss the pair when
        # it straddles a rounding cell, and the resulting sub-weld split plans
        # an edge the mesh rejects as degenerate. Distance-based on purpose.
        for anchor in (e.a, e.b, a, b):
            if (point - anchor).length() <= _SPLIT_TOLERANCE:
                point = anchor
                break
        if not (same_position(point, a) or same_position(point, b)):
            new_cuts.append(point)
        if not (same_position(point, e.a) or same_position(point, e.b)):
            edge_cuts[e] = point

    ordered = _order_along(a, b, new_cuts)
    chain = [a, *ordered, b]
    new_segments = [(chain[i], chain[i + 1]) for i in range(len(chain) - 1)]
    return new_segments, edge_cuts


def face_exists(faces: Iterable[Face], cycle: list[QVector3D]) -> bool:
    """Whether a face with the same vertex set as ``cycle`` already exists."""
    cycle_keys = frozenset(_key(v) for v in cycle)
    for face in faces:
        if frozenset(_key(v) for v in face.vertices) == cycle_keys:
            return True
    return False


# ---- Containment (face split / hole punching) ------------------------------

def _on_segment_2d(p, a, b, tol: float = 1e-7) -> bool:
    """Whether 2D point ``p`` lies on segment ``a``–``b`` within ``tol``."""
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    if abs(cross) > tol:
        return False
    dot = (p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])
    if dot < -tol:
        return False
    sqlen = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2
    return dot <= sqlen + tol


def _strictly_inside_2d(p, poly: list[tuple[float, float]]) -> bool:
    """Ray-cast point-in-polygon, strict: points on the boundary are *not*
    inside (they signal a shared-edge case, which is a chord split, not a
    hole)."""
    n = len(poly)
    j = n - 1
    inside = False
    for i in range(n):
        if _on_segment_2d(p, poly[i], poly[j]):
            return False
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > p[1]) != (yj > p[1]):
            xint = xi + (xj - xi) * (p[1] - yi) / (yj - yi)
            if p[0] < xint:
                inside = not inside
        j = i
    return inside


def loop_inside_face(mother: Face, loop: list[QVector3D],
                     outside_holes: bool = False) -> bool:
    """Whether ``loop`` lies entirely, strictly inside coplanar face ``mother``.

    Requires the loop to be coplanar with the mother and every loop vertex to
    fall strictly inside the mother's outer polygon (no vertex on its
    boundary). A loop that shares any boundary point is a chord split, handled
    elsewhere, and returns ``False`` here.

    With ``outside_holes`` the mother's holes count as *not hers*: a loop with
    a vertex inside one of her holes is not contained (it belongs to whatever
    face fills that hole — the nested-rectangle case).
    """
    if len(mother.vertices) < 3 or len(loop) < 3:
        return False
    normal = mother.normal()
    origin = mother.vertices[0]
    # Coplanarity: every loop vertex on the mother's plane.
    for v in loop:
        if abs(QVector3D.dotProduct(normal, v - origin)) > _PLANAR_TOLERANCE:
            return False

    from core.triangulate import plane_axes

    u, w = plane_axes(normal)

    def proj(p):
        rel = p - origin
        return (QVector3D.dotProduct(rel, u), QVector3D.dotProduct(rel, w))

    poly2 = [proj(p) for p in mother.vertices]
    if not all(_strictly_inside_2d(proj(v), poly2) for v in loop):
        return False
    if outside_holes:
        loop2 = [proj(v) for v in loop]
        for hole in mother.holes:
            hole2 = [proj(p) for p in hole]
            if any(_strictly_inside_2d(q, hole2) for q in loop2):
                return False
            # A loop that wraps or straddles the hole without a corner in
            # it overlaps the opening all the same; punched as a second hole
            # the two crossed, the face triangulated over its own opening
            # and the next rebuild filled it (#519).
            if (any(_strictly_inside_2d(q, loop2) for q in hole2)
                    or _loops_cross_2d(loop2, hole2)):
                return False
    return True


def _loops_cross_2d(a: list, b: list) -> bool:
    """Whether an edge of polygon ``a`` properly crosses one of ``b``
    (touching at an end or running along it does not count)."""
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    eps = 1e-12
    for i in range(len(a)):
        p1, p2 = a[i], a[(i + 1) % len(a)]
        for j in range(len(b)):
            q1, q2 = b[j], b[(j + 1) % len(b)]
            d1, d2 = side(q1, q2, p1), side(q1, q2, p2)
            d3, d4 = side(p1, p2, q1), side(p1, p2, q2)
            if (((d1 > eps and d2 < -eps) or (d1 < -eps and d2 > eps))
                    and ((d3 > eps and d4 < -eps)
                         or (d3 < -eps and d4 > eps))):
                return True
    return False


def hole_merged_with_loop(face: Face, loop: list[QVector3D]):
    """``(hole_index, merged)`` when ``loop`` — already known to lie inside
    ``face`` — runs along part of one of its holes' rims: the rectangle
    drawn on a ring's top against the opening. That is no second hole (two
    openings sharing an edge triangulate into slivers over both, #489): the
    opening grows to take it in, ``merged`` being its new outline. ``None``
    when the loop shares no stretch of rim with any hole."""
    from core.arrangement import _signed_area
    from core.cap_rebuild import _union_outline
    from core.triangulate import plane_axes

    normal = face.normal()
    origin = face.vertices[0]
    u, w = plane_axes(normal)
    back: dict = {}

    def proj(pts):
        out = []
        for p in pts:
            rel = p - origin
            xy = (QVector3D.dotProduct(rel, u), QVector3D.dotProduct(rel, w))
            back[xy] = QVector3D(p)
            out.append(xy)
        return out

    for idx, hole in enumerate(face.holes):
        h3 = refine_loop_with_points(list(hole), loop)
        l3 = refine_loop_with_points(list(loop), hole)
        shared = set(_loop_edges(h3)) & set(_loop_edges(l3))
        if not shared:
            continue
        rings = []
        for ring in (proj(h3), proj(l3)):
            if _signed_area(ring) < 0:
                ring = ring[::-1]
            rings.append((ring, []))
        merged = _union_outline(rings)
        if len(merged) != 1 or merged[0][1]:
            return None
        return idx, [back[xy] for xy in merged[0][0]]
    return None


def find_containing_face(
    faces: Iterable[Face], loop: list[QVector3D], exclude: Optional[Face] = None
) -> Optional[Face]:
    """Smallest existing face that strictly contains ``loop`` (or ``None``).

    Hole-aware: a loop inside a candidate's *hole* is not contained by it (it
    belongs to the face filling that hole — drawing a rectangle inside an
    already-drawn rectangle must punch the inner face, not the grandmother
    whose hole already excludes the spot). Smallest by vertex count is a
    cheap, good-enough proxy for the immediate mother when faces are nested.
    ``exclude`` skips the face being added.
    """
    best: Optional[Face] = None
    for face in faces:
        if face is exclude:
            continue
        if loop_inside_face(face, loop, outside_holes=True):
            if best is None or len(face.vertices) < len(best.vertices):
                best = face
    return best


def _loop_edges(loop: list[QVector3D]) -> list[frozenset]:
    n = len(loop)
    return [
        frozenset((_key(loop[i]), _key(loop[(i + 1) % n]))) for i in range(n)
    ]


def orphaned_edges_at(
    edges: Iterable[Edge], faces: Iterable[Face], vertices: Iterable[QVector3D]
) -> list[Edge]:
    """Edges incident to any of ``vertices`` that border no face.

    Used after push/pull consumes a face to sweep up the dangling lines left
    where geometry was carved away, without disturbing standalone edges
    elsewhere (only those touching the operation's vertices are considered).
    """
    vkeys = {_key(v) for v in vertices}
    key = KeyMemo()
    face_edges: set = set()
    for f in faces:
        loops = [[key(p) for p in lp] for lp in (f.vertices, *f.holes)]
        # Only an edge with an end in ``vkeys`` is asked about, and a face
        # can only carry it if it has that corner: the others are skipped
        # (exact — every face was walked before).
        if not any(k in vkeys for lk in loops for k in lk):
            continue
        for lk in loops:
            n = len(lk)
            face_edges.update(frozenset((lk[i], lk[(i + 1) % n]))
                              for i in range(n))
    out: list[Edge] = []
    for e in edges:
        ka, kb = key(e.a), key(e.b)
        if (ka in vkeys or kb in vkeys) and frozenset((ka, kb)) not in face_edges:
            out.append(e)
    return out


def _faces_coplanar(n1: QVector3D, n2: QVector3D) -> bool:
    return abs(QVector3D.dotProduct(n1.normalized(), n2.normalized())) > 0.999


def _unit_coplanar(n1: QVector3D, n2: QVector3D) -> bool:
    """``_faces_coplanar`` for normals already known to be unit length —
    ``Face.normal()`` returns one, and re-normalising both sides ran 14.3M
    times inside the heal's O(F^2) passes."""
    return abs(n1.x() * n2.x() + n1.y() * n2.y() + n1.z() * n2.z()) > 0.999


def _face_all_edges(face: Face) -> set:
    edges = set(_loop_edges(face.vertices))
    for hole in face.holes:
        edges.update(_loop_edges(hole))
    return edges


def _point_on_seg_incl(pt: QVector3D, p: QVector3D, q: QVector3D,
                       tol: float = _SPLIT_TOLERANCE) -> bool:
    """Whether ``pt`` lies on segment ``p``–``q``, endpoints included."""
    pq = q - p
    length = pq.length()
    if length < tol:
        return same_position(pt, p)
    t = QVector3D.dotProduct(pt - p, pq) / (length * length)
    if t < -tol or t > 1.0 + tol:
        return False
    return (pt - (p + pq * t)).length() < tol


def _segment_on_face_boundary(a: QVector3D, b: QVector3D, face: Face) -> bool:
    """Whether segment ``a``–``b`` lies on a boundary edge of ``face`` (a
    possibly-shorter sub-segment of one of its edges).

    Checks the outer loop *and* every hole: a face stacked on another sits with
    its base edges on the host's *hole* boundary (the opening the stack punched),
    so a perpendicular neighbour must be found there too — otherwise pushing the
    stack's side wall is misread as a free extrusion."""
    for loop in (face.vertices, *face.holes):
        n = len(loop)
        for i in range(n):
            p = loop[i]
            q = loop[(i + 1) % n]
            if _point_on_seg_incl(a, p, q) and _point_on_seg_incl(b, p, q):
                return True
    return False


def refine_loop_with_points(
    loop: list[QVector3D], points: Iterable[QVector3D], tol: float = _SPLIT_TOLERANCE
) -> list[QVector3D]:
    """Insert any ``points`` that lie on an edge's interior into ``loop``.

    A pushed wall whose edge runs along a *T-junction* — where the host wall ends
    and an earlier overhang's floor begins — has that edge covered piecewise by
    two faces, but no single one, so it reads as ``free``. Splitting the edge at
    the existing vertices sitting on it makes each sub-segment carried by one
    face, so push/pull classifies (and consumes) it correctly. Returns a new loop
    with the collinear points inserted in order; the originals are untouched."""
    import numpy as np
    out: list[QVector3D] = []
    n = len(loop)
    pts = list(points)
    # A point on a segment's interior lies inside its box (grown by the
    # tolerance): only those reach the exact test below, in their order. The
    # pushed face's loop against every vertex of a 25 797-face group was
    # ~80 000 same_position calls per push (09-10).
    xyz = (np.array([(p.x(), p.y(), p.z()) for p in pts], dtype=np.float64)
           if pts else np.zeros((0, 3)))
    for i in range(n):
        a = loop[i]
        b = loop[(i + 1) % n]
        out.append(a)
        ab = b - a
        length = ab.length()
        if length < tol:
            continue
        g = 2.0 * tol + 1e-6 * max(abs(a.x()), abs(a.y()), abs(a.z()),
                                   abs(b.x()), abs(b.y()), abs(b.z()))
        lo = np.array([min(a.x(), b.x()), min(a.y(), b.y()),
                       min(a.z(), b.z())]) - g
        hi = np.array([max(a.x(), b.x()), max(a.y(), b.y()),
                       max(a.z(), b.z())]) + g
        near = np.flatnonzero(((xyz >= lo) & (xyz <= hi)).all(axis=1))
        on: list[tuple[float, QVector3D]] = []
        for j in near:
            p = pts[j]
            if same_position(p, a) or same_position(p, b):
                continue
            t = QVector3D.dotProduct(p - a, ab) / (length * length)
            if t <= tol / length or t >= 1.0 - tol / length:
                continue
            if (p - (a + ab * t)).length() < tol:
                on.append((t, p))
        on.sort(key=lambda it: it[0])
        for _, p in on:
            out.append(QVector3D(p))
    return out


def classify_push_edge(
    face: Face, a: QVector3D, b: QVector3D, faces: Iterable[Face]
) -> tuple[str, Optional[Face]]:
    """How a push/pull side edge ``a``–``b`` of ``face`` attaches to the model.

    - ``("coplanar", g)`` — a face on the same plane shares this edge (its
      boundary or a hole); the push raises an inner wall here.
    - ``("perp", s)`` — a non-coplanar face carries this edge on its boundary
      (the solid's side wall); pushing in notches that wall.
    - ``("free", None)`` — nothing adjacent; a free extrusion edge.

    A coplanar neighbour is matched even when it carries the edge only as a
    *sub-segment* of a wider boundary edge (its own edge was never split at this
    vertex — the colinear-overlap case). Without this, a block flush against a
    wider wall reads its shared edge as ``free`` and the push becomes a stray
    free extrusion that leaves the base as an internal partition.
    """
    fn = face.normal()
    eset = frozenset((_key(a), _key(b)))
    faces = list(faces)
    for g in faces:
        if g is face:
            continue
        if _faces_coplanar(fn, g.normal()) and (
            eset in _face_all_edges(g) or _segment_on_face_boundary(a, b, g)
        ):
            return ("coplanar", g)
    for s in faces:
        if s is face or _faces_coplanar(fn, s.normal()):
            continue
        if _segment_on_face_boundary(a, b, s):
            return ("perp", s)
    return ("free", None)


def face_is_bordered(face: Face, faces: Iterable[Face]) -> bool:
    """Whether every boundary edge of ``face`` is also an edge of some other
    face (its boundary or a hole).

    A bordered face is embedded in a surface or solid — a cube's top, or a
    rectangle drawn inside another face — so push/pull *moves* it and the base
    is consumed (carving a recess, or extending/shortening a solid without
    leaving an internal cap). A free-standing face (free edges) is *extruded*,
    keeping the base as a cap. This is orientation-independent, so it works
    regardless of how the face happens to be wound.
    """
    base_edges = _loop_edges(face.vertices)
    if not base_edges:
        return False
    others: set = set()
    for f in faces:
        if f is face:
            continue
        others.update(_loop_edges(f.vertices))
        for hole in f.holes:
            others.update(_loop_edges(hole))
    return all(e in others for e in base_edges)


# ---- Chord split (a new edge divides an existing face) ---------------------

def _point_on_segment_3d(
    p: QVector3D, a: QVector3D, b: QVector3D, tol: float = _SPLIT_TOLERANCE
) -> bool:
    """Whether ``p`` lies on the *interior* of segment ``a``–``b`` (endpoints
    excluded — those are handled as vertex hits)."""
    ab = b - a
    length = ab.length()
    if length < tol:
        return False
    t = QVector3D.dotProduct(p - a, ab) / (length * length)
    if t < tol or t > 1.0 - tol:
        return False
    return (p - (a + ab * t)).length() < tol


def _locate_on_loop(vertices: list[QVector3D], p: QVector3D):
    """Where ``p`` sits on a face's boundary loop: ``("vertex", i)`` if it is
    vertex ``i``; ``("edge", i)`` if it lies on edge ``i → i+1``; else ``None``."""
    kp = _key(p)
    for i, v in enumerate(vertices):
        if _key(v) == kp:
            return ("vertex", i)
    n = len(vertices)
    for i in range(n):
        if _point_on_segment_3d(p, vertices[i], vertices[(i + 1) % n]):
            return ("edge", i)
    return None


def split_face_by_chord(
    face: Face, a: QVector3D, b: QVector3D
) -> Optional[tuple[list[QVector3D], list[QVector3D]]]:
    """If segment ``a``–``b`` is a chord of ``face`` (both ends on its
    boundary, the segment running through its interior), return the two
    sub-loops it divides the face into; otherwise ``None``.

    Handles ends that are existing vertices *or* points on a boundary edge
    (the latter get inserted into the loop). Faces with holes are skipped —
    chord-splitting a holed face is a harder case left for later. The two
    returned loops inherit the mother's winding, so neither comes out
    inverted.
    """
    if face.holes or len(face.vertices) < 3:
        return None
    la = _locate_on_loop(face.vertices, a)
    lb = _locate_on_loop(face.vertices, b)
    if la is None or lb is None:
        return None

    # Build an augmented loop with any on-edge endpoints inserted in order.
    on_edge: dict[int, list[QVector3D]] = {}
    if la[0] == "edge":
        on_edge.setdefault(la[1], []).append(QVector3D(a))
    if lb[0] == "edge":
        on_edge.setdefault(lb[1], []).append(QVector3D(b))

    aug: list[QVector3D] = []
    for i, v in enumerate(face.vertices):
        aug.append(v)
        if i in on_edge:
            base = v
            for p in sorted(on_edge[i], key=lambda q: (q - base).length()):
                aug.append(p)

    keys = [_key(v) for v in aug]
    ia = keys.index(_key(a))
    ib = keys.index(_key(b))
    if ia > ib:
        ia, ib = ib, ia
    m = len(aug)
    # Adjacent positions mean the "chord" is just a boundary edge.
    if ib - ia <= 1 or (ia == 0 and ib == m - 1):
        return None

    # The chord must run through the interior, not outside a concave face.
    normal = face.normal()
    origin = face.vertices[0]
    from core.triangulate import plane_axes

    u, w = plane_axes(normal)

    def proj(p):
        rel = p - origin
        return (QVector3D.dotProduct(rel, u), QVector3D.dotProduct(rel, w))

    mid = (a + b) * 0.5
    poly2 = [proj(v) for v in face.vertices]
    if not _strictly_inside_2d(proj(mid), poly2):
        return None

    loop_a = aug[ia : ib + 1]
    loop_b = aug[ib:] + aug[: ia + 1]
    if len(loop_a) < 3 or len(loop_b) < 3:
        return None
    return loop_a, loop_b


def find_chord_split(
    faces: Iterable[Face], a: QVector3D, b: QVector3D
) -> Optional[tuple[Face, list[QVector3D], list[QVector3D]]]:
    """First face that segment ``a``–``b`` chord-splits, with its two halves."""
    for face in faces:
        result = split_face_by_chord(face, a, b)
        if result is not None:
            return face, result[0], result[1]
    return None


def _loop_with_point(
    loop: list[QVector3D], ka: tuple, kb: tuple, point: QVector3D
) -> Optional[list[QVector3D]]:
    """Copy of ``loop`` with ``point`` inserted between the first consecutive
    vertex pair whose keys are ``ka``/``kb`` (either order). ``None`` if no such
    boundary edge exists or ``point`` already is one of those vertices."""
    kp = _key(point)
    n = len(loop)
    for i in range(n):
        j = (i + 1) % n
        ki, kj = _key(loop[i]), _key(loop[j])
        if {ki, kj} == {ka, kb}:
            if kp in (ki, kj):
                return None
            new = list(loop)
            new.insert(i + 1, QVector3D(point))
            return new
    return None


def split_edge_in_faces(
    faces: Iterable[Face],
    edge_a: QVector3D,
    edge_b: QVector3D,
    point: QVector3D,
    skip_endpoints: Iterable[QVector3D] = (),
) -> list[tuple[Face, list[QVector3D]]]:
    """Propagate an edge split into the faces that share that edge.

    When a drawn segment cuts an existing edge ``edge_a``–``edge_b`` at
    ``point``, every face carrying that edge on its outer boundary should gain
    ``point`` as a (collinear) vertex — otherwise the face stays detached from
    the split and won't follow when that vertex is later moved. This is what
    lets a gable wall pick up the ridge apex and deform into a pentagon when the
    ridge is raised, instead of leaving an open triangular gap.

    Returns ``[(face, new_vertices), ...]`` for the faces that changed. A face
    carrying *all* of ``skip_endpoints`` on its boundary is left out: that face
    is chord-split by the drawn segment, which already inserts the point, so
    handling it here would double-process it. Holes are left untouched.
    """
    ka, kb = _key(edge_a), _key(edge_b)
    skip = list(skip_endpoints)
    out: list[tuple[Face, list[QVector3D]]] = []
    for f in faces:
        if skip and all(_locate_on_loop(f.vertices, p) is not None for p in skip):
            continue
        new_verts = _loop_with_point(f.vertices, ka, kb, point)
        if new_verts is not None:
            out.append((f, new_verts))
    return out


# ---- Loop subtraction (a face drawn against another's boundary) -------------

def _face_plane_proj(face: Face):
    """Return ``(proj, poly2)`` — a projector to the face's 2D plane and the
    face's boundary projected with it."""
    from core.triangulate import plane_axes

    normal = face.normal()
    origin = face.vertices[0]
    u, w = plane_axes(normal)

    def proj(p):
        rel = p - origin
        return (QVector3D.dotProduct(rel, u), QVector3D.dotProduct(rel, w))

    return proj, [proj(v) for v in face.vertices]


def find_subdividing_chain(
    face: Face, loop: list[QVector3D]
) -> Optional[list[QVector3D]]:
    """If ``loop`` shares a contiguous boundary arc with ``face`` and pushes a
    single run of vertices through its interior, return that interior chain
    ``[P, ...interior..., Q]`` (P, Q on the face boundary). Otherwise ``None``.

    This is the "rectangle drawn in a corner / along an edge" case: the loop
    neither sits strictly inside the face (a hole) nor is a single straight
    chord — it carves a connected sub-region. Loops that poke outside the face,
    and loops touching the boundary in more than one place are out of scope and
    return ``None``.

    Holes on ``face`` are allowed and ignored here (the chain only concerns the
    outer boundary): drawing a door on a wall that already has a window must
    still subdivide. The caller is responsible for re-assigning each hole to the
    region that contains it.
    """
    if len(face.vertices) < 3 or len(loop) < 3:
        return None
    proj, poly2 = _face_plane_proj(face)

    labels: list[str] = []
    for v in loop:
        if _locate_on_loop(face.vertices, v) is not None:
            labels.append("bdry")
        elif _strictly_inside_2d(proj(v), poly2):
            labels.append("in")
        else:
            return None  # loop pokes outside the face → not a clean subdivision
    if "in" not in labels or "bdry" not in labels:
        return None

    n = len(loop)
    start = labels.index("bdry")
    runs: list[list[int]] = []
    cur: list[int] = []
    for k in range(n):
        idx = (start + k) % n
        if labels[idx] == "in":
            cur.append(idx)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    if len(runs) != 1:
        return None

    run = runs[0]
    p = loop[(run[0] - 1) % n]
    q = loop[(run[-1] + 1) % n]
    if same_position(p, q):
        return None
    return [p, *(loop[i] for i in run), q]


def _arc(seq: list, i: int, j: int) -> list:
    """Cyclic slice of ``seq`` from index ``i`` to ``j`` inclusive, forward."""
    if i <= j:
        return seq[i : j + 1]
    return seq[i:] + seq[: j + 1]


def split_face_by_chain(
    face: Face, chain: list[QVector3D]
) -> Optional[tuple[list[QVector3D], list[QVector3D]]]:
    """Split ``face`` along ``chain`` (``[P, ...interior..., Q]``, ends on the
    boundary) into its two sub-loops. On-edge ends are inserted into the
    boundary. Returns ``None`` if the ends can't be located."""
    p, q = chain[0], chain[-1]
    middles = list(chain[1:-1])
    on_edge: dict[int, list[QVector3D]] = {}
    for pt in (p, q):
        loc = _locate_on_loop(face.vertices, pt)
        if loc is None:
            return None
        if loc[0] == "edge":
            on_edge.setdefault(loc[1], []).append(QVector3D(pt))

    aug: list[QVector3D] = []
    for i, v in enumerate(face.vertices):
        aug.append(v)
        if i in on_edge:
            for pp in sorted(on_edge[i], key=lambda r: (r - v).length()):
                aug.append(pp)

    keys = [_key(x) for x in aug]
    ip = keys.index(_key(p))
    iq = keys.index(_key(q))
    region_pq = _arc(aug, ip, iq) + list(reversed(middles))
    region_qp = _arc(aug, iq, ip) + middles
    if len(region_pq) < 3 or len(region_qp) < 3:
        return None
    return region_pq, region_qp


def subtract_loop_from_face(
    face: Face, loop: list[QVector3D]
) -> Optional[list[QVector3D]]:
    """The remainder of ``face`` after ``loop`` is carved out of it, when the
    loop shares a contiguous boundary arc (corner / edge rectangle). ``None``
    if it isn't that case. The ``loop`` itself stays a separate face."""
    chain = find_subdividing_chain(face, loop)
    if chain is None:
        return None
    split = split_face_by_chain(face, chain)
    if split is None:
        return None
    r1, r2 = split
    loop_keys = frozenset(_key(v) for v in loop)
    if frozenset(_key(v) for v in r1) == loop_keys:
        return r2
    if frozenset(_key(v) for v in r2) == loop_keys:
        return r1
    return None  # neither half is the drawn loop → ambiguous, leave it alone


def carve_loop_by_chords(
    face: Face, loop: list[QVector3D]
) -> Optional[list[list[QVector3D]]]:
    """The pieces of ``face`` left around ``loop`` when EVERY corner of the
    loop sits on the face's boundary — a band drawn across a face from one
    side to the other (a rectangle across a stair tread, from its nosing to
    the riser). ``find_subdividing_chain`` needs a corner inside the face,
    so the Rectangle tool left the face whole with the band lying on top:
    two overlapping faces, edges with one and three faces, and a Push/Pull
    that built a broken solid (found testing #94). Lines drawn one by one
    never hit it: each chord splits the face as it lands.

    The loop's sides that cross the face (chords: midpoint strictly inside)
    split it one by one; the piece that IS the loop is dropped (it stays a
    face of its own). Returns the remaining outer loops, or ``None`` when
    this is not that case."""
    if len(face.vertices) < 3 or len(loop) < 3:
        return None
    if any(_locate_on_loop(face.vertices, v) is None for v in loop):
        return None
    proj, poly2 = _face_plane_proj(face)
    chords = []
    n = len(loop)
    for i in range(n):
        a, b = loop[i], loop[(i + 1) % n]
        mid = (a + b) * 0.5
        if _locate_on_loop(face.vertices, mid) is not None:
            continue                          # runs along the boundary
        if not _strictly_inside_2d(proj(mid), poly2):
            return None                       # leaves the face
        chords.append([QVector3D(a), QVector3D(b)])
    if not chords:
        return None

    class _Piece:
        __slots__ = ("vertices",)

        def __init__(self, vertices):
            self.vertices = vertices

    pieces = [[QVector3D(v) for v in face.vertices]]
    for chord in chords:
        for idx, piece in enumerate(pieces):
            mid = (chord[0] + chord[1]) * 0.5
            p2 = [proj(v) for v in piece]
            if not _strictly_inside_2d(proj(mid), p2):
                continue
            split = split_face_by_chain(_Piece(piece), chord)
            if split is None:
                return None
            pieces[idx:idx + 1] = [list(split[0]), list(split[1])]
            break
        else:
            return None
    loop_keys = frozenset(_key(v) for v in loop)
    rest = [p for p in pieces if frozenset(_key(v) for v in p) != loop_keys]
    if len(rest) != len(pieces) - 1:
        return None                           # the loop is not one of them
    return rest


# ---- Multiple-cycle detection ----------------------------------------------

def _same_cycle(c1: list[QVector3D], c2: list[QVector3D]) -> bool:
    return frozenset(_key(v) for v in c1) == frozenset(_key(v) for v in c2)


def find_cycles_through(
    edges: Iterable[Edge], a: QVector3D, b: QVector3D, max_results: int = 2,
    key=None,
) -> list[list[QVector3D]]:
    """Up to ``max_results`` distinct minimal cycles through segment ``a``–``b``.

    A single new edge can close more than one face — the classic case being a
    diagonal across a square, which bounds a triangle on each side. The first
    cycle is the smallest; the second is the smallest found after removing the
    first's interior nodes, which routes the search to the other side. This is
    what stops auto-facing from creating only one of the two triangles.
    """
    # One adjacency for both searches: the second one (the other side)
    # skips the first cycle's interior nodes instead of rebuilding the graph
    # without them — the same search, since the lists keep the edge order.
    # ``key`` (a KeyMemo) keys each vertex once per plan; a 38 700-edge group
    # rounded every endpoint twice per stroke (09-10).
    key = key or _key
    ka, kb = _key(a), _key(b)
    if ka == kb:
        return []
    adj = _cycle_adjacency(edges, ka, kb, key)
    first = _smallest_cycle(adj, a, b, ka, kb)
    if first is None:
        return []
    cycles = [first]
    if max_results >= 2:
        interior = {_key(v) for v in first} - {ka, kb}
        if interior:
            second = _smallest_cycle(adj, a, b, ka, kb, skip=interior)
            if second is not None and not _same_cycle(second, first):
                cycles.append(second)
    return cycles


# ---- Polygon offset (Offset tool: walls with thickness) --------------------

def _offset_line_intersection(
    p0: QVector3D, u: QVector3D, p1: QVector3D, v: QVector3D, n: QVector3D
) -> Optional[QVector3D]:
    """Intersection of two coplanar lines ``p0+s·u`` and ``p1+t·v`` (in the plane
    with normal ``n``). For (near-)parallel lines — collinear consecutive edges —
    return ``p1`` so the shared vertex survives without a spurious corner."""
    denom = QVector3D.dotProduct(QVector3D.crossProduct(u, v), n)
    if abs(denom) < 1e-9:
        return QVector3D(p1)
    s = QVector3D.dotProduct(QVector3D.crossProduct(p1 - p0, v), n) / denom
    return p0 + u * s


def offset_loop(
    loop: list[QVector3D], normal: QVector3D, d: float
) -> Optional[list[QVector3D]]:
    """Offset a planar polygon ``loop`` by ``d`` in its plane: ``d > 0`` moves the
    boundary *inward* (toward the interior), ``d < 0`` outward. Each edge slides
    along its in-plane normal and consecutive offset edges are re-intersected for
    the new corners. ``None`` if the loop degenerates (too few points, a zero-
    length edge, or the offset collapses/inverts it — e.g. inward by more than
    the polygon's half-width).

    Inward is ``cross(n, edge_dir)``: the Newell ``normal`` winds the loop CCW
    around itself, so that points to the interior. Convex and mild concave loops
    work; a deep concavity can self-intersect (not handled — returns None on
    inversion). Enough for rectangular footprints (walls with thickness)."""
    count = len(loop)
    if count < 3:
        return None
    n = normal.normalized()
    offset_lines: list[tuple[QVector3D, QVector3D]] = []
    for i in range(count):
        a = loop[i]
        b = loop[(i + 1) % count]
        edge = b - a
        if edge.length() < _SPLIT_TOLERANCE:
            return None
        e = edge.normalized()
        inward = QVector3D.crossProduct(n, e).normalized()
        offset_lines.append((a + inward * d, e))
    new_loop: list[QVector3D] = []
    for i in range(count):
        p0, u = offset_lines[(i - 1) % count]
        p1, v = offset_lines[i]
        pt = _offset_line_intersection(p0, u, p1, v, n)
        if pt is None:
            return None
        new_loop.append(pt)
    # Reject an overshot inward offset: if any edge reversed direction, the
    # offset edges crossed (the wall is thicker than the polygon's half-width).
    for i in range(count):
        orig = loop[(i + 1) % count] - loop[i]
        new = new_loop[(i + 1) % count] - new_loop[i]
        if new.length() < _SPLIT_TOLERANCE:
            return None
        if QVector3D.dotProduct(orig.normalized(), new.normalized()) <= 0.0:
            return None
    return new_loop


def max_offset_distance(loop: list[QVector3D], normal: QVector3D,
                       sign: float = 1.0, limit: float = 10.0) -> float:
    """The largest offset in the direction of ``sign`` that :func:`offset_loop`
    still accepts, in metres (0.0 when even a hair collapses the loop).

    Exists so the tool can say WHY it refused. A 20 cm kerb cannot take a
    10 cm inward offset — 0.20 - 2 x 0.10 is exactly zero — and a paved slab
    whose narrowest side is 4.6 cm inverts long before 10 cm. Refusing is
    right; refusing in silence is what reads as "the tool doesn't work"
    (Marco, 2026-09-10). Bisection: offset_loop is cheap and this only runs
    on the failure path.
    """
    step = abs(limit)
    if offset_loop(loop, normal, sign * 1e-4) is None:
        return 0.0
    lo, hi = 1e-4, step
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if offset_loop(loop, normal, sign * mid) is None:
            hi = mid
        else:
            lo = mid
    return lo


# ---- Heal overlapping coplanar faces (spurious mother) ---------------------

def _loop_inside_loop(inner: list[QVector3D], outer: list[QVector3D],
                      normal: QVector3D) -> bool:
    """Whether ``inner`` lies inside ``outer`` (both coplanar loops, by centroid)."""
    if len(inner) < 3 or len(outer) < 3:
        return False
    from core.triangulate import plane_axes
    u, w = plane_axes(normal)
    origin = outer[0]

    def proj(p):
        rel = p - origin
        return (QVector3D.dotProduct(rel, u), QVector3D.dotProduct(rel, w))

    poly = [proj(p) for p in outer]
    cx = sum(p.x() for p in inner) / len(inner)
    cy = sum(p.y() for p in inner) / len(inner)
    cz = sum(p.z() for p in inner) / len(inner)
    if _point_inside_2d(proj(QVector3D(cx, cy, cz)), poly):
        return True
    # The average of the vertices is NOT the centroid, and for a CONCAVE loop
    # it can land outside the loop itself — so a "no" from it means nothing.
    # An offset's inner face coincides exactly with the ring's hole; when its
    # boundary was concave, this said "not inside the hole", the heal pass
    # stopped seeing a legitimate ring and deleted it as a redundant mother
    # (Plaza Yanque, 2026-09-10: Offset 0.10 kept only the inner face).
    # Retry with a point that really is inside.
    point = _interior_point(inner, normal)
    if point is None:
        return False
    return _point_inside_2d(proj(point), poly)


def _interior_point(loop: list[QVector3D], normal: QVector3D):
    """A point genuinely inside ``loop``: the centroid of its biggest
    triangle. ``None`` when the loop does not triangulate (degenerate)."""
    from core.triangulate import triangulate
    try:
        tris = triangulate(list(loop), [], normal)
    except Exception:                      # noqa: BLE001 — geometry, not flow
        return None
    best = None
    best_area = 0.0
    for a, b, c in tris:
        area = QVector3D.crossProduct(b - a, c - a).lengthSquared()
        if area > best_area:
            best_area = area
            best = (a + b + c) / 3.0
    return best


def _point_inside_2d(pt, poly) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _maximal_holes(holes: list) -> list:
    """Drop holes nested inside a larger hole of the same face — redundant
    overlapping holes that incremental subdivision can leave behind."""
    def area(loop):
        a = 0.0
        n = len(loop)
        for i in range(n):
            a += loop[i].x() * loop[(i + 1) % n].y()
            a -= loop[(i + 1) % n].x() * loop[i].y()
        return abs(a) / 2.0

    areas = [area(h) for h in holes]
    keep = []
    for i, h in enumerate(holes):
        # The plane normal from the hole itself (any 3 non-collinear points).
        nrm = QVector3D.crossProduct(h[1] - h[0], h[2] - h[0])
        if nrm.length() < 1e-9:
            keep.append(h)
            continue
        nrm = nrm.normalized()
        nested = any(
            j != i and areas[j] > areas[i] + 1e-6
            and _loop_inside_loop(h, holes[j], nrm)
            for j in range(len(holes))
        )
        if not nested:
            keep.append(h)
    return keep


def _g_inside_a_hole(face: Face, loop: list[QVector3D]) -> bool:
    """Whether ``loop`` sits inside one of ``face``'s holes (so it doesn't
    actually overlap the face's solid region — it fills a hole)."""
    n = face.normal()
    return any(_loop_inside_loop(loop, h, n) for h in face.holes if len(h) >= 3)


def _point_in_face_solid(face: Face, point: QVector3D) -> bool:
    """Whether ``point`` lies in ``face``'s solid region — inside its outer loop
    and outside every hole."""
    from core.triangulate import plane_axes
    n = face.normal()
    u, w = plane_axes(n)
    origin = face.vertices[0]

    def proj(p):
        rel = p - origin
        return (QVector3D.dotProduct(rel, u), QVector3D.dotProduct(rel, w))

    pt = proj(point)
    if not _point_inside_2d(pt, [proj(v) for v in face.vertices]):
        return False
    return not any(_point_inside_2d(pt, [proj(v) for v in h]) for h in face.holes)


def winding_footprint(mesh):
    """How the faces of a flat drawing face BEFORE an edit, for
    :func:`orient_coplanar_faces` to respect afterwards: ``(face, normal,
    outer, holes)`` per face, positions copied (a face the edit removes may
    not keep its loop), plus its bounding box for a cheap first test.
    ``None`` where the orientation pass never runs — a 3D model, or one
    past the heal cap."""
    if len(mesh.faces) > _HEAL_FACE_CAP or not _mesh_is_flat(mesh):
        return None
    out = []
    for f in mesh.faces:
        outer = [QVector3D(v) for v in f.vertices]
        if not outer:
            continue
        xs = [v.x() for v in outer]
        ys = [v.y() for v in outer]
        zs = [v.z() for v in outer]
        box = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
        out.append((f, f.normal(), outer,
                    [[QVector3D(v) for v in h] for h in f.holes], box))
    return out


def _footprint_normal(footprint, face: Face):
    """The normal of the pre-edit face that covered ``face``'s interior, or
    ``None`` when it lies where no face was (a region drawn anew)."""
    from core.triangulate import plane_axes
    n = face.normal()
    point = _interior_point(face.vertices, n)
    if point is None:
        return None
    t = _PLANAR_TOLERANCE
    px, py, pz = point.x(), point.y(), point.z()
    for _old, old_n, outer, holes, box in footprint:
        # After a curve the planar rebuild re-makes EVERY face, and each is
        # looked up here: the box keeps that from costing a polygon test
        # per pair.
        if not (box[0] - t <= px <= box[3] + t and box[1] - t <= py <= box[4] + t
                and box[2] - t <= pz <= box[5] + t):
            continue
        if abs(QVector3D.dotProduct(old_n, n)) < 0.999:
            continue
        u, w = plane_axes(old_n)
        origin = outer[0]
        if abs(QVector3D.dotProduct(point - origin, old_n)) > _PLANAR_TOLERANCE:
            continue

        def proj(p):
            rel = p - origin
            return (QVector3D.dotProduct(rel, u), QVector3D.dotProduct(rel, w))

        pt = proj(point)
        if (_point_inside_2d(pt, [proj(v) for v in outer])
                and not any(_point_inside_2d(pt, [proj(v) for v in h])
                            for h in holes)):
            return old_n
    return None


def orient_coplanar_faces(mesh, footprint=None) -> list:
    """Flip faces whose winding came out reversed, so coplanar faces face the
    same way.

    Auto-faced cycles can close with the opposite orientation (a normal pointing
    the wrong way), and push/pull then extrudes that face *into* the model
    instead of out — it looks like "I can't push this one". A valid solid never
    has two anti-parallel faces on the same plane, so flipping any face whose
    normal opposes the area-weighted majority of its plane only ever fixes that
    anomaly. Returns the flipped faces.

    With ``footprint`` (:func:`winding_footprint`, taken before the edit) the
    orientation is the USER's: a face that was already there is never turned,
    and a face the edit made — a split half, a rebuilt region — faces the way
    the face it was cut from did. Only a region drawn where no face was
    follows the majority. Without it, a face reversed on purpose (Reverse
    Faces) came back the other way at the next draw on the plane — a loose
    rectangle anywhere was enough.
    """
    groups: dict = {}
    for f in mesh.faces:
        n = f.normal()
        axis = (round(abs(n.x()), 2), round(abs(n.y()), 2), round(abs(n.z()), 2))
        dist = round(abs(QVector3D.dotProduct(n, f.centroid())), 2)
        groups.setdefault((axis, dist), []).append(f)

    owned = {id(f) for f, *_ in footprint} if footprint is not None else set()
    flipped: list = []
    for fs in groups.values():
        if len(fs) < 2:
            continue
        dominant = QVector3D(0.0, 0.0, 0.0)
        for f in fs:
            dominant += f.normal() * f.area()
        for f in fs:
            target = dominant
            if footprint is not None:
                if id(f) in owned:
                    continue                      # the user's, as it stands
                old_n = _footprint_normal(footprint, f)
                target = dominant if old_n is None else old_n
            if QVector3D.dotProduct(f.normal(), target) < 0:
                outer = [QVector3D(v) for v in f.vertices][::-1]
                holes = [[QVector3D(v) for v in h] for h in f.holes]
                mesh.remove_face(f)
                mesh.add_face(outer, holes or None).attrs = dict(f.attrs)
                flipped.append(f)
    return flipped


def _collinear_overlapping(e1, e2) -> bool:
    """Whether edge ``e1`` lies collinearly over ``e2`` with overlapping span."""
    a, b, c, d = e1.a, e1.b, e2.a, e2.b
    d1, d2 = b - a, d - c
    if d1.length() < 1e-9 or d2.length() < 1e-9:
        return False
    u = d2.normalized()
    if QVector3D.crossProduct(d1.normalized(), u).length() > 1e-4:
        return False  # not parallel
    rel = a - c
    if (rel - u * QVector3D.dotProduct(rel, u)).length() > _PLANAR_TOLERANCE:
        return False  # parallel but offset (different line)
    ta = QVector3D.dotProduct(a - c, u)
    tb = QVector3D.dotProduct(b - c, u)
    lo1, hi1 = min(ta, tb), max(ta, tb)
    return min(hi1, d2.length()) - max(lo1, 0.0) > 1e-4


def sweep_tjunctions(mesh, seedkeys=None) -> None:
    """Split every edge that runs past a vertex belonging to another face, in
    ONE vectorised pass per round instead of a Python walk per edge.

    ``seedkeys`` (``core.topology._key`` tuples — positions rounded to the weld
    tolerance, NOT ``core.mesh._key``'s integer cells) bound the sweep to an
    operation's own box: only an edge reaching that box can be split, which is
    every T-junction the op can have created and none it merely found lying
    around. ``None`` sweeps the whole mesh, which is what a repair pass wants.

    The scalar form was O(splits x E x V) — ``interior_vertex_on`` walked EVERY
    vertex in Python and the loop restarted from edge zero after each split. On
    the imported brick barbecue (3054 faces) one pass alone measured 24.8 s
    (6983 edges x 3993 vertices), and the pass repeats per split: that is the
    hang Marco hit deleting a few faces inside it, and the same hang the push
    preview hit before phase 1 was batched. ONE implementation now serves both.
    """
    import numpy as np
    from core.mesh import _STITCH_TOL
    tol2 = _STITCH_TOL * _STITCH_TOL
    # Cap on candidate pairs materialised at once, so a model-spanning edge
    # whose slab holds every vertex can't blow memory: edges run in chunks.
    pair_cap = 1 << 21
    # ``seedkeys`` are ``core.topology._key`` tuples — the seed positions
    # rounded to the weld tolerance, so they ARE coordinates and bound the
    # operation directly. (Not ``core.mesh._key``, whose integer cell indices
    # would read as positions 10⁴× too small and shrink the scope to nothing.)
    seed_lo = seed_hi = None
    if seedkeys:
        skeys = np.array(sorted(seedkeys), dtype=np.float64)
        seed_lo = skeys.min(axis=0) - _STITCH_TOL
        seed_hi = skeys.max(axis=0) + _STITCH_TOL
    while True:
        verts = mesh.vertices
        edges = list(mesh.edges)
        if not verts or not edges:
            break
        vpos = np.array([[v.position.x(), v.position.y(), v.position.z()]
                         for v in verts])
        vslot = {id(v): i for i, v in enumerate(verts)}
        ends = np.array([(vslot[id(e.v0)], vslot[id(e.v1)]) for e in edges],
                        dtype=np.int64)
        va, vb = vpos[ends[:, 0]], vpos[ends[:, 1]]
        elo, ehi = np.minimum(va, vb), np.maximum(va, vb)
        if seed_lo is None:
            live = np.ones(len(edges), dtype=bool)
        else:
            live = ((ehi >= seed_lo).all(axis=1)
                    & (elo <= seed_hi).all(axis=1))
        # Degenerate edges never split.
        seg_all = vb - va
        live &= np.einsum("ij,ij->i", seg_all, seg_all) > tol2
        pick = np.flatnonzero(live)
        if not len(pick):
            break
        # Broad phase over the scoped edges: a splitting vertex sits in the
        # edge's box, so only that slice of the x-sorted vertices is tested.
        order = np.argsort(vpos[:, 0], kind="stable")
        xs = vpos[order, 0]
        lo = np.searchsorted(xs, elo[pick, 0] - _STITCH_TOL, side="left")
        counts = np.searchsorted(xs, ehi[pick, 0] + _STITCH_TOL,
                                 side="right") - lo
        counts = np.maximum(counts, 0)
        # Lowest-indexed interior vertex per edge — the scalar sweep walked
        # ``mesh.vertices`` in order, and which vertex splits first must not
        # depend on the x-sort. ``len(verts)`` is the "none" sentinel so
        # ``np.minimum.at`` can reduce into it.
        best = np.full(len(edges), len(verts), dtype=np.int64)
        cum = np.cumsum(counts)
        p0 = 0
        while p0 < len(pick):
            base = int(cum[p0] - counts[p0])
            p1 = max(int(np.searchsorted(cum, base + pair_cap, side="right")),
                     p0 + 1)
            block = slice(p0, p1)
            c = counts[block]
            total = int(c.sum())
            p0 = p1
            if not total:
                continue
            eidx = np.repeat(pick[block], c)
            rank = np.arange(total) - np.repeat(np.cumsum(c) - c, c)
            vidx = order[np.repeat(lo[block], c) + rank]
            keep = (vidx != ends[eidx, 0]) & (vidx != ends[eidx, 1])
            # Narrow the x-slab down the other two axes before projecting.
            # One axis at a time on 1-D gathers is far cheaper than pulling
            # the (N, 3) vertex/edge rows the projection needs, and on a dense
            # model it is what keeps the slab's false positives off that step.
            for ax in (1, 2):
                if not keep.any():
                    break
                on = eidx[keep]
                coord = vpos[vidx[keep], ax]
                keep[keep] = ((coord >= elo[on, ax] - _STITCH_TOL)
                              & (coord <= ehi[on, ax] + _STITCH_TOL))
            if not keep.any():
                continue
            eidx, vidx = eidx[keep], vidx[keep]
            seg = seg_all[eidx]
            rel = vpos[vidx] - va[eidx]
            l2 = np.einsum("ij,ij->i", seg, seg)
            t = np.einsum("ij,ij->i", rel, seg) / l2
            tol_t = _STITCH_TOL / np.sqrt(l2)
            ok = (t > tol_t) & (t < 1.0 - tol_t)
            d = rel - seg * t[:, None]
            ok &= np.einsum("ij,ij->i", d, d) < tol2
            if ok.any():
                np.minimum.at(best, eidx[ok], vidx[ok])
        hits = np.flatnonzero(best < len(verts))
        if not len(hits):
            break
        for i in hits:
            # Only the split edge is removed and only existing vertices are
            # reused, so the sweep's arrays stay valid across these splits.
            mesh.split_edge_at(edges[int(i)], verts[int(best[int(i)])])


def resolve_tjunctions(mesh, max_iter: int = 1000) -> None:
    """Split edges at T-junction vertices so faces with mismatched subdivisions
    share connectivity instead of a naked collinear seam.

    Two walls meeting can leave one face's long edge running past the vertices
    where the other face is split (the door, a perpendicular wall). Their shared
    boundary is then two separate naked edges, not one border-2 edge — so erasing
    the dividing line cascades and deletes a wall instead of merging. Splitting at
    each interior vertex welds the seam; erase-merge then reunites the walls.

    Whole-mesh repair, so it sweeps unscoped — but through the same batched
    pass the push stitch uses, not the per-edge Python walk that hung on a
    3k-face import. ``max_iter`` is kept for callers; the sweep runs to its
    own fixpoint."""
    sweep_tjunctions(mesh)


def fold_nonplanar_faces(mesh, tolerance: float = _PLANAR_TOLERANCE) -> list:
    """*Autofold*: split every face a move has warped out of its
    plane into planar pieces along fold edges.

    The warped face is triangulated (earcut over its Newell plane — robust for
    the gentle warps a vertex drag produces), then coplanar adjacent triangles
    are merged back so only the true folds remain: a quad with one lifted
    corner becomes exactly two triangles joined by one fold edge. Merging is
    confined to the pieces of the same source face, so a fold never dissolves
    into a coplanar neighbour across the original boundary. Returns the faces
    that were folded (the originals, already removed from the mesh)."""
    folded = []
    for face in list(mesh.faces):
        pts = list(face.vertices)
        for hole in face.holes:
            pts += list(hole)
        if len(pts) <= 3 or is_planar(pts, tolerance):
            continue
        tris = face.triangulate()
        if len(tris) < 2:
            continue
        mesh.remove_face(face)
        pieces = {
            mesh.add_face([QVector3D(a), QVector3D(b), QVector3D(c)])
            for a, b, c in tris
        }
        for piece in pieces:  # every planar piece continues the warped mother
            piece.attrs = dict(face.attrs)
        merged = True
        while merged:
            merged = False
            for f in list(pieces):
                if f not in mesh.faces:
                    pieces.discard(f)
                    continue
                lp = f.loop
                for i in range(len(lp)):
                    e = mesh.find_edge(lp[i], lp[(i + 1) % len(lp)])
                    if e is None or len(e.faces) != 2:
                        continue
                    g = e.faces[0] if e.faces[1] is f else e.faces[1]
                    if g is f or g not in pieces:
                        continue
                    if QVector3D.dotProduct(f.normal().normalized(),
                                            g.normal().normalized()) > 0.999:
                        region = mesh.dissolve_edge(e)
                        if region is not None:
                            region.attrs = dict(face.attrs)
                            pieces.discard(f)
                            pieces.discard(g)
                            pieces.add(region)
                            merged = True
                            break
                if merged:
                    break
        folded.append(face)
    return folded


def _box_grid(lo, hi):
    """``meeting(i)``: the indices, ascending, of the boxes (rows of ``lo`` /
    ``hi``) that meet box ``i`` — the same answer as testing all of them.

    One NumPy sweep over every box per query was 4 s of each Line click on an
    exploded DWG plan of 19 800 edges, 11 700 of them faceless (#491). Boxes
    go in the cells they cover; the cell grows until they cover a few each."""
    import numpy as np
    n = len(lo)
    size = max(float(np.median((hi - lo).max(axis=1))) if n else 1.0, 1e-6)
    while (np.prod(np.floor(hi / size) - np.floor(lo / size) + 1, axis=1)
           .sum() > 8 * max(n, 1)):
        size *= 2.0
    c_lo = np.floor(lo / size).astype(np.int64).tolist()
    c_hi = np.floor(hi / size).astype(np.int64).tolist()
    lo_l, hi_l = lo.tolist(), hi.tolist()
    grid: dict = {}
    for k in range(n):
        (x0, y0, z0), (x1, y1, z1) = c_lo[k], c_hi[k]
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                for cz in range(z0, z1 + 1):
                    grid.setdefault((cx, cy, cz), []).append(k)

    def meeting(i):
        (x0, y0, z0), (x1, y1, z1) = c_lo[i], c_hi[i]
        cand: set = set()
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                for cz in range(z0, z1 + 1):
                    cand.update(grid.get((cx, cy, cz), ()))
        (ax, ay, az), (bx, by, bz) = lo_l[i], hi_l[i]
        out = []
        for j in sorted(cand):
            (px, py, pz), (qx, qy, qz) = lo_l[j], hi_l[j]
            if (qx >= ax and qy >= ay and qz >= az
                    and px <= bx and py <= by and pz <= bz):
                out.append(j)
        return out
    return meeting


def prune_collinear_orphan_edges(mesh) -> list:
    """Remove edges that bound no face and lie collinearly over another edge — the
    unwelded collinear overlaps that leave a duplicate 'division line'. Returns
    the removed edges."""
    removed = []
    edges = list(mesh.edges)
    orphans = [e for e in edges if len(e.faces) == 0]
    if not orphans:
        return removed
    import numpy as np
    # Broad phase: an edge can only overlap one whose box it meets. The bare
    # loop tested every orphan against EVERY edge — 850k calls to the
    # collinearity predicate on the imported barbecue, 2.8 s of a Delete.
    P = np.array([[e.a.x(), e.a.y(), e.a.z(), e.b.x(), e.b.y(), e.b.z()]
                  for e in edges], dtype=np.float64)
    lo = np.minimum(P[:, :3], P[:, 3:]) - _PLANAR_TOLERANCE
    hi = np.maximum(P[:, :3], P[:, 3:]) + _PLANAR_TOLERANCE
    slot = {id(e): i for i, e in enumerate(edges)}
    meeting = _box_grid(lo, hi)
    # An orphan already pruned must not prune the one it lay on: the bare
    # loop read the LIVE edge list, so the partner had to still be there.
    gone: set = set()
    for e in orphans:
        i = slot[id(e)]
        for j in meeting(i):
            other = edges[j]
            if other is e or id(other) in gone:
                continue
            if _collinear_overlapping(e, other):
                mesh.remove_edge(e)
                removed.append(e)
                gone.add(id(e))
                break
    return removed


def _mesh_is_flat(mesh) -> bool:
    """Whether every face lies on one common plane — a flat 2D drawing, where the
    aggressive partial-overlap cleanup is safe (in 3D, coplanar faces inside each
    other are legitimate)."""
    faces = mesh.faces
    if len(faces) < 2:
        return True
    n0 = faces[0].normal()
    d0 = QVector3D.dotProduct(n0, faces[0].vertices[0])
    for f in faces[1:]:
        if not _faces_coplanar(n0, f.normal()):
            return False
        if abs(QVector3D.dotProduct(n0, f.vertices[0]) - d0) > _PLANAR_TOLERANCE:
            return False
    return True


#: Above this many faces the overlap heal is skipped entirely — see the
#: guard at the top of :func:`heal_overlapping_faces`.
_HEAL_FACE_CAP = 3000


#: Slack on the face boxes the heal filters pairs with: far past the
#: planar tolerance a "coplanar" point may sit off the plane by.
_BOX_PAD = 1e-2


def _outer_boxes(faces):
    """``(lo, hi)``: per face, the bounding box of its outer loop."""
    import numpy as np
    if not faces:
        return np.empty((0, 3)), np.empty((0, 3))
    lo = np.empty((len(faces), 3))
    hi = np.empty((len(faces), 3))
    for i, f in enumerate(faces):
        pts = np.array([(v.x(), v.y(), v.z()) for v in f.vertices])
        lo[i] = pts.min(axis=0)
        hi[i] = pts.max(axis=0)
    return lo, hi


def heal_overlapping_faces(mesh, coverage: float = 0.5, partial=None,
                           footprint=None) -> list:
    """Clean up coplanar face overlaps that draw/delete sequences can leave:

    1. **Redundant nested holes** — incrementally subdividing a face can punch
       overlapping holes (a hole inside a hole). Keep only the outermost ones.
    2. **A redundant mother** — a big enclosing face left on top of the smaller
       coplanar faces inside it (not merely filling its holes). When the inside
       faces cover most (> ``coverage``) of its area, that mother is spurious;
       remove it so the real subdivision stays. A ring (face with holes) whose
       inside faces only *fill its holes* is legitimate and kept.

    3. **Reversed faces** — a face auto-faced with the wrong winding (so it would
       push the wrong way) is flipped to match its plane. Given the edit's
       ``footprint`` (:func:`winding_footprint`), faces that were already
       there keep the way the user left them.

    The partial-overlap pass also removes a small face whose body lies in
    another's solid region — a partial overlap the auto-divide missed (e.g. a
    door-corner sliver). It's unsafe in 3D (stacked blocks, through-holes
    legitimately nest coplanar faces), so ``partial`` defaults to *auto*: on only
    when the whole model is one flat plane (a 2D drawing). ``True``/``False``
    force it.

    Returns the faces removed (the rebuilt/flipped ones don't count).
    """
    if len(mesh.faces) > _HEAL_FACE_CAP:
        # This heal exists for hand-drawing scale (the overlaps draw/delete
        # sequences leave); its mother-face pass is O(F²) and froze the UI
        # for minutes after exploding a 9k-face import (piscina.igz user
        # report — a single Delete took >120 s). At import scale the
        # cosmetic overlap cleanup is skipped; editing stays correct.
        return []
    flat = _mesh_is_flat(mesh)
    if partial is None:
        partial = flat

    # 0a. Prune duplicate division lines: an edge bounding no face that lies
    #     collinearly over another edge (the unwelded collinear-overlap that
    #     leaves a "doubled line" you can't merge away).
    prune_collinear_orphan_edges(mesh)

    # 0b. Weld T-junction seams so two faces share their dividing edge — erasing
    #     it then merges the walls instead of deleting one.
    resolve_tjunctions(mesh)

    # 0c. Flip any reversed face so coplanar faces face the same way — only
    #     meaningful on a flat drawing. In 3D one plane can legitimately carry
    #     opposite outwards (two solids back to back share it), so winding is
    #     the volumetric pass's job (``orient_outward`` below).
    if flat:
        orient_coplanar_faces(mesh, footprint)

    # 1. Dedupe nested holes by rebuilding the face with the outermost holes.
    for face in list(mesh.faces):
        if len(face.holes) < 2:
            continue
        keep = _maximal_holes(face.holes)
        if len(keep) != len(face.holes):
            outer = [QVector3D(v) for v in face.vertices]
            mesh.remove_face(face)
            mesh.add_face(
                outer, [[QVector3D(v) for v in h] for h in keep] or None
            ).attrs = dict(face.attrs)

    # 2. Remove a redundant mother covered by faces that aren't in its holes.
    removed: list = []
    # Normals and areas ONCE per face, not once per pair: this sweep is
    # O(F^2) and it re-derived ``Face.normal()`` (a Newell walk over
    # QVector3D) inside the inner loop — 4.2M Newell computations, 66 s of
    # the 82 s a Delete cost on the imported barbecue. Faces are only
    # REMOVED here, and a removed face stays alive in ``removed``, so no
    # cached id can be reused under us.
    import numpy as np
    snap = list(mesh.faces)
    N = np.array([[(n := f.normal()).x(), n.y(), n.z()] for f in snap],
                 dtype=np.float64) if snap else np.empty((0, 3))
    A = np.array([f.area() for f in snap], dtype=np.float64)
    LO, HI = _outer_boxes(snap)
    gone: set = set()
    for i, face in enumerate(snap):
        a_face = A[i]
        if a_face < _SPLIT_TOLERANCE:
            continue
        # The coplanar partner test for the WHOLE mesh in one dot product.
        # Same tolerance, same pairs — but the scalar form ran 4.2M times in
        # Python (66 s of the 82 s a Delete cost inside the imported
        # barbecue, plus 5 s once its normals were cached). A loop strictly
        # inside the face sits inside its box too: on a flat plan every face
        # is coplanar with every other, and the box test is what keeps an
        # exploded DWG of 700 faces from testing them all (#491).
        cand = np.flatnonzero((np.abs(N @ N[i]) > 0.999) & (A < a_face)
                              & (LO >= LO[i] - _BOX_PAD).all(axis=1)
                              & (HI <= HI[i] + _BOX_PAD).all(axis=1))
        covered = 0.0
        for j in cand:
            g = snap[j]
            if g is face or id(g) in gone:
                continue
            if (loop_inside_face(face, g.vertices)
                    and not _g_inside_a_hole(face, g.vertices)):
                covered += A[j]
        if covered > coverage * a_face:
            mesh.remove_face(face)
            removed.append(face)
            gone.add(id(face))

    # 3. (Flat plans) A small face whose body lies in a bigger coplanar face's
    #    solid region is a partial overlap the auto-divide missed (a door piece
    #    drawn over the wall). Don't delete it — the user wants it as its own
    #    selectable face — instead punch a matching hole in the bigger face so
    #    they no longer overlap. The small face fills that hole.
    if partial:
        from collections import defaultdict
        # Rebuilt for THIS pass: pass 2 removed faces and the earlier passes
        # may have rebuilt some, so the pass-2 caches no longer cover the
        # mesh. Same reason as there — the sweep is O(F^2).
        snap3 = list(mesh.faces)
        N3 = np.array([[(n := f.normal()).x(), n.y(), n.z()] for f in snap3],
                      dtype=np.float64) if snap3 else np.empty((0, 3))
        A3 = np.array([f.area() for f in snap3], dtype=np.float64)
        LO3, HI3 = _outer_boxes(snap3)
        punch: dict = defaultdict(list)
        for i3, face in enumerate(snap3):
            if id(face) in gone:
                continue
            # Guaranteed-interior probes: triangle centroids. A concave face's
            # polygon centroid can fall OUTSIDE itself (an L around a circular
            # sector lands inside the sector) and used to punch a bogus hole in
            # a neighbour it merely borders — require the face's *body* (most of
            # its triangles) to lie inside the bigger face instead.
            tris = face.triangulate()
            if not tris:
                continue
            probes = [(t0 + t1 + t2) / 3.0 for t0, t1, t2 in tris]
            a_face = A3[i3]
            # Probes are in this face's box and count only inside g's outer
            # loop, so g's box must meet ours — 2.4 M probe tests, 135 s,
            # on an exploded DWG plan without it (#491).
            for j3 in np.flatnonzero((np.abs(N3 @ N3[i3]) > 0.999)
                                     & (A3 > a_face)
                                     & (LO3 <= HI3[i3] + _BOX_PAD).all(axis=1)
                                     & (HI3 >= LO3[i3] - _BOX_PAD).all(axis=1)):
                g = snap3[j3]
                if g is face or id(g) in gone:
                    continue
                if _g_inside_a_hole(g, face.vertices):
                    continue  # already filling a hole — no overlap
                inside = sum(1 for p in probes if _point_in_face_solid(g, p))
                if inside * 2 > len(probes):
                    punch[g].append(face)
                    break
        for g, smalls in punch.items():
            outer = [QVector3D(v) for v in g.vertices]
            holes = [[QVector3D(v) for v in h] for h in g.holes]
            holes += [[QVector3D(v) for v in s.vertices] for s in smalls]
            mesh.remove_face(g)
            try:
                mesh.add_face(outer, holes).attrs = dict(g.attrs)
            except Exception:
                # Degenerate hole arrangement — fall back to the face as it was.
                mesh.add_face(outer, [[QVector3D(v) for v in h]
                                      for h in g.holes] or None
                              ).attrs = dict(g.attrs)

    # 4. (3D) Volumetric winding: a freshly drawn sub-face lands with whatever
    #    winding the user traced; on a closed solid, orient per face (and
    #    re-mark interior partitions). No-op on open meshes.
    if not flat:
        from core.orient import orient_outward
        orient_outward(mesh)
    return removed




#: The defects :func:`defects_near` counts, worst first — the order a
#: refusal names them in when a weld leaves more than one.
DEFECT_KINDS = ("duplicate_face", "overlapping_face", "pinched_face",
                "crossed_face", "flat_face", "zero_edge")


def _loop_crosses_itself(loop, normal: QVector3D) -> bool:
    """Whether two non-adjacent sides of a closed loop cross or touch, in
    the loop's own plane — a corner dragged over the far side of its face
    turns a quad into a bow tie."""
    count = len(loop)
    if count < 4:
        return False
    n = (normal.x(), normal.y(), normal.z())
    ax = max(range(3), key=lambda i: abs(n[i]))
    u, w = [i for i in range(3) if i != ax]
    pts = []
    for v in loop:
        p = (v.position.x(), v.position.y(), v.position.z())
        pts.append((p[u], p[w]))
    eps = 1e-9

    def orient(a, b, c):
        val = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return 0 if abs(val) < eps else (1 if val > 0 else -1)

    def on_seg(a, b, c):
        return (min(a[0], b[0]) - eps <= c[0] <= max(a[0], b[0]) + eps and
                min(a[1], b[1]) - eps <= c[1] <= max(a[1], b[1]) + eps)

    for i in range(count):
        a, b = pts[i], pts[(i + 1) % count]
        for j in range(i + 2, count):
            if i == 0 and j == count - 1:
                continue                      # the closing side: adjacent
            c, d = pts[j], pts[(j + 1) % count]
            o1, o2 = orient(a, b, c), orient(a, b, d)
            o3, o4 = orient(c, d, a), orient(c, d, b)
            if o1 != o2 and o3 != o4 and 0 not in (o1, o2, o3, o4):
                return True
            if ((o1 == 0 and on_seg(a, b, c)) or (o2 == 0 and on_seg(a, b, d))
                    or (o3 == 0 and on_seg(c, d, a))
                    or (o4 == 0 and on_seg(c, d, b))):
                return True
    return False


def _coplanar_overlap(f, g) -> bool:
    """Whether two faces lie in one plane and cover some of the same area
    (more than a shared side or corner): one's inside reaches into the
    other, or a side of one cuts properly across a side of the other."""
    nf, ng = f.normal(), g.normal()
    if abs(QVector3D.dotProduct(nf, ng)) < 1.0 - 1e-6:
        return False
    origin = f.loop[0].position
    if any(abs(QVector3D.dotProduct(v.position - origin, nf)) > _SPLIT_TOLERANCE
           for v in g.loop):
        return False
    for a, b in ((f, g), (g, f)):
        inner = _interior_point(a.vertices, a.normal())
        if (inner is not None and _point_in_face_solid(a, inner)
                and _point_in_face_solid(b, inner)):
            return True
    from core.triangulate import plane_axes
    u, w = plane_axes(nf)

    def proj(v):
        rel = v.position - origin
        return (QVector3D.dotProduct(rel, u), QVector3D.dotProduct(rel, w))

    def sides(face):
        pts = [proj(v) for v in face.loop]
        return [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]

    def orient(a, b, c):
        val = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return 0 if abs(val) < 1e-9 else (1 if val > 0 else -1)

    for a, b in sides(f):
        for c, d in sides(g):
            o1, o2 = orient(a, b, c), orient(a, b, d)
            o3, o4 = orient(c, d, a), orient(c, d, b)
            if 0 not in (o1, o2, o3, o4) and o1 != o2 and o3 != o4:
                return True
    return False


def defects_near(vertices, area_eps: float = 1e-10) -> dict:
    """Count the topological defects among the edges and faces that touch
    ``vertices`` (mesh ``Vertex`` objects), by kind (:data:`DEFECT_KINDS`):

    * ``duplicate_face`` — a face over the same edge cycle as another;
    * ``overlapping_face`` — two faces in one plane covering the same area
      (a pair counts once);
    * ``pinched_face`` — a loop that passes twice through one vertex, or an
      edge that borders the same face twice;
    * ``crossed_face`` — two sides of one loop cross (a bow tie);
    * ``flat_face`` — a face with no area left (under three distinct
      corners, or all of them in a row);
    * ``zero_edge`` — an edge whose ends are one point.

    Edges with three or more faces are NOT a defect here: a partition
    inside a box, or a fin on its edge, is normal surface modelling.

    Local on purpose: a move checks the neighbourhood it touched before and
    after, so a huge model pays for a few faces, and old damage elsewhere
    never blocks an unrelated edit."""
    counts = dict.fromkeys(DEFECT_KINDS, 0)
    edges: dict = {}
    faces: dict = {}
    for v in vertices:
        for e in v.edges:
            edges[id(e)] = e
            for f in e.faces:
                faces[id(f)] = f
    for e in edges.values():
        if (e.v0 is e.v1 or
                (e.v0.position - e.v1.position).lengthSquared() < 1e-18):
            counts["zero_edge"] += 1
        if len({id(f) for f in e.faces}) < len(e.faces):
            counts["pinched_face"] += 1
    seen: set = set()
    for f in faces.values():
        loops = [f.loop, *f.hole_loops]
        distinct = {id(x) for x in f.loop}
        if len(distinct) < 3 or f.area() < area_eps:
            counts["flat_face"] += 1
        for loop in loops:
            if len({id(x) for x in loop}) < len(loop):
                counts["pinched_face"] += 1
            elif len(loop) >= 4 and _loop_crosses_itself(loop, f.normal()):
                counts["crossed_face"] += 1
        sig = frozenset(
            frozenset((id(f.loop[i]), id(f.loop[(i + 1) % len(f.loop)])))
            for i in range(len(f.loop)))
        if sig in seen:
            counts["duplicate_face"] += 1
        seen.add(sig)
    flat = [f for f in faces.values() if len({id(x) for x in f.loop}) >= 3
            and f.area() >= area_eps]
    for i, f in enumerate(flat):
        for g in flat[i + 1:]:
            if _coplanar_overlap(f, g):
                counts["overlapping_face"] += 1
    return counts


def new_defects(before: dict, after: dict) -> list:
    """The defect kinds :func:`defects_near` counts more of ``after`` than
    ``before``, worst first."""
    return [k for k in DEFECT_KINDS if after.get(k, 0) > before.get(k, 0)]
