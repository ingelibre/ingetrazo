# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Hidden-line removal for the sheet composer (C4, docs/composer-plan.md).

Given the scene and a parallel camera, produce the VISIBLE portions of the
model's edges as true 2D vector segments — what a drafter would ink. The
math is EXACT, not sampled: along each projected edge, the region occluded
by one triangle is the intersection of four linear inequalities in the
edge parameter t (three half-planes of the triangle's convex projection
plus the depth comparison, all linear under a parallel projection), so
every (edge, triangle) pair contributes one exact interval; visibility is
[0,1] minus their union.

Self-occlusion needs no adjacency bookkeeping: an edge lies in the plane
of each face it bounds, so the depth difference e(t) is ~0 across the
whole edge and never beats the epsilon.

Curved surfaces: a soft edge is included only when its faces straddle the
view (one toward the camera, one away) — the same silhouette rule the
viewport draws with; soft edges with a single face are open boundaries
and always profile.

Everything here is NumPy over camera-space arrays; Qt types appear only
while reading the scene.
"""
from __future__ import annotations

import math

import numpy as np

#: Merge tolerance for the union of occluded intervals, in edge-parameter
#: units — gaps smaller than this are drafting dust, not visibility.
_T_EPS = 1e-6


# ── Camera basis ────────────────────────────────────────────────────────────

def camera_basis(camera):
    """Right/up/forward unit vectors + eye, as NumPy rows, from an
    OrbitCamera (same derivation as its lookAt)."""
    eye = camera.eye()
    e = np.array([eye.x(), eye.y(), eye.z()], dtype=np.float64)
    t = np.array([camera.target.x(), camera.target.y(),
                  camera.target.z()], dtype=np.float64)
    up_v = camera.up_vector() if hasattr(camera, "up_vector") else camera.up
    up = np.array([up_v.x(), up_v.y(), up_v.z()],
                  dtype=np.float64)
    f = t - e
    f /= max(np.linalg.norm(f), 1e-12)
    r = np.cross(f, up)
    r /= max(np.linalg.norm(r), 1e-12)
    u = np.cross(r, f)
    return e, r, u, f


def _to_cam(points: np.ndarray, eye, right, up, fwd) -> np.ndarray:
    """World (N,3) → camera space (N,3): x right, y up, z = depth AWAY
    from the camera (bigger = farther)."""
    d = points - eye
    return np.stack([d @ right, d @ up, d @ fwd], axis=1)


# ── Scene collection ────────────────────────────────────────────────────────

def collect_geometry(scene):
    """World-space triangles (T,3,3) and edge segments (E,2,3) of every
    visible, non-billboard entity; instance groups are baked through their
    transform. Soft edges come back separately with their two face normals
    (silhouette test happens per view)."""
    from core.group import world_mesh

    tris: list = []
    hard: list = []
    soft: list = []          # (p0, p1, n_a, n_b) — n_b None for boundaries

    def eat_mesh(mesh, visible=lambda _e: True):
        for face in mesh.faces:
            if not visible(face):
                continue
            for a, b, c in face.triangulate():
                tris.append(((a.x(), a.y(), a.z()),
                             (b.x(), b.y(), b.z()),
                             (c.x(), c.y(), c.z())))
        for e in mesh.edges:
            if not visible(e):
                continue
            p0 = (e.v0.position.x(), e.v0.position.y(), e.v0.position.z())
            p1 = (e.v1.position.x(), e.v1.position.y(), e.v1.position.z())
            if getattr(e, "hidden", False):
                continue
            if getattr(e, "soft", False):
                fs = [f for f in e.faces if visible(f)]
                if not fs:
                    continue
                na = fs[0].normal()
                nb = fs[1].normal() if len(fs) > 1 else None
                soft.append((p0, p1,
                             (na.x(), na.y(), na.z()),
                             None if nb is None
                             else (nb.x(), nb.y(), nb.z())))
            else:
                hard.append((p0, p1))

    eat_mesh(scene.loose_mesh, visible=scene.entity_visible)
    for g in scene.groups:
        if not scene.entity_visible(g) or getattr(g, "billboard", False):
            continue
        mesh = (world_mesh(g) if g.xform is not None or g.children
                else g.mesh)
        eat_mesh(mesh)
    return tris, hard, soft


def collect_circles(scene) -> list:
    """Every circle and arc the model carries, as ``(centre, radius,
    normal)`` in world space — the curves :func:`core.snap.curve_centers_of_face`
    reads off each visible face's boundary (a drawn circle, a rounded
    corner, a hole; an imported polyline by its shape), placements taken
    through their transform. It is what a sheet's radius / diameter tool
    recognises when the drafter clicks ON the arc, the way AutoCAD's
    DIMRADIUS asks for the arc and never for a centre nobody can see
    (Marco, 2026-09-20: «como que no reconoce el centro de un círculo»).
    The same curve on two faces (a hole and the pipe through it) is
    reported once."""
    from core.group import iter_placements
    from core.snap import curve_centers_of_face

    out: list = []
    seen: set = set()

    def eat(mesh, xform=None, visible=lambda _f: True):
        for face in mesh.faces:
            if not visible(face):
                continue
            n = face.normal()
            if xform is not None:
                n = xform.mapVector(n)
                if n.length() < 1e-9:
                    continue
                n.normalize()
            for c, r, _key in curve_centers_of_face(face, xform):
                key = (round(c.x(), 4), round(c.y(), 4), round(c.z(), 4),
                       round(r, 4), round(abs(n.x()), 3),
                       round(abs(n.y()), 3), round(abs(n.z()), 3))
                if key in seen:
                    continue
                seen.add(key)
                out.append((c, r, n))

    eat(scene.loose_mesh, visible=scene.entity_visible)
    for g in scene.groups:
        if not scene.entity_visible(g) or getattr(g, "billboard", False):
            continue
        for placed, m in iter_placements(g):
            eat(placed.mesh, m)
    return out


def clip_to_section(tris, hard, soft, plane, split_cuts: bool = False):
    """Clip collected geometry to the KEPT side of the active section plane
    (S5 — the point of the sections track): triangles are cut, edges are
    shortened, and the plane∩triangle intersection segments join the hard
    edges — the sheet composer's hidden-line pass then draws real plans and
    cross-sections. ``plane`` is a core.section.SectionPlane; the hidden
    side is where ``plane.side(p) > 0``.

    With ``split_cuts`` the chords come back as a fourth list instead of
    joining the hard edges — the drawing that inks them thicker and fills
    the poché needs to know which lines are the cut."""
    nx = plane.normal.x()
    ny = plane.normal.y()
    nz = plane.normal.z()
    c = (nx * plane.point.x() + ny * plane.point.y()
         + nz * plane.point.z())
    eps = 1e-9

    def dist(p):
        return p[0] * nx + p[1] * ny + p[2] * nz - c

    def lerp(a, b, da, db):
        t = da / (da - db)
        return (a[0] + (b[0] - a[0]) * t,
                a[1] + (b[1] - a[1]) * t,
                a[2] + (b[2] - a[2]) * t)

    out_tris: list = []
    cut_edges: list = []
    for tri in tris:
        d = (dist(tri[0]), dist(tri[1]), dist(tri[2]))
        hidden = [di > eps for di in d]
        nh = sum(hidden)
        if nh == 0:
            out_tris.append(tri)
            continue
        if nh == 3:
            continue
        # Clip the polygon against the plane (Sutherland–Hodgman, keep
        # d <= 0) and remember the crossing chord — the section-cut line.
        poly: list = []
        crossings: list = []
        for i in range(3):
            a, b = tri[i], tri[(i + 1) % 3]
            da, db = d[i], d[(i + 1) % 3]
            if da <= eps:
                poly.append(a)
            if (da > eps) != (db > eps):
                x = lerp(a, b, da, db)
                poly.append(x)
                crossings.append(x)
        if len(crossings) == 2:
            cut_edges.append((crossings[0], crossings[1]))
        for i in range(1, len(poly) - 1):     # fan
            out_tris.append((poly[0], poly[i], poly[i + 1]))

    def clip_seg(p0, p1):
        d0, d1 = dist(p0), dist(p1)
        if d0 > eps and d1 > eps:
            return None
        if d0 <= eps and d1 <= eps:
            return (p0, p1)
        x = lerp(p0, p1, d0, d1)
        return (p0, x) if d0 <= eps else (x, p1)

    out_hard: list = []
    for p0, p1 in hard:
        seg = clip_seg(p0, p1)
        if seg is not None:
            out_hard.append(seg)
    if not split_cuts:
        out_hard.extend(cut_edges)
    out_soft: list = []
    for p0, p1, na, nb in soft:
        seg = clip_seg(p0, p1)
        if seg is not None:
            out_soft.append((seg[0], seg[1], na, nb))
    if split_cuts:
        return out_tris, out_hard, out_soft, cut_edges
    return out_tris, out_hard, out_soft


def section_loops(cut_edges, tol: float | None = None) -> list:
    """Chain the plane∩triangle chords of a section cut into CLOSED loops —
    the outlines of the solids the plane slices through, i.e. the areas a
    drafter fills with poché. Returns a list of (M, 3) arrays in world
    space, each a closed ring (first point not repeated).

    A watertight solid triangulated conformingly yields chords whose
    endpoints meet two by two, so walking the adjacency closes every ring;
    a chain that dead-ends (an open surface: a lone wall face, a roof
    without walls) is dropped rather than filled — SketchUp's own section
    fill leaks on those, we prefer to leave them white. Nested rings (a
    hollow wall, a pipe) are the caller's even-odd fill rule."""
    if not len(cut_edges):
        return []
    E = np.asarray(cut_edges, dtype=np.float64).reshape(-1, 2, 3)
    if tol is None:
        span = float((E.max(axis=(0, 1)) - E.min(axis=(0, 1))).max())
        tol = max(span * 1e-7, 1e-9)
    # Endpoints → node ids, merging anything closer than tol (a 3×3×3
    # neighbourhood of quantised cells, so a point on a cell boundary still
    # finds its twin on the other side).
    cells: dict = {}
    nodes: list = []
    inv = 1.0 / tol

    def node_of(pt) -> int:
        cx, cy, cz = (int(math.floor(pt[0] * inv)),
                      int(math.floor(pt[1] * inv)),
                      int(math.floor(pt[2] * inv)))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for i in cells.get((cx + dx, cy + dy, cz + dz), ()):
                        q = nodes[i]
                        if (abs(q[0] - pt[0]) <= tol
                                and abs(q[1] - pt[1]) <= tol
                                and abs(q[2] - pt[2]) <= tol):
                            return i
        nodes.append((float(pt[0]), float(pt[1]), float(pt[2])))
        cells.setdefault((cx, cy, cz), []).append(len(nodes) - 1)
        return len(nodes) - 1

    adj: dict = {}
    chords: list = []
    for k in range(len(E)):
        a = node_of(E[k, 0])
        b = node_of(E[k, 1])
        if a == b:
            continue                    # a triangle touching the plane at a point
        idx = len(chords)
        chords.append((a, b))
        adj.setdefault(a, []).append(idx)
        adj.setdefault(b, []).append(idx)
    used = [False] * len(chords)
    loops: list = []
    for start in range(len(chords)):
        if used[start]:
            continue
        a0, b0 = chords[start]
        used[start] = True
        ring = [a0, b0]
        cur, prev_chord = b0, start
        closed = False
        while True:
            nxt = None
            for c in adj.get(cur, ()):
                if c != prev_chord and not used[c]:
                    nxt = c
                    break
            if nxt is None:
                break
            used[nxt] = True
            x, y = chords[nxt]
            cur = y if x == cur else x
            prev_chord = nxt
            if cur == a0:
                closed = True
                break
            ring.append(cur)
        if closed and len(ring) >= 3:
            loops.append(np.asarray([nodes[i] for i in ring],
                                    dtype=np.float64))
    return loops


# ── The exact visibility kernel ─────────────────────────────────────────────

def _interval_from_linear(c0: float, c1: float):
    """Solve c0 + c1·t ≥ 0 over [0,1] → (lo, hi) or None."""
    if abs(c1) < 1e-15:
        return (0.0, 1.0) if c0 >= 0.0 else None
    t = -c0 / c1
    return (t, 1.0) if c1 > 0.0 else (0.0, t)


def visible_spans(a2, b2, az, bz, tv2, tvz, eps: float):
    """Visible t-intervals of ONE edge against candidate triangles.

    ``a2``/``b2``: edge endpoints in 2D cam coords; ``az``/``bz`` depths;
    ``tv2`` (K,3,2) candidate triangle 2D verts; ``tvz`` (K,3) depths."""
    d2 = b2 - a2
    occluded: list = []
    for k in range(len(tv2)):
        v = tv2[k]
        area2 = ((v[1, 0] - v[0, 0]) * (v[2, 1] - v[0, 1])
                 - (v[1, 1] - v[0, 1]) * (v[2, 0] - v[0, 0]))
        if abs(area2) < 1e-14:
            continue                    # edge-on: its own edges draw it
        z = tvz[k]
        if area2 < 0.0:                 # enforce CCW
            v = v[::-1]
            z = z[::-1]
        lo, hi = 0.0, 1.0
        dead = False
        # three half-planes of the projected triangle
        for i in range(3):
            ex, ey = v[(i + 1) % 3] - v[i]
            # inside: cross(edge_i, p - v_i) >= 0
            c0 = ex * (a2[1] - v[i, 1]) - ey * (a2[0] - v[i, 0])
            c1 = ex * d2[1] - ey * d2[0]
            iv = _interval_from_linear(c0, c1)
            if iv is None:
                dead = True
                break
            lo, hi = max(lo, iv[0]), min(hi, iv[1])
            if lo >= hi:
                dead = True
                break
        if dead:
            continue
        # depth: triangle plane z(x, y) = alpha·x + beta·y + gamma
        m = np.array([[v[0, 0], v[0, 1], 1.0],
                      [v[1, 0], v[1, 1], 1.0],
                      [v[2, 0], v[2, 1], 1.0]])
        try:
            abg = np.linalg.solve(m, z)
        except np.linalg.LinAlgError:
            continue
        # occluded where edge depth > tri depth + eps (farther than the tri)
        # e(t) = (az + t(bz-az)) - (alpha·x(t) + beta·y(t) + gamma) - eps > 0
        c0 = (az - (abg[0] * a2[0] + abg[1] * a2[1] + abg[2]) - eps)
        c1 = ((bz - az) - (abg[0] * d2[0] + abg[1] * d2[1]))
        iv = _interval_from_linear(c0, c1)
        if iv is None:
            continue
        lo, hi = max(lo, iv[0]), min(hi, iv[1])
        if lo < hi:
            occluded.append((lo, hi))

    if not occluded:
        return [(0.0, 1.0)]
    occluded.sort()
    merged = [list(occluded[0])]
    for lo, hi in occluded[1:]:
        if lo <= merged[-1][1] + _T_EPS:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    visible: list = []
    cursor = 0.0
    for lo, hi in merged:
        if lo > cursor + _T_EPS:
            visible.append((cursor, min(lo, 1.0)))
        cursor = max(cursor, hi)
        if cursor >= 1.0:
            break
    if cursor < 1.0 - _T_EPS:
        visible.append((cursor, 1.0))
    return visible


# ── The section cap: the poché covers ───────────────────────────────────────
#
# A section cut leaves the solid OPEN: the clipper throws the hidden half
# away and nothing closes the hole, so the hidden-line pass still sees
# straight through the wall it just sliced and inks whatever sits behind —
# the far end of the board, the next divider — right across the poché.
# «Tapa pero no tapa», said Rafael, and the fill mode made no difference:
# the fill is painted UNDER the lines.
#
# So the rings the composer fills are also an OCCLUDER, exactly the same
# region under exactly the same even-odd rule: whatever lies strictly
# behind the cut plane and inside the poché is inside solid material, and
# solid material is not see-through. The cut chords themselves sit ON the
# plane, so they are never their own victims and the outline always survives.


def cap_depth_affine(plane, eye, right, up, fwd):
    """``(alpha, beta, gamma)`` with the cut plane's camera depth given by
    ``alpha·x + beta·y + gamma`` over the camera plane — a parallel camera
    maps a plane to a plane. ``None`` when the cut is seen edge-on: its cap
    projects to a line and covers nothing."""
    from core.triangulate import plane_axes
    u, v = plane_axes(plane.normal)
    p = plane.point
    pts = np.array([[p.x(), p.y(), p.z()],
                    [p.x() + u.x(), p.y() + u.y(), p.z() + u.z()],
                    [p.x() + v.x(), p.y() + v.y(), p.z() + v.z()]],
                   dtype=np.float64)
    c = _to_cam(pts, eye, right, up, fwd)
    area2 = ((c[1, 0] - c[0, 0]) * (c[2, 1] - c[0, 1])
             - (c[1, 1] - c[0, 1]) * (c[2, 0] - c[0, 0]))
    if abs(area2) < 1e-9:
        return None
    m = np.array([[c[0, 0], c[0, 1], 1.0],
                  [c[1, 0], c[1, 1], 1.0],
                  [c[2, 0], c[2, 1], 1.0]])
    try:
        return np.linalg.solve(m, c[:, 2])
    except np.linalg.LinAlgError:
        return None


def cap_ring_edges(loops):
    """Every ring of the cap as one pair of (K, 2) endpoint arrays ``P→Q``.
    Stacking all the rings together IS the even-odd rule: a hollow wall's
    inner ring flips the parity back, so its hole stays see-through."""
    if not loops:
        return None, None
    P = np.concatenate([np.asarray(r, dtype=np.float64)[:, :2] for r in loops])
    Q = np.concatenate([np.roll(np.asarray(r, dtype=np.float64)[:, :2], -1,
                                axis=0) for r in loops])
    return P, Q


def _inside_cap(px: float, py: float, P, Q) -> bool:
    """Even-odd point-in-region over the stacked ring edges (ray to +x)."""
    y0 = P[:, 1]
    y1 = Q[:, 1]
    hit = (y0 > py) != (y1 > py)
    if not hit.any():
        return False
    ya, yb = y0[hit], y1[hit]
    xa, xb = P[hit, 0], Q[hit, 0]
    xi = xa + (xb - xa) * (py - ya) / (yb - ya)
    return bool(int((xi > px).sum()) & 1)


def cap_hidden_spans(a2, b2, az, bz, P, Q, abg, eps: float):
    """t-intervals of ONE edge that the section cap hides: behind the cut
    plane AND inside the filled region. Sorted and disjoint."""
    d2 = b2 - a2
    behind = _interval_from_linear(
        float(az - (abg[0] * a2[0] + abg[1] * a2[1] + abg[2]) - eps),
        float((bz - az) - (abg[0] * d2[0] + abg[1] * d2[1])))
    if behind is None:
        return []
    lo, hi = max(0.0, behind[0]), min(1.0, behind[1])
    if hi - lo <= _T_EPS:
        return []
    # Where the edge crosses the outline, the parity — and so the answer —
    # flips: cut it there and ask each piece once, at its midpoint. A
    # crossing counted twice only splits a piece in two that agree.
    e = Q - P
    w = P - a2
    denom = d2[0] * e[:, 1] - d2[1] * e[:, 0]
    ok = np.abs(denom) > 1e-15
    cuts = np.empty(0, dtype=np.float64)
    if ok.any():
        dn = denom[ok]
        t = (w[ok, 0] * e[ok, 1] - w[ok, 1] * e[ok, 0]) / dn
        s = (w[ok, 0] * d2[1] - w[ok, 1] * d2[0]) / dn
        m = (s >= 0.0) & (s <= 1.0) & (t > lo) & (t < hi)
        cuts = np.sort(t[m])
    bounds = np.concatenate(([lo], cuts, [hi]))
    out: list = []
    for i in range(len(bounds) - 1):
        t0, t1 = float(bounds[i]), float(bounds[i + 1])
        if t1 - t0 <= _T_EPS:
            continue
        tm = (t0 + t1) * 0.5
        if _inside_cap(a2[0] + tm * d2[0], a2[1] + tm * d2[1], P, Q):
            if out and t0 - out[-1][1] <= _T_EPS:
                out[-1] = (out[-1][0], t1)
            else:
                out.append((t0, t1))
    return out


def subtract_spans(spans, hidden):
    """``spans`` minus ``hidden`` (both sorted, disjoint, within [0,1])."""
    if not hidden:
        return spans
    out: list = []
    for lo, hi in spans:
        cur = lo
        for c0, c1 in hidden:
            if c1 <= cur or c0 >= hi:
                continue
            if c0 - cur > _T_EPS:
                out.append((cur, min(c0, hi)))
            cur = max(cur, c1)
            if cur >= hi:
                break
        if hi - cur > _T_EPS:
            out.append((cur, hi))
    return out


def _geometry_as_lists(tris, hard, soft, soft_n):
    """Array geometry → the tuple lists ``clip_to_section`` walks."""
    t = [tuple(map(tuple, tri)) for tri in np.asarray(tris).tolist()]
    h = [(tuple(a), tuple(b)) for a, b in np.asarray(hard).tolist()]
    s = []
    for (p0, p1), (na, nb) in zip(np.asarray(soft).tolist(),
                                  np.asarray(soft_n).tolist()):
        open_edge = any(x != x for x in nb)            # NaN = no 2nd face
        s.append((tuple(p0), tuple(p1), tuple(na),
                  None if open_edge else tuple(nb)))
    return t, h, s


#: Line classes of a drawing, per segment (``HlrDrawing.kinds``).
KIND_EDGE = 0        #: a plain edge between two visible faces
KIND_PROFILE = 1     #: silhouette / outline against the background (SketchUp's Profiles)
KIND_CUT = 2         #: the section plane slicing through a solid
KIND_HIDDEN = 3      #: the part of an edge something stands in front of (dashed)


class HlrDrawing:
    """What :func:`hlr_drawing` returns: the visible segments in the camera
    plane (``segs`` (N,4)), their world endpoints (``world`` (N,2,3)),
    a class per segment (``kinds`` (N,) int8 — KIND_EDGE / KIND_PROFILE /
    KIND_CUT) and the closed section-cut rings to fill (``loops``, a list
    of (M,2) arrays in the camera plane)."""

    __slots__ = ("segs", "world", "kinds", "loops")

    def __init__(self, segs, world, kinds, loops):
        self.segs = segs
        self.world = world
        self.kinds = kinds
        self.loops = loops

    def __len__(self) -> int:
        return len(self.segs)


def _surface_at(p, depth, tv2, tvz, tol) -> bool:
    """Does any of the triangles (K,3,2)/(K,3) cover the camera-plane point
    ``p`` with a surface no farther than ``depth + tol``? The adjacency test
    behind SketchUp's Profiles: a visible edge with a covered point on each
    side runs between two surfaces; an uncovered side is the background (or
    a surface well behind) — the edge outlines the shape."""
    if not len(tv2):
        return False
    a = tv2[:, 0]
    v0 = tv2[:, 1] - a
    v1 = tv2[:, 2] - a
    v2 = p - a
    den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
    ok = np.abs(den) > 1e-18
    den = np.where(ok, den, 1.0)
    l1 = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / den
    l2 = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / den
    l0 = 1.0 - l1 - l2
    inside = ok & (l0 >= -1e-9) & (l1 >= -1e-9) & (l2 >= -1e-9)
    if not inside.any():
        return False
    z = l0 * tvz[:, 0] + l1 * tvz[:, 1] + l2 * tvz[:, 2]
    return bool(np.any(inside & (z <= depth + tol)))


def _drop_hidden_under_visible(segs, world, kinds, tol: float):
    """A hidden line that falls on a visible one is not drawn — the
    visible line wins (the back edges of a wall seen from the front lie
    exactly under its front outline). Segments are grouped by their line
    (direction and offset, rounded), so this stays linear in the drawing
    and each hidden piece is only compared with the visible pieces on its
    own line."""
    hid = np.nonzero(kinds == KIND_HIDDEN)[0]
    if not len(hid):
        return segs, world, kinds
    atol = 1e-6                                   # radians
    inv_d = 1.0 / max(tol, 1e-12)

    def key_and_span(row):
        x0, y0, x1, y1 = row
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy)
        if ln < 1e-15:
            return None
        ux, uy = dx / ln, dy / ln
        if ux < -1e-12 or (abs(ux) <= 1e-12 and uy < 0):
            ux, uy = -ux, -uy                     # one direction per line
        ang = math.atan2(uy, ux)
        off = ux * y0 - uy * x0                   # signed distance of line
        t0, t1 = ux * x0 + uy * y0, ux * x1 + uy * y1
        return ((round(ang / atol), round(off * inv_d)),
                (min(t0, t1), max(t0, t1)))

    lines: dict = {}
    for i in np.nonzero(kinds != KIND_HIDDEN)[0]:
        ks = key_and_span(segs[i])
        if ks is not None:
            lines.setdefault(ks[0], []).append(ks[1])
    if not lines:
        return segs, world, kinds
    keep_s, keep_w, keep_k = [], [], []
    for i in range(len(segs)):
        if kinds[i] != KIND_HIDDEN:
            keep_s.append(segs[i]); keep_w.append(world[i])
            keep_k.append(kinds[i])
            continue
        ks = key_and_span(segs[i])
        if ks is None:
            continue
        (ka, ko), (lo, hi) = ks
        # Hidden pieces already kept cover the line too: a box's front and
        # back edges fall on the same line on paper, once is enough.
        lines_here = lines
        cover = []
        for da in (-1, 0, 1):
            for do in (-1, 0, 1):
                cover.extend(lines.get((ka + da, ko + do), ()))
        if not cover:
            keep_s.append(segs[i]); keep_w.append(world[i])
            keep_k.append(kinds[i])
            lines_here.setdefault((ka, ko), []).append((lo, hi))
            continue
        span = hi - lo
        if span < 1e-15:
            continue
        cover = sorted(((max(0.0, (c0 - lo) / span),
                         min(1.0, (c1 - lo) / span))
                        for c0, c1 in cover if c1 > lo and c0 < hi))
        merged: list = []
        for c0, c1 in cover:
            if merged and c0 <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], c1))
            else:
                merged.append((c0, c1))
        # The segment may run either way along its line.
        x0, y0, x1, y1 = segs[i]
        ux = (x1 - x0) / (math.hypot(x1 - x0, y1 - y0))
        uy = (y1 - y0) / (math.hypot(x1 - x0, y1 - y0))
        forward = ux > 1e-12 or (abs(ux) <= 1e-12 and uy > 0)
        w0, w1 = world[i, 0, :], world[i, 1, :]
        for t0, t1 in subtract_spans([(0.0, 1.0)], merged):
            a, b = (t0, t1) if forward else (1.0 - t1, 1.0 - t0)
            keep_s.append((x0 + a * (x1 - x0), y0 + a * (y1 - y0),
                           x0 + b * (x1 - x0), y0 + b * (y1 - y0)))
            keep_w.append((w0 + a * (w1 - w0), w0 + b * (w1 - w0)))
            keep_k.append(KIND_HIDDEN)
            lines_here.setdefault((ka, ko), []).append(
                (lo + t0 * span, lo + t1 * span))
    return (np.asarray(keep_s, dtype=float).reshape(-1, 4),
            np.asarray(keep_w, dtype=float).reshape(-1, 2, 3),
            np.asarray(keep_k, dtype=np.int8))


def _merge_collinear(segs, world, kinds, tol: float):
    """Join runs of segments of one class that meet end to end and run
    collinear in 3D — the chords of a section through a triangulated face
    meet at the triangle's diagonal, an edge comes back from the
    visibility pass in pieces — into single segments. Cleaner ink (no
    round-cap seams), fewer DXF lines, honest anchor points."""
    n = len(segs)
    if n < 2:
        return segs, world, kinds
    inv = 1.0 / tol
    cells: dict = {}
    for i in range(n):
        for end in (0, 1):
            x, y = segs[i, 2 * end], segs[i, 2 * end + 1]
            cells.setdefault((int(math.floor(x * inv)),
                              int(math.floor(y * inv))), []).append((i, end))

    def at(x, y):
        cx, cy = int(math.floor(x * inv)), int(math.floor(y * inv))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i, end in cells.get((cx + dx, cy + dy), ()):
                    yield i, end

    used = np.zeros(n, dtype=bool)
    out_s, out_w, out_k = [], [], []

    def follow(i, end, wdir):
        """From segment i's endpoint ``end`` walk over collinear
        neighbours; returns the far endpoint reached (2D, world)."""
        p2 = segs[i, 2 * end:2 * end + 2]
        pw = world[i, end]
        while True:
            nxt = None
            for j, jend in at(p2[0], p2[1]):
                if j == i or used[j] or kinds[j] != kinds[i]:
                    continue
                q2 = segs[j, 2 * jend:2 * jend + 2]
                if abs(q2[0] - p2[0]) > tol or abs(q2[1] - p2[1]) > tol:
                    continue
                if np.max(np.abs(world[j, jend] - pw)) > tol:
                    continue
                other = world[j, 1 - jend] - world[j, jend]
                ln = float(np.linalg.norm(other))
                if ln < 1e-15:
                    continue
                cr = np.cross(wdir, other / ln)
                if float(np.dot(cr, cr)) > 1e-14 or float(np.dot(wdir, other)) <= 0:
                    continue
                nxt = (j, jend)
                break
            if nxt is None:
                return p2, pw
            j, jend = nxt
            used[j] = True
            p2 = segs[j, 2 * (1 - jend):2 * (1 - jend) + 2]
            pw = world[j, 1 - jend]

    for i in range(n):
        if used[i]:
            continue
        used[i] = True
        d = world[i, 1] - world[i, 0]
        ln = float(np.linalg.norm(d))
        if ln < 1e-15:
            out_s.append(segs[i]); out_w.append(world[i]); out_k.append(kinds[i])
            continue
        wdir = d / ln
        b2, bw = follow(i, 1, wdir)
        a2, aw = follow(i, 0, -wdir)
        out_s.append((a2[0], a2[1], b2[0], b2[1]))
        out_w.append((aw, bw))
        out_k.append(kinds[i])
    return (np.asarray(out_s, dtype=np.float64).reshape(-1, 4),
            np.asarray(out_w, dtype=np.float64).reshape(-1, 2, 3),
            np.asarray(out_k, dtype=np.int8))


def hlr_drawing(scene, camera, geometry=None, profiles: bool = True,
                fills: bool = True, caps: bool = True,
                hidden: bool = False) -> HlrDrawing:
    """The full line drawing of *scene* under *camera* (parallel): visible
    segments classified as edge / profile / cut, plus the section-cut
    rings to fill. :func:`hlr_view` is the segments-only view of this.

    Profiles (SketchUp's): soft edges where the surface turns away from the
    eye (and open boundaries), and hard edges with the background on one
    side — tested in 2D a hair off the visible segment's midpoint, so a
    lone face's outline, a box's contour and the eave of a roof all come out
    thick while the edges between two lit faces stay thin. ``profiles=False``
    skips the test (every non-cut line is KIND_EDGE).

    Fills: the chords of the active section chained into closed rings
    (:func:`section_loops`), projected to the camera plane.

    Caps: those same rings also OCCLUDE — whatever lies strictly behind the
    cut plane and inside the filled region is inside solid material, and a
    poché that lets the far side of the board show through «tapa pero no
    tapa» (Rafael, 2026-09-16). The cut chords lie ON the plane, so the
    outline of the cut always survives. ``caps=False`` draws the open
    silhouette instead.

    Hidden lines (``hidden=True``, issue #81, @pacaeiro: «I expected that
    Hidden line will show hidden lines of the model as dashed lines —
    that's the standard»): the parts of the hard edges that something
    stands in front of come back too, as KIND_HIDDEN, for the sheet to ink
    dashed. What lies inside the material behind a section cut stays out,
    as on a drawn section; silhouettes and cut chords have no hidden part.

    ``geometry`` — optional pre-collected arrays ``(tris, hard, soft,
    soft_n)`` as ``Viewport.hlr_geometry()`` returns them (world space:
    tris (T,3,3), hard (E,2,3), soft (S,2,3), soft_n (S,2,3) with NaN for
    an open boundary's missing second normal). Skips the per-face Python
    walk of :func:`collect_geometry` — 5 s on a 106k-triangle fountain —
    and runs the silhouette rule vectorised."""
    soft_n = None
    if geometry is None:
        tris, hard, soft = collect_geometry(scene)
    else:
        tris, hard, soft, soft_n = geometry
    # Active section cut (SketchUp): the composer's sheets honour it — the
    # whole reason sections exist here (plans and cross-cuts on paper).
    sp = (scene.active_section()
          if getattr(scene, "show_section_cuts", True)
          and hasattr(scene, "active_section") else None)
    cut_edges: list = []
    if sp is not None:
        if soft_n is not None:          # the clipper walks tuple lists
            tris, hard, soft = _geometry_as_lists(tris, hard, soft, soft_n)
            soft_n = None
        tris, hard, soft, cut_edges = clip_to_section(
            tris, hard, soft, sp, split_cuts=True)
    _e, _r, _u, fwd = camera_basis(camera)

    def empty_drawing():
        return HlrDrawing(np.empty((0, 4)), np.empty((0, 2, 3)),
                          np.empty((0,), dtype=np.int8), [])

    n_hard = len(hard)
    if soft_n is not None:
        # silhouette rule, vectorised: a soft edge is a profile where its
        # two faces face opposite ways, or where it bounds an open surface.
        hard = np.asarray(hard, dtype=np.float64).reshape(-1, 2, 3)
        if len(soft):
            fa = np.asarray(soft_n)[:, 0, :] @ fwd
            fb = np.asarray(soft_n)[:, 1, :] @ fwd
            mask = np.isnan(fb) | ((fa < 0.0) != (fb < 0.0))
            hard = np.concatenate(
                [hard, np.asarray(soft, dtype=np.float64)[mask]])
        if not len(hard) and not len(cut_edges):
            return empty_drawing()
    else:
        # silhouette rule for soft edges
        for p0, p1, na, nb in soft:
            fa = float(np.dot(np.asarray(na), fwd))
            if nb is None:
                hard.append((p0, p1))   # open boundary: always a profile
            else:
                fb = float(np.dot(np.asarray(nb), fwd))
                if (fa < 0.0) != (fb < 0.0):
                    hard.append((p0, p1))
        if not hard and not cut_edges:
            return empty_drawing()
    # Row layout of E: [hard edges | soft silhouettes | cut chords] — the
    # class of a row follows from its index.
    n_sil = len(hard) - n_hard
    parts = [np.asarray(hard, dtype=np.float64).reshape(-1, 2, 3)]
    if len(cut_edges):
        parts.append(np.asarray(cut_edges, dtype=np.float64).reshape(-1, 2, 3))
    eye, right, up, fwd = camera_basis(camera)
    E = np.concatenate(parts) if len(parts) > 1 else parts[0]   # (E,2,3)
    A = _to_cam(E[:, 0, :], eye, right, up, fwd)
    B = _to_cam(E[:, 1, :], eye, right, up, fwd)
    if len(tris):
        T = np.asarray(tris, dtype=np.float64)          # (T,3,3)
        TC = _to_cam(T.reshape(-1, 3), eye, right, up, fwd).reshape(-1, 3, 3)
        tv2 = TC[:, :, :2]
        tvz = TC[:, :, 2]
        # depth-based epsilon: relative to the scene's depth span
        span = float(tvz.max() - tvz.min()) or 1.0
        eps = max(span * 1e-4, 1e-9)
        tmin = tv2.min(axis=1)                          # (T,2)
        tmax = tv2.max(axis=1)
        tzmin = tvz.min(axis=1)
        # the sideways probe of the profile test: a hair, in drawing units
        ext = float((tv2.reshape(-1, 2).max(axis=0)
                     - tv2.reshape(-1, 2).min(axis=0)).max()) or 1.0
        delta = max(ext * 1e-4, 1e-9)
        # a surface counts as adjacent up to slope 10 (≈ 84°) — steeper
        # faces are silhouettes to the eye anyway
        ptol = eps + delta * 10.0
    else:
        tv2 = tvz = None
        eps = 0.0
        delta = ptol = 0.0

    ab = np.concatenate([A[:, :2], B[:, :2]])
    ext_e = float((ab.max(axis=0) - ab.min(axis=0)).max()) or 1.0
    zero_len = ext_e * 1e-9             # a vertical seen end-on: a point
    # The section cap: the rings the composer fills also COVER (see above).
    loops: list = []
    cap_P = cap_Q = cap_abg = None
    cap_eps = 0.0
    cap_box = None
    if len(cut_edges):
        for ring in section_loops(cut_edges):
            loops.append(_to_cam(ring, eye, right, up, fwd)[:, :2])
        if loops and caps:
            cap_abg = cap_depth_affine(sp, eye, right, up, fwd)
        if cap_abg is not None:
            cap_P, cap_Q = cap_ring_edges(loops)
            zs = np.concatenate([A[:, 2], B[:, 2]])
            cap_eps = max(float(zs.max() - zs.min()) * 1e-4, eps, 1e-9)
            cap_box = (cap_P.min(axis=0), cap_P.max(axis=0))
    out: list = []
    out_w: list = []
    out_k: list = []
    for i in range(len(A)):
        a2, b2 = A[i, :2], B[i, :2]
        az, bz = A[i, 2], B[i, 2]
        is_cut = i >= n_hard + n_sil
        base_kind = (KIND_CUT if is_cut
                     else KIND_PROFILE if i >= n_hard else KIND_EDGE)
        if tv2 is None:
            spans = [(0.0, 1.0)]
            idx = None
        else:
            lo = np.minimum(a2, b2) - 1e-9
            hi = np.maximum(a2, b2) + 1e-9
            cand = ~((tmax[:, 0] < lo[0]) | (tmin[:, 0] > hi[0])
                     | (tmax[:, 1] < lo[1]) | (tmin[:, 1] > hi[1]))
            # a triangle entirely behind both endpoints' nearest depth can
            # never occlude — quick reject
            cand &= tzmin < max(az, bz)
            idx = np.nonzero(cand)[0]
            if len(idx) == 0:
                spans = [(0.0, 1.0)]
            else:
                spans = visible_spans(a2, b2, az, bz,
                                      tv2[idx], tvz[idx], eps)
        # The hidden part: the rest of the edge, before the section cap
        # takes what lies inside the material (that is not drawn at all).
        hid = (subtract_spans([(0.0, 1.0)], spans)
               if hidden and i < n_hard else [])
        if cap_abg is not None and (spans or hid):
            elo = np.minimum(a2, b2)
            ehi = np.maximum(a2, b2)
            if not (ehi[0] < cap_box[0][0] or elo[0] > cap_box[1][0]
                    or ehi[1] < cap_box[0][1] or elo[1] > cap_box[1][1]):
                inside = cap_hidden_spans(a2, b2, az, bz, cap_P, cap_Q,
                                          cap_abg, cap_eps)
                spans = subtract_spans(spans, inside)
                hid = subtract_spans(hid, inside)
        for t0, t1 in hid:
            if (t1 - t0) < 1e-9:
                continue
            p = a2 + t0 * (b2 - a2)
            q = a2 + t1 * (b2 - a2)
            if math.hypot(q[0] - p[0], q[1] - p[1]) < zero_len:
                continue
            out.append((p[0], p[1], q[0], q[1]))
            out_k.append(KIND_HIDDEN)
            w0, w1 = E[i, 0, :], E[i, 1, :]
            out_w.append((w0 + t0 * (w1 - w0), w0 + t1 * (w1 - w0)))
        for t0, t1 in spans:
            if (t1 - t0) < 1e-9:
                continue
            p = a2 + t0 * (b2 - a2)
            q = a2 + t1 * (b2 - a2)
            if math.hypot(q[0] - p[0], q[1] - p[1]) < zero_len:
                continue
            kind = base_kind
            if (profiles and kind == KIND_EDGE and tv2 is not None):
                # Profile test: probe a hair to each side of the visible
                # span's midpoint; background on either side = outline.
                d = q - p
                ln = math.hypot(d[0], d[1])
                if ln > 1e-12:
                    nrm = np.array([-d[1] / ln, d[0] / ln]) * delta
                    mid = (p + q) * 0.5
                    tm = (t0 + t1) * 0.5
                    zm = az + tm * (bz - az)
                    lo2 = mid - delta * 1.001
                    hi2 = mid + delta * 1.001
                    near = ~((tmax[:, 0] < lo2[0]) | (tmin[:, 0] > hi2[0])
                             | (tmax[:, 1] < lo2[1]) | (tmin[:, 1] > hi2[1]))
                    near &= tzmin <= zm + ptol
                    nid = np.nonzero(near)[0]
                    if (not _surface_at(mid + nrm, zm, tv2[nid], tvz[nid],
                                        ptol)
                            or not _surface_at(mid - nrm, zm, tv2[nid],
                                               tvz[nid], ptol)):
                        kind = KIND_PROFILE
            out.append((p[0], p[1], q[0], q[1]))
            out_k.append(kind)
            w0, w1 = E[i, 0, :], E[i, 1, :]
            out_w.append((w0 + t0 * (w1 - w0), w0 + t1 * (w1 - w0)))
    segs = np.asarray(out) if out else np.empty((0, 4))
    world = np.asarray(out_w) if out_w else np.empty((0, 2, 3))
    kinds = (np.asarray(out_k, dtype=np.int8) if out_k
             else np.empty((0,), dtype=np.int8))
    if len(segs) > 1:
        segs, world, kinds = _merge_collinear(segs, world, kinds,
                                              ext_e * 1e-9)
    if hidden and len(segs):
        segs, world, kinds = _drop_hidden_under_visible(
            segs, world, kinds, max(ext_e * 1e-6, 1e-9))
    return HlrDrawing(segs, world, kinds, loops if fills else [])


def hlr_view(scene, camera, return_world: bool = False, geometry=None):
    """Visible edge segments of *scene* under *camera* (parallel), as an
    (N, 4) array of (x0, y0, x1, y1) in CAMERA-PLANE coordinates (model
    units, origin at the camera axis). This is the drawing a drafter would
    ink; the composer maps it to paper millimetres, the DXF export writes
    it in model units.

    With ``return_world`` also return the same segments' endpoints in
    WORLD coordinates, (N, 2, 3) — the anchor data for dimensions that
    follow the model. Both arrays share row order.

    ``geometry`` — see :func:`hlr_drawing`, which this wraps (no line
    classes, no fills: the cheap call for snapping and the DXF bridge)."""
    d = hlr_drawing(scene, camera, geometry=geometry, profiles=False,
                    fills=False)
    if not return_world:
        return d.segs
    return d.segs, d.world


# ── Perspective ─────────────────────────────────────────────────────────────
# The hidden-line pass above is parallel. A perspective turns into a parallel
# view by the projective map (x, y, z) → (x/w, y/w, 1/w): lines stay lines
# and planes stay planes, and 1/w orders the depth. Clipped to the view
# pyramid first — a point beside or behind the eye has no picture.

#: The view pyramid in clip space, as rows ``a`` with the kept side a·p ≥ 0:
#: left, right, bottom, top, near.
_PYRAMID = np.array([[1, 0, 0, 1], [-1, 0, 0, 1], [0, 1, 0, 1],
                     [0, -1, 0, 1], [0, 0, 1, 1]], dtype=np.float64)


def _clip_polygon(poly):
    """Sutherland–Hodgman against the view pyramid, in clip space."""
    for a in _PYRAMID:
        out = []
        n = len(poly)
        for i in range(n):
            p, q = poly[i], poly[(i + 1) % n]
            dp, dq = float(a @ p), float(a @ q)
            if dp >= 0.0:
                out.append(p)
            if (dp >= 0.0) != (dq >= 0.0):
                out.append(p + (q - p) * (dp / (dp - dq)))
        poly = out
        if len(poly) < 3:
            return []
    return poly


def _clip_triangles(C):
    """(T,3,4) clip-space triangles → the parts inside the pyramid."""
    if not len(C):
        return C
    D = C @ _PYRAMID.T                                  # (T,3,5)
    inside = (D >= 0.0).all(axis=(1, 2))
    outside = (D < 0.0).all(axis=1).any(axis=1)
    parts = [C[inside]]
    for tri in C[~inside & ~outside]:
        poly = _clip_polygon(list(tri))
        for i in range(1, len(poly) - 1):
            parts.append(np.stack([poly[0], poly[i], poly[i + 1]])[None])
    return np.concatenate(parts)


def _clip_segments(A, B):
    """Clip-space segments (E,4) → the parts inside the pyramid."""
    if not len(A):
        return A, B
    t0 = np.zeros(len(A))
    t1 = np.ones(len(A))
    keep = np.ones(len(A), dtype=bool)
    for a in _PYRAMID:
        da, db = A @ a, B @ a
        keep &= ~((da < 0.0) & (db < 0.0))
        with np.errstate(divide="ignore", invalid="ignore"):
            t = da / (da - db)
        t0 = np.where(da < 0.0, np.maximum(t0, t), t0)
        t1 = np.where(db < 0.0, np.minimum(t1, t), t1)
    keep &= t0 < t1
    A, B, t0, t1 = A[keep], B[keep], t0[keep, None], t1[keep, None]
    d = B - A
    return A + d * t0, A + d * t1


def hlr_perspective(scene, camera, geometry=None) -> np.ndarray:
    """Visible edge segments of *scene* in *camera*'s PERSPECTIVE (the
    two-point one included), (N, 4) as (x0, y0, x1, y1) in metres on the
    picture plane through the target — what sits at the target's depth
    comes out true size — with the origin at the centre of the view. Only
    what the view shows: the drawing is cut at the window's edges.

    ``geometry`` as for :func:`hlr_drawing`. The section in force cuts the
    model; its poché does not hide what lies behind it here."""
    from core.camera import OrbitCamera

    soft_n = None
    if geometry is None:
        tris, hard, soft = collect_geometry(scene)
    else:
        tris, hard, soft, soft_n = geometry
    sp = (scene.active_section()
          if getattr(scene, "show_section_cuts", True)
          and hasattr(scene, "active_section") else None)
    cut: list = []
    if sp is not None:
        if soft_n is not None:
            tris, hard, soft = _geometry_as_lists(tris, hard, soft, soft_n)
            soft_n = None
        tris, hard, soft, cut = clip_to_section(tris, hard, soft, sp,
                                                split_cuts=True)
    if soft_n is None:                  # tuple lists → arrays
        soft_n = np.array([[na, nb if nb is not None else (np.nan,) * 3]
                           for _p0, _p1, na, nb in soft],
                          dtype=np.float64).reshape(-1, 2, 3)
        soft = np.array([[p0, p1] for p0, p1, _na, _nb in soft],
                        dtype=np.float64).reshape(-1, 2, 3)
    tris = np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3)
    soft = np.asarray(soft, dtype=np.float64).reshape(-1, 2, 3)
    soft_n = np.asarray(soft_n, dtype=np.float64).reshape(-1, 2, 3)
    lines = [np.asarray(hard, dtype=np.float64).reshape(-1, 2, 3),
             np.asarray(cut, dtype=np.float64).reshape(-1, 2, 3)]
    if len(soft):
        # A soft edge is a profile where its two faces turn opposite ways
        # to the EYE — in perspective the sight line differs per edge.
        eye = camera.eye()
        e = np.array([eye.x(), eye.y(), eye.z()], dtype=np.float64)
        v = soft.mean(axis=1) - e
        fa = np.einsum("ij,ij->i", soft_n[:, 0], v)
        fb = np.einsum("ij,ij->i", soft_n[:, 1], v)
        lines.append(soft[np.isnan(fb) | ((fa < 0.0) != (fb < 0.0))])
    E = np.concatenate(lines)

    m = camera.projection_matrix() * camera.view_matrix()
    M = np.array(m.data(), dtype=np.float64).reshape(4, 4, order="F")

    def to_clip(p):
        return p @ M[:, :3].T + M[:, 3]

    t = camera.target
    w_t = float(to_clip(np.array([t.x(), t.y(), t.z()]))[3])
    if w_t <= 1e-9:
        return np.empty((0, 4))
    half_h = w_t * math.tan(math.radians(camera.fov_deg) / 2.0)
    scale = np.array([half_h * camera.aspect, half_h, w_t])

    def to_parallel(c):
        # (x/w, y/w) scaled to metres at the target's depth; w_t/w for the
        # depth, which grows toward the eye.
        w = c[..., 3:4]
        return np.concatenate([c[..., :2] / w, 1.0 / w], axis=-1) * scale

    T = _clip_triangles(to_clip(tris.reshape(-1, 3)).reshape(-1, 3, 4))
    A, B = _clip_segments(to_clip(E[:, 0]), to_clip(E[:, 1]))
    if not len(A):
        return np.empty((0, 4))
    T = to_parallel(T)
    L = np.stack([to_parallel(A), to_parallel(B)], axis=1)
    # A parallel camera looking down −Z onto that space: x right, y up, and
    # the depth growing away from it.
    top = OrbitCamera()
    top.perspective = False
    top.target = type(camera.target)(0.0, 0.0, 0.0)
    top.yaw, top.pitch = -math.pi / 2.0, math.pi / 2.0
    top.distance = float(max(T[..., 2].max() if len(T) else 0.0,
                             L[..., 2].max())) + 1.0

    class _NoSection:
        pass

    d = hlr_drawing(_NoSection(), top,
                    geometry=(T, L, np.empty((0, 2, 3)), np.empty((0, 2, 3))),
                    profiles=False, fills=False, caps=False)
    return d.segs
