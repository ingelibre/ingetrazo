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


def sweep_rings(face, path, closed):
    """The profile's rings (outer loop + holes) at every path station.

    Returns ``(rings, dirs, spans)`` or ``None`` on degenerate input — a
    180° reversal in the path, a segment parallel to a joint plane, a
    zero-length span."""
    dirs = []
    n = len(path)
    spans = n if closed else n - 1
    if spans < 1:
        return None
    for i in range(spans):
        d = path[(i + 1) % n] - path[i]
        if d.length() < 1e-9:
            return None
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
            return None
        anchor = path[i % n]
        if i == 0:
            ring = [_project_ring(lp, dirs[0], anchor, pn) for lp in loops]
        else:
            ring = [_project_ring(prev_lp, dirs[i - 1], anchor, pn)
                    for prev_lp in rings[-1]]
        if any(lp is None for lp in ring):
            return None
        rings.append(ring)
    return rings, dirs, spans


def sweep_preview_faces(face, path, closed):
    """The sweep as plain polygons for a live preview — the walls of every
    span and, on an open path, the far cap. No stitch, no orientation, no
    mesh: the shape while it is still moving under the cursor."""
    from core.geometry import Face          # the preview polygon (attrs kw)
    got = sweep_rings(face, path, closed)
    if got is None:
        return []
    rings, _dirs, spans = got
    attrs = dict(face.attrs) if face.attrs else None
    stations = len(rings)
    out = []
    for s in range(spans):
        r0 = rings[s]
        r1 = rings[(s + 1) % stations] if closed else rings[s + 1]
        for lp0, lp1 in zip(r0, r1):
            m = len(lp0)
            for j in range(m):
                a, b = lp0[j], lp0[(j + 1) % m]
                b2, a2 = lp1[(j + 1) % m], lp1[j]
                if (a - a2).length() < 1e-9 and (b - b2).length() < 1e-9:
                    continue
                out.append(Face([a, b, b2, a2], attrs=attrs))
    if not closed:
        out.append(Face(list(rings[-1][0]), list(rings[-1][1:]) or None,
                        attrs=attrs))
    return out


# ---- Manual (dragged) paths — SketchUp's "click and drag along the path" --

def manual_path_start(face, edge, toward=None):
    """The first station(s) of a path dragged from the profile ``face`` over
    ``edge``. When the edge crosses the profile's plane the sweep starts
    at the crossing (the profile sits mid-edge); otherwise it starts at the
    endpoint nearest the profile. Returns ``(start_point | None,
    [Vertex, ...])``: the chain's vertices come after the start point."""
    c = face.centroid()
    n = face.normal().normalized()
    a, b = edge.v0, edge.v1
    da = QVector3D.dotProduct(a.position - c, n)
    db = QVector3D.dotProduct(b.position - c, n)
    if da * db < -1e-12:
        t = da / (da - db)
        p = a.position + (b.position - a.position) * t
        far = b
        if toward is not None and ((a.position - toward).length()
                                   < (b.position - toward).length()):
            far = a
        return p, [far]
    near, far = (a, b) if abs(da) <= abs(db) else (b, a)
    return None, [near, far]


def manual_path_extend(chain, edge, skip=None, limit=400) -> bool:
    """Grow — or shrink — a dragged path with the edge under the cursor.
    Returns True when the chain changed.

    - an edge touching the chain's end extends it (or backs up over the
      last segment when the cursor returns along it);
    - an edge lying earlier on the chain shrinks the path back to it;
    - anywhere else, the shortest run of connected edges bridges the gap,
      so a fast drag that skips segments of an arc still follows it.
    ``skip(edge)`` vetoes edges (those in the profile's plane)."""
    if not chain or (skip is not None and skip(edge)):
        return False
    last = chain[-1]
    v0, v1 = edge.v0, edge.v1
    ids = {id(v): i for i, v in enumerate(chain)}
    if last is v0 or last is v1:
        other = v1 if last is v0 else v0
        if len(chain) >= 2 and other is chain[-2]:
            chain.pop()                              # backing up
            return True
        if id(other) in ids:
            if other is chain[0] and len(chain) >= 3:
                chain.append(other)                  # the loop closes
                return True
            return False
        chain.append(other)
        return True
    if id(v0) in ids and id(v1) in ids:
        del chain[max(ids[id(v0)], ids[id(v1)]) + 1:]   # back to that edge
        return True
    route = _route(last, (v0, v1), skip, ids, limit)
    if route is None:
        return False
    chain.extend(route)
    reached = route[-1]
    other = v1 if reached is v0 else v0
    if id(other) not in ids and other is not reached:
        chain.append(other)
    return True


def _route(start, targets, skip, blocked_ids, limit):
    """Shortest run of edges (breadth-first) from ``start`` to either of
    ``targets``, never through vertices already on the chain."""
    from collections import deque
    prev = {id(start): None}
    seen = {id(start)}
    q = deque([start])
    hit = None
    steps = 0
    while q and steps < limit and hit is None:
        v = q.popleft()
        steps += 1
        for e in v.edges:
            if skip is not None and skip(e):
                continue
            w = e.v1 if e.v0 is v else e.v0
            if id(w) in seen or (id(w) in blocked_ids and w is not start):
                continue
            seen.add(id(w))
            prev[id(w)] = v
            if w is targets[0] or w is targets[1]:
                hit = w
                break
            q.append(w)
    if hit is None:
        return None
    route = []
    v = hit
    while v is not None and v is not start:
        route.append(v)
        v = prev[id(v)]
    route.reverse()
    return route


def orient_closed_path(pts, face):
    """A closed path as the sweep wants it: station 0 at the vertex nearest
    the profile, travelling the way whose FIRST segment stands closest to
    perpendicular to the profile (the profile is perpendicular to one
    segment at its corner; starting along the other collapses the first
    ring)."""
    pts = [QVector3D(p) for p in pts]
    if len(pts) < 3:
        return pts
    c = face.centroid()
    k = min(range(len(pts)), key=lambda i: (pts[i] - c).length())
    pts = pts[k:] + pts[:k]
    n = face.normal().normalized()
    fwd = pts[1] - pts[0]
    back = pts[-1] - pts[0]
    if fwd.length() > 1e-9 and back.length() > 1e-9:
        af = abs(QVector3D.dotProduct(fwd.normalized(), n))
        ab = abs(QVector3D.dotProduct(back.normalized(), n))
        if ab > af + 1e-9:
            pts = [pts[0]] + pts[1:][::-1]
    return pts


def sweep_profile(mesh, face, path, closed) -> bool:
    """Sweep ``face`` (with holes) along ``path``; mutates ``mesh`` in place.

    Returns ``False`` (mesh untouched) on degenerate input — a 180° reversal
    in the path, a segment parallel to a joint plane, a zero-length span."""
    got = sweep_rings(face, path, closed)
    if got is None:
        return False
    rings, _dirs, spans = got
    n = len(path)
    stations = n                                  # one ring per path vertex

    # Build: walls per span per loop edge; the closed path's last span goes
    # straight back to ring 0 (exact weld, no seam).
    before_edges = set(mesh.edges)
    profile_loops = [list(face.loop)] + [list(h) for h in face.hole_loops]
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

    # The profile's own edges go with it: when station 0 is a mitre (the
    # profile at a corner of a closed path) they no longer bound anything
    # and would stay behind as loose lines.
    for lp in profile_loops:
        n_lp = len(lp)
        for i in range(n_lp):
            e = mesh.find_edge(lp[i], lp[(i + 1) % n_lp])
            if e is not None and not e.faces:
                mesh.remove_edge(e)
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
