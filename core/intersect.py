# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Intersect Faces (Edit ▸ Intersect Faces ▸ With Model / With
Selection / With Context): new edges wherever faces cross.

Nothing has to be a solid — this is the classic way to cut shapes
out of one another: intersect, then erase what is not wanted. The edges
land in the context being edited (outside the groups when the model is
the context, which is what makes them easy to separate), and they split
the faces of that context they run across.

The geometry: two planar faces cross along the line common to their two
planes; that line is clipped by each polygon (outer ring and holes, the
even-odd rule) and what both keep is the new edge. Coplanar faces do not
cross — nothing is drawn for them.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.triangulate import plane_axes

#: Below this a crossing is a point, not an edge.
_MIN_LEN = 1e-5


class _Poly:
    """A face in world space, ready for crossing tests."""

    __slots__ = ("rings", "n", "d", "lo", "hi", "u", "v", "rings2d")

    def __init__(self, rings: list, normal: QVector3D) -> None:
        self.rings = rings
        self.n = normal.normalized()
        self.d = QVector3D.dotProduct(self.n, rings[0][0])
        xs = [p.x() for p in rings[0]]
        ys = [p.y() for p in rings[0]]
        zs = [p.z() for p in rings[0]]
        self.lo = (min(xs), min(ys), min(zs))
        self.hi = (max(xs), max(ys), max(zs))
        self.u, self.v = plane_axes(self.n)
        self.rings2d = [[(QVector3D.dotProduct(p, self.u),
                          QVector3D.dotProduct(p, self.v)) for p in ring]
                        for ring in rings]


def world_polys(face, xform=None) -> _Poly | None:
    """``face`` as a world-space polygon (through ``xform`` for a group)."""
    def w(p):
        return xform.map(p) if xform is not None else QVector3D(p)
    outer = [w(p) for p in face.vertices]
    if len(outer) < 3:
        return None
    holes = [[w(p) for p in h] for h in face.holes]
    n = _newell(outer)
    if n.length() < 1e-12:
        return None
    return _Poly([outer, *holes], n)


def _newell(pts) -> QVector3D:
    x = y = z = 0.0
    for i, a in enumerate(pts):
        b = pts[(i + 1) % len(pts)]
        x += (a.y() - b.y()) * (a.z() + b.z())
        y += (a.z() - b.z()) * (a.x() + b.x())
        z += (a.x() - b.x()) * (a.y() + b.y())
    return QVector3D(x, y, z)


def _boxes_touch(a: _Poly, b: _Poly, eps: float = 1e-6) -> bool:
    return all(a.lo[i] <= b.hi[i] + eps and b.lo[i] <= a.hi[i] + eps
               for i in range(3))


def _intervals(poly: _Poly, origin: QVector3D, direction: QVector3D) -> list:
    """Where the line ``origin + t·direction`` (lying in ``poly``'s plane)
    is inside the polygon: sorted ``(t0, t1)`` pairs, even-odd over every
    ring."""
    ox = QVector3D.dotProduct(origin, poly.u)
    oy = QVector3D.dotProduct(origin, poly.v)
    dx = QVector3D.dotProduct(direction, poly.u)
    dy = QVector3D.dotProduct(direction, poly.v)
    ts = []
    for ring in poly.rings2d:
        n = len(ring)
        for i in range(n):
            ax, ay = ring[i]
            bx, by = ring[(i + 1) % n]
            # which side of the line each end is on (half-open: a vertex ON
            # the line counts as the positive side, so it is crossed once)
            sa = (ax - ox) * dy - (ay - oy) * dx
            sb = (bx - ox) * dy - (by - oy) * dx
            if (sa >= 0) == (sb >= 0):
                continue
            k = sa / (sa - sb)
            px, py = ax + (bx - ax) * k, ay + (by - ay) * k
            den = dx * dx + dy * dy
            ts.append(((px - ox) * dx + (py - oy) * dy) / den)
    ts.sort()
    return [(ts[i], ts[i + 1]) for i in range(0, len(ts) - 1, 2)]


def _overlap(xs: list, ys: list) -> list:
    out, i, j = [], 0, 0
    while i < len(xs) and j < len(ys):
        lo = max(xs[i][0], ys[j][0])
        hi = min(xs[i][1], ys[j][1])
        if hi > lo:
            out.append((lo, hi))
        if xs[i][1] < ys[j][1]:
            i += 1
        else:
            j += 1
    return out


def cross(a: _Poly, b: _Poly) -> list:
    """The segments where faces ``a`` and ``b`` cross (none when their
    planes are parallel)."""
    direction = QVector3D.crossProduct(a.n, b.n)
    if direction.length() < 1e-9:
        return []
    direction = direction.normalized()
    # A point on both planes: the one nearest the origin.
    n1, n2 = a.n, b.n
    d1, d2 = a.d, b.d
    c = QVector3D.dotProduct(n1, n2)
    den = 1.0 - c * c
    if den < 1e-12:
        # Nearly parallel: QVector3D works in float32, so c rounded to
        # exactly 1 and this divided by zero (seen on a real model while
        # testing #541). No well-defined crossing line there.
        return []
    k1 = (d1 - d2 * c) / den
    k2 = (d2 - d1 * c) / den
    origin = n1 * k1 + n2 * k2
    segs = []
    for t0, t1 in _overlap(_intervals(a, origin, direction),
                           _intervals(b, origin, direction)):
        p, q = origin + direction * t0, origin + direction * t1
        if (q - p).length() > _MIN_LEN:
            segs.append((p, q))
    return segs


def _boxes(polys: list):
    import numpy as np
    lo = np.array([p.lo for p in polys], dtype=np.float64).reshape(-1, 3)
    hi = np.array([p.hi for p in polys], dtype=np.float64).reshape(-1, 3)
    return lo, hi


#: Box pairs tested per NumPy block (rows × columns), to bound the memory.
_PAIR_BLOCK = 2_000_000


def _touching(lo_a, hi_a, lo_b, hi_b, same: bool, eps: float = 1e-6):
    """Index pairs ``(i, j)`` whose boxes touch — ``_boxes_touch`` for every
    pair at once, in blocks of rows (``same``: j > i only)."""
    import numpy as np
    # The Rust engine (core._native) answers the same pairs in the same
    # order: the same test, with a grid that skips the far boxes.
    from core._native import native
    if native is not None:
        ii, jj = native.touching_boxes(
            *(np.ascontiguousarray(x, dtype=np.float64)
              for x in (lo_a, hi_a, lo_b, hi_b)), bool(same), float(eps))
        yield from zip(ii.tolist(), jj.tolist())
        return
    rows = max(1, _PAIR_BLOCK // max(1, len(lo_b)))
    for r0 in range(0, len(lo_a), rows):
        r1 = min(len(lo_a), r0 + rows)
        ok = np.all((lo_a[r0:r1, None, :] <= hi_b[None, :, :] + eps)
                    & (lo_b[None, :, :] <= hi_a[r0:r1, None, :] + eps), axis=2)
        if same:
            ok &= np.arange(len(lo_b))[None, :] > np.arange(r0, r1)[:, None]
        ii, jj = np.nonzero(ok)
        yield from zip((ii + r0).tolist(), jj.tolist())


def intersect(polys_a: list, polys_b: list, same: bool = False,
              boxes_a=None, boxes_b=None) -> list:
    """Every crossing between a face of ``polys_a`` and one of ``polys_b``
    (``same``: the two lists are one, each pair once). The box test runs
    in NumPy blocks: one Python test per pair took minutes over a whole
    model. ``boxes_a``/``boxes_b``: the ``_boxes`` of each list, when the
    caller already has them."""
    out = []
    if not polys_a or not polys_b:
        return out
    lo_a, hi_a = boxes_a if boxes_a is not None else _boxes(polys_a)
    if same:
        lo_b, hi_b = lo_a, hi_a
        ia = ib = None
    else:
        import numpy as np
        lo_b, hi_b = boxes_b if boxes_b is not None else _boxes(polys_b)
        # Only the faces that reach the OTHER side's whole box can cross
        # it: a big object (a pavement under a thousand others) is cut
        # down to the few faces near each neighbour before the pair test.
        eps = 1e-6
        ia = np.nonzero(np.all((lo_a <= hi_b.max(axis=0) + eps)
                               & (hi_a >= lo_b.min(axis=0) - eps), axis=1))[0]
        if not len(ia):
            return out
        lo_a, hi_a = lo_a[ia], hi_a[ia]
        ib = np.nonzero(np.all((lo_b <= hi_a.max(axis=0) + eps)
                               & (hi_b >= lo_a.min(axis=0) - eps), axis=1))[0]
        if not len(ib):
            return out
        lo_b, hi_b = lo_b[ib], hi_b[ib]
    for i, j in _touching(lo_a, hi_a, lo_b, hi_b, same):
        if ia is not None:
            i, j = int(ia[i]), int(ib[j])
        a, b = polys_a[i], polys_b[j]
        if a is not b:
            out.extend(cross(a, b))
    return _dedupe(out)


def _dedupe(segs: list, tol: float = 1e-6) -> list:
    seen = set()
    out = []
    for p, q in segs:
        k1 = tuple(round(c / tol) for c in (p.x(), p.y(), p.z()))
        k2 = tuple(round(c / tol) for c in (q.x(), q.y(), q.z()))
        key = (k1, k2) if k1 <= k2 else (k2, k1)
        if key in seen:
            continue
        seen.add(key)
        out.append((p, q))
    return out


# ---- What takes part ----------------------------------------------------------

def polys_of(entities) -> list:
    """World polygons for a mix of loose faces and groups/components."""
    from core.group import Group, iter_placements
    from core.mesh import Face
    out = []
    for e in entities:
        if isinstance(e, Face):
            p = world_polys(e)
            if p is not None:
                out.append(p)
        elif isinstance(e, Group):
            for g, xf in iter_placements(e):
                for f in g.mesh.faces:
                    p = world_polys(f, xf)
                    if p is not None:
                        out.append(p)
    return out


WITH_MODEL, WITH_SELECTION, WITH_CONTEXT = "model", "selection", "context"


def segments_for(scene, mode: str) -> list:
    """The crossing segments Intersect Faces would add, for ``mode``:

    * **model** — the selection against everything it touches (the whole
      context and every group in it),
    * **selection** — only the selected things against each other,
    * **context** — the selection against the rest of the context being
      edited (inside a group: its own geometry)."""
    from core.group import Group
    from core.mesh import Face
    sel = [e for e in scene.selection if isinstance(e, (Face, Group))]
    if not sel:
        return []
    mine = polys_of(sel)
    if mode == WITH_SELECTION:
        return intersect(mine, mine, same=True)
    selected = set(map(id, sel))
    rest = [f for f in scene.mesh.faces if id(f) not in selected]
    if mode == WITH_MODEL:
        owner = scene.edit_group
        kids = (getattr(owner, "children", None) or []) if owner is not None \
            else scene.groups
        rest += [g for g in kids if id(g) not in selected]
    others = polys_of(rest)
    if mode == WITH_MODEL:
        # The selection is part of the model: Select All + With Model is the
        # usual way to cut everything against everything, and taking the
        # selection out of «the rest» left nothing to cut against (#541).
        return _dedupe(intersect(mine, others)
                       + intersect(mine, mine, same=True))
    return intersect(mine, others)
