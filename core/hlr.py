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
    up = np.array([camera.up.x(), camera.up.y(), camera.up.z()],
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
        mesh = world_mesh(g) if g.xform is not None else g.mesh
        eat_mesh(mesh)
    return tris, hard, soft


def clip_to_section(tris, hard, soft, plane):
    """Clip collected geometry to the KEPT side of the active section plane
    (S5 — the point of the sections track): triangles are cut, edges are
    shortened, and the plane∩triangle intersection segments join the hard
    edges — the sheet composer's hidden-line pass then draws real plans and
    cross-sections. ``plane`` is a core.section.SectionPlane; the hidden
    side is where ``plane.side(p) > 0``."""
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
    out_hard.extend(cut_edges)
    out_soft: list = []
    for p0, p1, na, nb in soft:
        seg = clip_seg(p0, p1)
        if seg is not None:
            out_soft.append((seg[0], seg[1], na, nb))
    return out_tris, out_hard, out_soft


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


def hlr_view(scene, camera, return_world: bool = False):
    """Visible edge segments of *scene* under *camera* (parallel), as an
    (N, 4) array of (x0, y0, x1, y1) in CAMERA-PLANE coordinates (model
    units, origin at the camera axis). This is the drawing a drafter would
    ink; the composer maps it to paper millimetres, the DXF export writes
    it in model units.

    With ``return_world`` also return the same segments' endpoints in
    WORLD coordinates, (N, 2, 3) — the anchor data for dimensions that
    follow the model. Both arrays share row order."""
    tris, hard, soft = collect_geometry(scene)
    # Active section cut (SketchUp): the composer's sheets honour it — the
    # whole reason sections exist here (plans and cross-cuts on paper).
    sp = (scene.active_section()
          if getattr(scene, "show_section_cuts", True)
          and hasattr(scene, "active_section") else None)
    if sp is not None:
        tris, hard, soft = clip_to_section(tris, hard, soft, sp)
    _e, _r, _u, fwd = camera_basis(camera)

    # silhouette rule for soft edges
    for p0, p1, na, nb in soft:
        fa = float(np.dot(np.asarray(na), fwd))
        if nb is None:
            hard.append((p0, p1))       # open boundary: always a profile
        else:
            fb = float(np.dot(np.asarray(nb), fwd))
            if (fa < 0.0) != (fb < 0.0):
                hard.append((p0, p1))

    if not hard:
        empty = np.empty((0, 4))
        return (empty, np.empty((0, 2, 3))) if return_world else empty
    eye, right, up, fwd = camera_basis(camera)
    E = np.asarray(hard, dtype=np.float64)              # (E,2,3)
    A = _to_cam(E[:, 0, :], eye, right, up, fwd)
    B = _to_cam(E[:, 1, :], eye, right, up, fwd)
    if tris:
        T = np.asarray(tris, dtype=np.float64)          # (T,3,3)
        TC = _to_cam(T.reshape(-1, 3), eye, right, up, fwd).reshape(-1, 3, 3)
        tv2 = TC[:, :, :2]
        tvz = TC[:, :, 2]
        # depth-based epsilon: relative to the scene's depth span
        span = float(tvz.max() - tvz.min()) or 1.0
        eps = max(span * 1e-4, 1e-9)
        tmin = tv2.min(axis=1)                          # (T,2)
        tmax = tv2.max(axis=1)
    else:
        tv2 = tvz = None
        eps = 0.0

    out: list = []
    out_w: list = []
    for i in range(len(A)):
        a2, b2 = A[i, :2], B[i, :2]
        az, bz = A[i, 2], B[i, 2]
        if tv2 is None:
            spans = [(0.0, 1.0)]
        else:
            lo = np.minimum(a2, b2) - 1e-9
            hi = np.maximum(a2, b2) + 1e-9
            cand = ~((tmax[:, 0] < lo[0]) | (tmin[:, 0] > hi[0])
                     | (tmax[:, 1] < lo[1]) | (tmin[:, 1] > hi[1]))
            # a triangle entirely behind both endpoints' nearest depth can
            # never occlude — quick reject
            cand &= tvz.min(axis=1) < max(az, bz)
            idx = np.nonzero(cand)[0]
            if len(idx) == 0:
                spans = [(0.0, 1.0)]
            else:
                spans = visible_spans(a2, b2, az, bz,
                                      tv2[idx], tvz[idx], eps)
        for t0, t1 in spans:
            if (t1 - t0) < 1e-9:
                continue
            p = a2 + t0 * (b2 - a2)
            q = a2 + t1 * (b2 - a2)
            out.append((p[0], p[1], q[0], q[1]))
            if return_world:
                w0, w1 = E[i, 0, :], E[i, 1, :]
                out_w.append((w0 + t0 * (w1 - w0), w0 + t1 * (w1 - w0)))
    segs = np.asarray(out) if out else np.empty((0, 4))
    if not return_world:
        return segs
    world = np.asarray(out_w) if out_w else np.empty((0, 2, 3))
    return segs, world
