"""Topology helpers — graph queries over the scene's edge network.

Used by tools (today: ``LineTool``) to find polygons that close when a new
edge is added. Modeled after SketchUp's behaviour: as soon as a new edge
completes a planar cycle in the edge graph — using any combination of
existing edges — that cycle becomes a face automatically.

Position equality is tolerant: two vertices within ``_KEY_DECIMALS``
decimal places (≈ 0.1 mm at metric scale) are treated as the same node.
"""
from __future__ import annotations

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
    exists. This is the primitive behind SketchUp-style auto-merge: drawing
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

    # adj[u] -> [(v_key, v_pos), ...]
    adj: dict[tuple, list[tuple[tuple, QVector3D]]] = {}
    for edge in edges:
        ea, eb = _key(edge.a), _key(edge.b)
        if ea == eb:
            continue
        # Skip an existing copy of the same edge, otherwise the cycle just
        # finds itself (length-2 loop a→b→a).
        if {ea, eb} == {ka, kb}:
            continue
        adj.setdefault(ea, []).append((eb, edge.b))
        adj.setdefault(eb, []).append((ea, edge.a))

    if ka not in adj or kb not in adj:
        return None

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
            if v_key not in parent:
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

    v0 = vertices[0]
    plane_normal: Optional[QVector3D] = None
    for i in range(1, n - 1):
        for j in range(i + 1, n):
            cross = QVector3D.crossProduct(vertices[i] - v0, vertices[j] - v0)
            if cross.length() > 1e-6:
                plane_normal = cross.normalized()
                break
        if plane_normal is not None:
            break
    if plane_normal is None:
        return False
    for v in vertices:
        if abs(QVector3D.dotProduct(plane_normal, v - v0)) > tolerance:
            return False
    return True


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

    a = QVector3D.dotProduct(d1, d1)
    b = QVector3D.dotProduct(d1, d2)
    c = QVector3D.dotProduct(d2, d2)
    w0 = p1 - p3
    d = QVector3D.dotProduct(d1, w0)
    e = QVector3D.dotProduct(d2, w0)
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
    if not (-margin1 <= s <= 1.0 + margin1):
        return None
    if not (-margin2 <= t <= 1.0 + margin2):
        return None

    point_on_1 = p1 + d1 * s
    point_on_2 = p3 + d2 * t
    if (point_on_1 - point_on_2).length() > tol:
        return None  # skew: lines pass without meeting
    return (point_on_1 + point_on_2) * 0.5


def _order_along(a: QVector3D, b: QVector3D, points: list[QVector3D]) -> list[QVector3D]:
    """Deduplicate ``points`` and order them by their projection along a→b,
    dropping any that coincide with an endpoint."""
    d = b - a
    uniq: list[QVector3D] = []
    for p in points:
        if same_position(p, a) or same_position(p, b):
            continue
        if not any(same_position(p, q) for q in uniq):
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


def loop_inside_face(mother: Face, loop: list[QVector3D]) -> bool:
    """Whether ``loop`` lies entirely, strictly inside coplanar face ``mother``.

    Requires the loop to be coplanar with the mother and every loop vertex to
    fall strictly inside the mother's outer polygon (no vertex on its
    boundary). A loop that shares any boundary point is a chord split, handled
    elsewhere, and returns ``False`` here.
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
    return all(_strictly_inside_2d(proj(v), poly2) for v in loop)


def find_containing_face(
    faces: Iterable[Face], loop: list[QVector3D], exclude: Optional[Face] = None
) -> Optional[Face]:
    """Smallest existing face that strictly contains ``loop`` (or ``None``).

    Smallest by vertex count is a cheap, good-enough proxy for the immediate
    mother when faces are nested. ``exclude`` skips the face being added.
    """
    best: Optional[Face] = None
    for face in faces:
        if face is exclude:
            continue
        if loop_inside_face(face, loop):
            if best is None or len(face.vertices) < len(best.vertices):
                best = face
    return best


def _loop_edges(loop: list[QVector3D]) -> list[frozenset]:
    n = len(loop)
    return [
        frozenset((_key(loop[i]), _key(loop[(i + 1) % n]))) for i in range(n)
    ]


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


# ---- Multiple-cycle detection ----------------------------------------------

def _same_cycle(c1: list[QVector3D], c2: list[QVector3D]) -> bool:
    return frozenset(_key(v) for v in c1) == frozenset(_key(v) for v in c2)


def find_cycles_through(
    edges: Iterable[Edge], a: QVector3D, b: QVector3D, max_results: int = 2
) -> list[list[QVector3D]]:
    """Up to ``max_results`` distinct minimal cycles through segment ``a``–``b``.

    A single new edge can close more than one face — the classic case being a
    diagonal across a square, which bounds a triangle on each side. The first
    cycle is the smallest; the second is the smallest found after removing the
    first's interior nodes, which routes the search to the other side. This is
    what stops auto-facing from creating only one of the two triangles.
    """
    edges = list(edges)
    first = find_smallest_cycle_through(edges, a, b)
    if first is None:
        return []
    cycles = [first]
    if max_results >= 2:
        interior = {_key(v) for v in first} - {_key(a), _key(b)}
        if interior:
            filtered = [
                e for e in edges
                if _key(e.a) not in interior and _key(e.b) not in interior
            ]
            second = find_smallest_cycle_through(filtered, a, b)
            if second is not None and not _same_cycle(second, first):
                cycles.append(second)
    return cycles
