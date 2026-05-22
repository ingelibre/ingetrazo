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


def _key(p: QVector3D) -> tuple[float, float, float]:
    return (round(p.x(), _KEY_DECIMALS),
            round(p.y(), _KEY_DECIMALS),
            round(p.z(), _KEY_DECIMALS))


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


def face_exists(faces: Iterable[Face], cycle: list[QVector3D]) -> bool:
    """Whether a face with the same vertex set as ``cycle`` already exists."""
    cycle_keys = frozenset(_key(v) for v in cycle)
    for face in faces:
        if frozenset(_key(v) for v in face.vertices) == cycle_keys:
            return True
    return False
