"""Deterministic plane rebuild for push/pull (the root-fix, "path C").

Replaces the fragile post-extrude heal chain on a given plane — the
``_extrude_commands`` case tree + ``cap_boundary_loops`` + the winding-tolerant
coplanar merge — with one deterministic recompute:

1. Gather the mesh edges lying on the plane.
2. Run the planar arrangement (:mod:`core.arrangement`) to get every minimal
   bounded region.
3. Classify each region as **part of the solid** (inside) or a **phantom**
   (outside) by the winding number of an interior point against the plane's
   *wall* edges, each oriented so the solid sits on its left — the wall's
   outward normal (from :func:`core.orient.orient_outward`) projected into the
   plane decides the side. This is the "which side is the solid?" question the
   plain arrangement can't answer on its own.
4. Union the solid regions (dropping the edges interior to the union) into the
   final face loops — outer boundary plus holes.

The classification was validated against the engine bench (irregular triangle
prism, every push order; concave L with a phantom in the notch) before wiring
in — see the session notes. The headline win: a push that touched a plane just
rebuilds that plane's faces from its edges, instead of patching geometry with a
growing tree of special cases.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional

from PySide6.QtGui import QVector3D

from core.arrangement import (
    _TOL,
    _interior_point,
    _point_in_polygon,
    _signed_area,
    planar_arrangement,
    plane_basis,
)

# A point this close to the plane (along its normal) counts as on it.
_ON_PLANE = 1e-4


def _key2(p) -> tuple[int, int]:
    return (round(p[0] / _TOL), round(p[1] / _TOL))


def _on_plane(pos: QVector3D, origin: QVector3D, normal: QVector3D) -> bool:
    return abs(QVector3D.dotProduct(pos - origin, normal)) < _ON_PLANE


def _winding(p, edges) -> float:
    """Signed winding number of point ``p`` against the directed 2D ``edges``
    (≈ ±1 inside, 0 outside). Robust on concave outlines where an even-odd test
    would misjudge a notch."""
    total = 0.0
    for a, b in edges:
        ax, ay = a[0] - p[0], a[1] - p[1]
        bx, by = b[0] - p[0], b[1] - p[1]
        total += math.atan2(ax * by - ay * bx, ax * bx + ay * by)
    return total / (2.0 * math.pi)


def _wall_boundary(mesh, origin, normal, u, v, to2d) -> list:
    """Directed 2D edges of the plane's *wall* borders, oriented so the solid is
    on the left. A plane edge borders a wall when it is shared with a face that
    is **not** coplanar with this plane; that wall's outward normal projected
    into the plane points away from the solid, which fixes the side."""
    edges = []
    for e in mesh.edges:
        if not (_on_plane(e.a, origin, normal) and _on_plane(e.b, origin, normal)):
            continue
        wall = next(
            (f for f in e.faces
             if abs(QVector3D.dotProduct(f.normal().normalized(), normal)) < 0.5),
            None,
        )
        if wall is None:
            continue
        nw = wall.normal().normalized()
        out2 = (QVector3D.dotProduct(nw, u), QVector3D.dotProduct(nw, v))
        a2, b2 = to2d(e.a), to2d(e.b)
        dx, dy = b2[0] - a2[0], b2[1] - a2[1]
        # Left normal of a→b is (-dy, dx); keep the orientation whose left points
        # inward (toward the solid = opposite the wall's outward projection).
        if (-dy) * (-out2[0]) + dx * (-out2[1]) > 0:
            edges.append((a2, b2))
        else:
            edges.append((b2, a2))
    return edges


def _region_test_point(outer_xy, holes_xy):
    """A point inside ``outer_xy`` but outside every hole — so the classifier
    samples the region's *material*, not a void. The plain centroid of an annular
    region (a cap with a skylight) falls in the hole, which would misread it as
    outside the solid; this nudges in from an outer edge instead when needed."""
    p = _interior_point(outer_xy)
    if not any(_point_in_polygon(p, h) for h in holes_xy):
        return p
    n = len(outer_xy)
    for i in range(n):
        ax, ay = outer_xy[i]
        bx, by = outer_xy[(i + 1) % n]
        mx, my = (ax + bx) / 2, (ay + by) / 2
        dx, dy = bx - ax, by - ay
        ln = math.hypot(dx, dy)
        if ln < _TOL:
            continue
        # Interior of a CCW loop is to the left of a→b: nudge along (-dy, dx).
        q = (mx - dy / ln * 1e-3, my + dx / ln * 1e-3)
        if _point_in_polygon(q, outer_xy) and not any(
            _point_in_polygon(q, h) for h in holes_xy
        ):
            return q
    return p


def _union_outline(solid_regions_xy) -> list:
    """Union a set of 2D regions (each ``(outer, [holes])`` wound as the
    arrangement winds them — outer CCW, holes CW) into ``[(outer, [holes])]``,
    dropping every edge interior to the union (it appears in two solid regions,
    once in each direction, so the directions cancel)."""
    dir_count: dict = defaultdict(int)
    coords: dict = {}
    for outer, holes in solid_regions_xy:
        for loop in (outer, *holes):
            n = len(loop)
            for i in range(n):
                a, b = loop[i], loop[(i + 1) % n]
                ka, kb = _key2(a), _key2(b)
                coords[ka] = a
                coords[kb] = b
                dir_count[(ka, kb)] += 1

    # Net direction per undirected edge: interior edges cancel (a→b and b→a),
    # boundary edges survive in the direction that keeps the solid on the left.
    out_adj: dict = defaultdict(list)
    for (ka, kb), c in dir_count.items():
        net = c - dir_count.get((kb, ka), 0)
        for _ in range(net):
            out_adj[ka].append(kb)

    # Trace the surviving directed edges into closed loops.
    loops: list = []
    for start in list(out_adj.keys()):
        while out_adj[start]:
            loop = [start]
            cur = out_adj[start].pop()
            while cur != start:
                loop.append(cur)
                nxts = out_adj.get(cur)
                if not nxts:
                    loop = None
                    break
                cur = nxts.pop()
                if len(loop) > 100000:
                    loop = None
                    break
            if loop is not None and len(loop) >= 3:
                loops.append([coords[k] for k in loop])

    # Classify: CCW loops are outer faces, CW loops are holes; nest each hole in
    # the smallest outer that contains it.
    outers = [lp for lp in loops if _signed_area(lp) > _TOL]
    holes = [lp for lp in loops if _signed_area(lp) < -_TOL]
    outers.sort(key=lambda lp: _signed_area(lp))  # smallest first
    result = [(o, []) for o in outers]
    for h in holes:
        hp = _interior_point(h)
        for outer, hl in result:
            if _point_in_polygon(hp, outer):
                hl.append(h)
                break
    return result


def rebuild_plane(mesh, origin: QVector3D, normal: QVector3D) -> Optional[list]:
    """Recompute the solid faces of ``mesh`` on the plane ``(origin, normal)``.

    Returns ``[(outer_loop, [hole_loops]), …]`` with every loop a list of 3D
    ``QVector3D`` on the plane, ready for ``AddFaceCommand`` — or ``None`` when
    the plane carries too little to face (fewer than three usable edges). Pure:
    it reads the mesh, it does not mutate it.
    """
    normal = normal.normalized()
    u, v = plane_basis(normal)

    def to2d(p):
        d = p - origin
        return (QVector3D.dotProduct(d, u), QVector3D.dotProduct(d, v))

    def to3d(xy):
        return origin + u * xy[0] + v * xy[1]

    segs = [
        (e.a, e.b)
        for e in mesh.edges
        if _on_plane(e.a, origin, normal) and _on_plane(e.b, origin, normal)
    ]
    if len(segs) < 3:
        return None

    regions_3d = planar_arrangement(segs, origin, normal)
    if not regions_3d:
        return None

    boundary = _wall_boundary(mesh, origin, normal, u, v, to2d)

    solid_xy = []
    for outer, holes in regions_3d:
        outer_xy = [to2d(p) for p in outer]
        holes_xy = [[to2d(p) for p in h] for h in holes]
        ip = _region_test_point(outer_xy, holes_xy)
        if abs(_winding(ip, boundary)) > 0.5:
            solid_xy.append((outer_xy, holes_xy))

    merged = _union_outline(solid_xy)
    return [
        ([to3d(p) for p in outer], [[to3d(p) for p in h] for h in holes])
        for outer, holes in merged
    ]


def _coplanar_on(face, origin, normal) -> bool:
    return (
        abs(QVector3D.dotProduct(face.normal().normalized(), normal)) > 0.999
        and _on_plane(face.centroid(), origin, normal)
    )


def apply_rebuild(mesh, origin: QVector3D, normal: QVector3D) -> bool:
    """Rebuild one plane of ``mesh`` in place: replace its coplanar faces with the
    deterministic solid faces from :func:`rebuild_plane`, and prune the edges left
    interior to the plane (a dissolved seam) that now border nothing. Returns
    whether anything changed. No-op when the rebuild yields nothing to face.

    The caller snapshots for undo (the push wraps the whole mutation), so this
    keeps no inverse of its own."""
    normal = normal.normalized()
    rebuilt = rebuild_plane(mesh, origin, normal)
    if not rebuilt:
        return False
    old = [f for f in mesh.faces if _coplanar_on(f, origin, normal)]
    for f in old:
        mesh.remove_face(f)
    for outer, holes in rebuilt:
        mesh.add_face(outer, holes or None)
    # Drop edges that lie fully on the plane and ended up facing nothing — the
    # interior seams the union dissolved. Perimeter edges still border a wall, so
    # they keep a face and survive.
    for e in list(mesh.edges):
        if (not e.faces
                and _on_plane(e.a, origin, normal)
                and _on_plane(e.b, origin, normal)):
            mesh.remove_edge(e)
    return True


def crack_planes(mesh) -> list:
    """Representative ``(origin, normal)`` for each distinct plane that carries a
    crack — a boundary edge bordering a single face. These are the planes a
    nested push can leave unclosed, the ones :func:`apply_rebuild` should
    recompute (the deterministic replacement for ``cap_boundary_loops``)."""
    seen: dict = {}
    for e in mesh.edges:
        if len(e.faces) != 1:
            continue
        f = e.faces[0]
        n = f.normal().normalized()
        # Canonical normal (largest-magnitude component made positive) so the two
        # sides of a slab don't collide, but a face and its flip map to one plane.
        comps = (n.x(), n.y(), n.z())
        if comps[max(range(3), key=lambda i: abs(comps[i]))] < 0:
            n = -n
        d = QVector3D.dotProduct(n, f.centroid())
        key = (round(n.x(), 3), round(n.y(), 3), round(n.z(), 3), round(d, 3))
        if key not in seen:
            seen[key] = (f.centroid(), n)
    return list(seen.values())
