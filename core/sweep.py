# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Follow Me sweep: extrude a profile face along an edge path.

The discrete prism-miter construction: at every path vertex a *joint plane*
is placed (normal = bisector of the incoming and outgoing directions; at open
ends, the segment direction itself). The profile's ring at each station is
obtained by sliding the previous ring parallel to the incoming segment onto
the joint plane — the exact miter, so square corners join without pinching.
Closed paths connect the last span straight back to the first ring, welding
the loop with zero seam.

Headless engine API (the AI-native action layer): the tool is a thin click
shell over :func:`sweep_profile`.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.orient import is_closed, orient_outward
from core.history import run_stitch
from core.topology import _key

#: Dihedral cosine above which a sweep seam reads as a *curve* facet and is
#: softened (hidden) — same rule as Push/Pull's cylinder seams.
_CURVE_FACET_COS = 0.85


def order_path_edges(edges):
    """Chain the selected edges into an ordered polyline.

    Returns ``(points, closed)`` or ``None`` when the edges do not form one
    simple chain (branching, disjoint pieces)."""
    edges = list(edges)
    if not edges:
        return None
    adj: dict = {}
    for e in edges:
        adj.setdefault(e.v0, []).append(e.v1)
        adj.setdefault(e.v1, []).append(e.v0)
    if any(len(nbrs) > 2 for nbrs in adj.values()):
        return None                                  # branching
    ends = [v for v, nbrs in adj.items() if len(nbrs) == 1]
    if len(ends) not in (0, 2):
        return None
    closed = not ends
    start = ends[0] if ends else edges[0].v0
    pts = [QVector3D(start.position)]
    prev, cur = None, start
    for _ in range(len(edges)):
        nxt = next((v for v in adj[cur] if v is not prev), None)
        if nxt is None:
            return None
        pts.append(QVector3D(nxt.position))
        prev, cur = cur, nxt
    if closed:
        if cur is not start:
            return None                              # disjoint loops
        pts.pop()                                    # implicit wrap
    elif len(pts) != len(edges) + 1:
        return None                                  # disjoint chains
    return pts, closed


def _project_ring(points, direction, plane_pt, plane_n):
    """Slide each point parallel to ``direction`` onto the joint plane."""
    denom_dir = QVector3D.dotProduct(direction, plane_n)
    if abs(denom_dir) < 1e-9:
        return None                                  # segment ⟂ joint plane
    out = []
    for p in points:
        t = QVector3D.dotProduct(plane_pt - p, plane_n) / denom_dir
        out.append(p + direction * t)
    return out


def sweep_profile(mesh, face, path, closed) -> bool:
    """Sweep ``face`` (with holes) along ``path``; mutates ``mesh`` in place.

    Returns ``False`` (mesh untouched) on degenerate input — a 180° reversal
    in the path, a segment parallel to a joint plane, a zero-length span."""
    dirs = []
    n = len(path)
    spans = n if closed else n - 1
    for i in range(spans):
        d = path[(i + 1) % n] - path[i]
        if d.length() < 1e-9:
            return False
        dirs.append(d.normalized())

    def joint_normal(i):
        if closed:
            a, b = dirs[(i - 1) % spans], dirs[i % spans]
        elif i == 0:
            return dirs[0]
        elif i >= spans:
            return dirs[-1]
        else:
            a, b = dirs[i - 1], dirs[i]
        s = a + b
        if s.length() < 1e-9:
            return None                              # 180° reversal
        return s.normalized()

    loops = [[QVector3D(v) for v in face.vertices]]
    loops += [[QVector3D(v) for v in h] for h in face.holes]

    stations = n                                  # one ring per path vertex
    rings: list = []
    for i in range(stations):
        pn = joint_normal(i)
        if pn is None:
            return False
        anchor = path[i % n]
        if i == 0:
            ring = [_project_ring(lp, dirs[0], anchor, pn) for lp in loops]
        else:
            ring = [_project_ring(prev_lp, dirs[i - 1], anchor, pn)
                    for prev_lp in rings[-1]]
        if any(lp is None for lp in ring):
            return False
        rings.append(ring)

    # Build: walls per span per loop edge; the closed path's last span goes
    # straight back to ring 0 (exact weld, no seam).
    before_edges = set(mesh.edges)
    mesh.remove_face(face)                           # profile is consumed
    for s in range(spans):
        r0 = rings[s]
        r1 = rings[(s + 1) % stations] if closed else rings[s + 1]
        for lp0, lp1 in zip(r0, r1):
            m = len(lp0)
            for j in range(m):
                a, b = lp0[j], lp0[(j + 1) % m]
                b2, a2 = lp1[(j + 1) % m], lp1[j]
                quad = [a, b, b2, a2]
                # Skip degenerate quads (a span that doesn't move this edge).
                if (a - a2).length() < 1e-9 and (b - b2).length() < 1e-9:
                    continue
                mesh.add_face(quad)
    if not closed:
        mesh.add_face(list(reversed(rings[0][0])),
                      [list(reversed(h)) for h in rings[0][1:]] or None)
        mesh.add_face(rings[-1][0], rings[-1][1:] or None)

    seed = {_key(p) for ring in rings for lp in ring for p in lp}
    run_stitch(mesh, seed, None, coplanar_merge=False)
    # Soften the seams of a curved sweep (shallow dihedral between successive
    # spans) so a moulding around a circle reads smooth; real corners stay.
    for e in mesh.edges:
        if e in before_edges or e.soft or len(e.faces) != 2:
            continue
        d = QVector3D.dotProduct(e.faces[0].normal().normalized(),
                                 e.faces[1].normal().normalized())
        if _CURVE_FACET_COS < d < 0.99995:
            e.soft = True
    orient_outward(mesh)
    return True
