# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Terrain from survey data — the pure geometry behind Draw ▸ Terrain ▸
From Contours and From Points.

- :func:`points_terrain` — a triangulated network (TIN) through survey
  points: a Delaunay triangulation of their plan, each corner at its
  point's height, so the ground passes exactly through every point. Long
  thin triangles round the rim, which only join far points across the
  outside of the survey, can be peeled off with a longest-side limit.
- :func:`contour_terrain` — a ground through contour lines: a regular grid
  over them, each node on a contour fixed at that contour's height and the
  rest filled by harmonic interpolation (every free node the average of its
  four neighbours — the smoothest surface through the lines, which runs as
  an even ramp from one contour to the next, with no terraces). The grid
  is clipped to the contours' outline (their convex hull).

Both return ``(vertices, triangles)`` as :func:`core.terrain_mesh.
grid_terrain` does — ``QVector3D`` corners and counter-clockwise index
triples — for :func:`core.terrain_mesh.terrain_group`. Classic textbook
algorithms (Bowyer–Watson, red–black SOR), written here from scratch.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.terrain_mesh import grid_cells

#: Points closer than this in plan count as one (model units).
MERGE = 1e-3


class TerrainBuildError(ValueError):
    """The data makes no ground; the message says why (English source text,
    translated by the caller)."""


# ---- Points ------------------------------------------------------------------

def merge_points(points, tol: float = MERGE) -> list:
    """``points`` (``QVector3D``) without plan duplicates: points closer
    than ``tol`` in plan become one, at their mean height."""
    cells: dict = {}
    order = []
    for p in points:
        key = (round(p.x() / tol), round(p.y() / tol))
        if key not in cells:
            cells[key] = [p.x(), p.y(), 0.0, 0]
            order.append(key)
        c = cells[key]
        c[2] += p.z()
        c[3] += 1
    return [QVector3D(cells[k][0], cells[k][1], cells[k][2] / cells[k][3])
            for k in order]


def delaunay(xy) -> list:
    """Delaunay triangles ``[(i, j, k), ...]`` (counter-clockwise) of the
    plan points ``xy`` (``[(x, y), ...]``, no duplicates): Bowyer–Watson,
    each point inserted into the triangles whose circumcircle holds it,
    the circumcircle test vectorised over every live triangle."""
    import numpy as np

    n = len(xy)
    if n < 3:
        return []
    pts = np.asarray(xy, dtype=np.float64)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    span = max(float((hi - lo).max()), 1e-9)
    mid = (lo + hi) / 2.0
    # Work centred and scaled to ~1, so the circumcircles stay well-posed
    # for survey coordinates in the hundreds of thousands.
    P = (pts - mid) / span
    big = 1.0e4      # far enough that no hull edge sees its corners
    P = np.vstack([P, [[-big, -big], [big, -big], [0.0, big]]])
    cap = 8 * n + 16
    tri = np.zeros((cap, 3), dtype=np.int64)
    cx = np.zeros(cap)
    cy = np.zeros(cap)
    r2 = np.zeros(cap)
    alive = np.zeros(cap, dtype=bool)
    count = 0

    def add(a, b, c):
        nonlocal count, tri, cx, cy, r2, alive, cap
        if count == cap:
            cap *= 2
            tri = np.resize(tri, (cap, 3))
            cx, cy, r2 = (np.resize(arr, cap) for arr in (cx, cy, r2))
            grown = np.zeros(cap, dtype=bool)
            grown[:count] = alive[:count]
            alive = grown
        (ax, ay), (bx, by), (qx, qy) = P[a], P[b], P[c]
        if (bx - ax) * (qy - ay) - (by - ay) * (qx - ax) < 0:
            b, c = c, b                      # keep every triangle CCW
            (bx, by), (qx, qy) = (qx, qy), (bx, by)
        d = 2.0 * (ax * (by - qy) + bx * (qy - ay) + qx * (ay - by))
        if abs(d) < 1e-30:
            ux, uy, rr = ax, ay, np.inf       # degenerate: always "bad"
        else:
            a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, qx * qx + qy * qy
            ux = (a2 * (by - qy) + b2 * (qy - ay) + c2 * (ay - by)) / d
            uy = (a2 * (qx - bx) + b2 * (ax - qx) + c2 * (bx - ax)) / d
            rr = (ax - ux) ** 2 + (ay - uy) ** 2
        tri[count] = (a, b, c)
        cx[count], cy[count], r2[count] = ux, uy, rr
        alive[count] = True
        count += 1

    add(n, n + 1, n + 2)
    # A spatially sorted order keeps each cavity small and local.
    order = np.lexsort((P[:n, 1], np.round(P[:n, 0] * 64)))
    for i in order:
        px, py = P[i]
        live = np.flatnonzero(alive[:count])
        d2 = (cx[live] - px) ** 2 + (cy[live] - py) ** 2
        bad = live[d2 < r2[live] * (1.0 + 1e-12)]
        if not len(bad):
            continue
        edges: dict = {}
        for t in bad:
            a, b, c = tri[t]
            for u, v in ((a, b), (b, c), (c, a)):
                key = (min(u, v), max(u, v))
                if key in edges:
                    del edges[key]           # shared by two bad: inside
                else:
                    edges[key] = (u, v)
        alive[bad] = False
        for u, v in edges.values():
            add(int(u), int(v), int(i))
    out = []
    for t in np.flatnonzero(alive[:count]):
        a, b, c = (int(k) for k in tri[t])
        if a >= n or b >= n or c >= n:
            continue                         # touches the super-triangle
        out.append((a, b, c))
    return out


def peel_long_rim(xy, triangles, max_side: float) -> list:
    """``triangles`` without the rim triangles that have a side longer than
    ``max_side`` (plan): peeled from the outside in, so a long triangle
    inside the survey — between two real points — is kept."""
    if max_side <= 0.0:
        return list(triangles)
    tris = list(triangles)

    def long(i, j):
        return math.hypot(xy[i][0] - xy[j][0], xy[i][1] - xy[j][1]) > max_side

    while True:
        uses: dict = {}
        for t in tris:
            for u, v in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                key = (min(u, v), max(u, v))
                uses[key] = uses.get(key, 0) + 1
        keep = []
        for t in tris:
            rim_long = any(uses[(min(u, v), max(u, v))] == 1 and long(u, v)
                           for u, v in ((t[0], t[1]), (t[1], t[2]),
                                        (t[2], t[0])))
            if not rim_long:
                keep.append(t)
        if len(keep) == len(tris):
            return keep
        tris = keep


def points_terrain(points, max_side: float = 0.0):
    """A TIN through survey ``points`` (``QVector3D``): ``(vertices,
    triangles)``. ``max_side`` > 0 peels the long rim triangles. Raises
    :class:`TerrainBuildError` with fewer than three points or all on a
    line."""
    pts = merge_points(points)
    if len(pts) < 3:
        raise TerrainBuildError("A terrain needs at least three points.")
    xy = [(p.x(), p.y()) for p in pts]
    tris = delaunay(xy)
    if not tris:
        raise TerrainBuildError("The points lie on a line.")
    tris = peel_long_rim(xy, tris, max_side)
    if not tris:
        raise TerrainBuildError(
            "Every triangle is longer than the longest side allowed.")
    used = sorted({k for t in tris for k in t})
    remap = {k: i for i, k in enumerate(used)}
    return ([QVector3D(pts[k]) for k in used],
            [tuple(remap[k] for k in t) for t in tris])


# ---- Contours ----------------------------------------------------------------

def convex_hull(xy) -> list:
    """Counter-clockwise convex hull of plan points (monotone chain)."""
    pts = sorted(set(xy))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _inside_convex(hull, xs, ys, eps):
    """Mask of the points inside the CCW convex polygon ``hull`` (with a
    margin ``eps`` outward)."""
    import numpy as np
    inside = np.ones(xs.shape, dtype=bool)
    n = len(hull)
    for k in range(n):
        (x0, y0), (x1, y1) = hull[k], hull[(k + 1) % n]
        ex, ey = x1 - x0, y1 - y0
        length = math.hypot(ex, ey) or 1.0
        side = (ex * (ys - y0) - ey * (xs - x0)) / length
        inside &= side >= -eps
    return inside


def _relax(Z, fixed, iters: int, tol: float):
    """Red–black over-relaxation of Laplace's equation on the free nodes of
    grid ``Z`` (the ``fixed`` ones keep their value; the border mirrors, so
    the ground runs out level past the last contour)."""
    import numpy as np
    ny, nx = Z.shape
    jj, ii = np.indices((ny, nx))
    red = ((ii + jj) % 2 == 0) & ~fixed
    black = ((ii + jj) % 2 == 1) & ~fixed
    omega = 2.0 / (1.0 + math.sin(math.pi / max(nx, ny, 2)))
    for _ in range(iters):
        change = 0.0
        for mask in (red, black):
            padded = np.pad(Z, 1, mode="edge")
            avg = 0.25 * (padded[:-2, 1:-1] + padded[2:, 1:-1]
                          + padded[1:-1, :-2] + padded[1:-1, 2:])
            step = omega * (avg[mask] - Z[mask])
            Z[mask] += step
            if step.size:
                change = max(change, float(np.abs(step).max()))
        if change < tol:
            break
    return Z


def _harmonic(fixed, values):
    """The harmonic fill of a grid with ``fixed`` nodes at ``values``:
    solved on a grid half as fine first (recursively), then refined, so
    the fine grid only has to settle the details."""
    import numpy as np
    ny, nx = fixed.shape
    span = float(values[fixed].max() - values[fixed].min()) if fixed.any() else 0.0
    tol = max(span, 1e-6) * 1e-5
    if min(nx, ny) > 12:
        cy, cx = (ny + 1) // 2, (nx + 1) // 2
        cs = np.zeros((cy, cx))
        cn = np.zeros((cy, cx))
        jj, ii = np.nonzero(fixed)
        np.add.at(cs, (jj // 2, ii // 2), values[jj, ii])
        np.add.at(cn, (jj // 2, ii // 2), 1.0)
        cf = cn > 0
        cv = np.where(cf, cs / np.maximum(cn, 1.0), 0.0)
        coarse = _harmonic(cf, cv)
        Z = np.repeat(np.repeat(coarse, 2, axis=0), 2, axis=1)[:ny, :nx]
        iters = 300
    else:
        mean = float(values[fixed].mean()) if fixed.any() else 0.0
        Z = np.full((ny, nx), mean)
        iters = 4000
    Z = Z.astype(np.float64)
    Z[fixed] = values[fixed]
    return _relax(Z, fixed, iters, tol)


def contour_terrain(segments, cell: float):
    """A ground through contour lines: world segments ``[(a, b), ...]``,
    each at its contour's height. ``(vertices, triangles)`` on a grid of
    about ``cell`` (at most :data:`core.terrain_mesh.MAX_CELLS_PER_SIDE`
    cells a side),
    clipped to the contours' convex hull. Raises :class:`TerrainBuildError`
    with no contour or all of them at one point."""
    import numpy as np

    segs = [(a, b) for a, b in segments
            if math.hypot(b.x() - a.x(), b.y() - a.y()) > MERGE]
    if not segs:
        raise TerrainBuildError("Select the contour lines first.")
    xs = [p.x() for s in segs for p in s]
    ys = [p.y() for s in segs for p in s]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 - x0 < MERGE or y1 - y0 < MERGE:
        raise TerrainBuildError("The contour lines have no width or depth.")
    nx, ny = grid_cells(x1 - x0, y1 - y0, cell)
    dx, dy = (x1 - x0) / nx, (y1 - y0) / ny
    # Every contour sampled finely and dropped on its nearest node.
    total = np.zeros((ny + 1, nx + 1))
    count = np.zeros((ny + 1, nx + 1))
    step = 0.5 * min(dx, dy)
    for a, b in segs:
        length = math.hypot(b.x() - a.x(), b.y() - a.y())
        k = max(1, int(math.ceil(length / step)))
        t = np.linspace(0.0, 1.0, k + 1)
        px = a.x() + (b.x() - a.x()) * t
        py = a.y() + (b.y() - a.y()) * t
        pz = a.z() + (b.z() - a.z()) * t
        ii = np.clip(np.rint((px - x0) / dx).astype(int), 0, nx)
        jj = np.clip(np.rint((py - y0) / dy).astype(int), 0, ny)
        np.add.at(total, (jj, ii), pz)
        np.add.at(count, (jj, ii), 1.0)
    fixed = count > 0
    values = np.where(fixed, total / np.maximum(count, 1.0), 0.0)
    Z = _harmonic(fixed, values)
    # Clip to the contours' outline: a cell stays when its centre is inside.
    hull = convex_hull(list(zip(xs, ys)))
    ci, cj = np.meshgrid(np.arange(nx), np.arange(ny))
    centre_x = x0 + (ci + 0.5) * dx
    centre_y = y0 + (cj + 0.5) * dy
    keep = _inside_convex(hull, centre_x, centre_y, 0.5 * min(dx, dy))
    row = nx + 1
    triangles = []
    for j, i in zip(*np.nonzero(keep)):
        a = j * row + i
        b, c, d = a + 1, a + row + 1, a + row
        if (i + j) % 2 == 0:
            triangles += [(a, b, c), (a, c, d)]
        else:
            triangles += [(a, b, d), (b, c, d)]
    if not triangles:
        raise TerrainBuildError("The contour lines have no width or depth.")
    used = sorted({k for t in triangles for k in t})
    remap = {k: n for n, k in enumerate(used)}
    vertices = []
    for k in used:
        j, i = divmod(k, row)
        vertices.append(QVector3D(x0 + i * dx if i < nx else x1,
                                  y0 + j * dy if j < ny else y1,
                                  float(Z[j, i])))
    return vertices, [tuple(remap[k] for k in t) for t in triangles]
