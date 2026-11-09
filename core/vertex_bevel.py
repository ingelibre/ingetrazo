# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Bevel the corners (vertices) of a model instead of its edges — the
usual bevel's «Affect: Vertices».

Each chosen vertex is cut back by the same distance along every edge
that reaches it. In each face the corner is replaced by the profile's
curve between the two cut points: the superellipse drawn in the
parallelogram of the two edges, tangent to both (``profile`` 0.5 is
circular when the edges are square, 0.25 straight, toward 1 the old
sharp corner, toward 0 a cove). Then:

* a solid corner where three edges meet is closed by a cap that runs
  exactly through the three face curves — the surface
  ``X^r + Y^r + Z^r = 2`` in the frame of the three cut edges, which at a
  box corner and profile 0.5 is the sphere through them; one segment
  makes it the flat triangle that cuts the tip;
* a corner of a flat figure, or of an open surface, has nothing to close:
  only its faces lose the corner;
* more edges at a solid corner close with a flat polygon, one segment
  only, when the cut points lie in one plane.

Anything else is refused with a reason and the model is left as it was.
The result is a :class:`core.fillet.FilletPlan`, applied in one go by
:func:`core.fillet.apply_fillet` — one undo step.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.fillet import (CIRCULAR, MIN_ANGLE_DEG, PLANE_TOL, FilletPlan,
                         _exponent, _facing, _fmt, _same, _unit)
from core.i18n import tr
from core.mesh import edge_flags


def _face_curve(origin, ua, ub, r, segments):
    """Points from ``origin + ua`` to ``origin + ub``: the corner's curve in
    the face of the two edges ``ua`` and ``ub`` (vectors from the corner
    to the cut points)."""
    e = 2.0 / r
    pts = []
    for k in range(segments + 1):
        if k == 0:
            xa, xb = 0.0, 1.0
        elif k == segments:
            xa, xb = 1.0, 0.0
        else:
            ang = math.pi / 2.0 * k / segments
            xa, xb = math.sin(ang) ** e, math.cos(ang) ** e
        pts.append(origin + ua * (1.0 - xa) + ub * (1.0 - xb))
    return pts


def _cap_point(origin, us, lambdas, r):
    """A point of the three-edge cap at barycentric ``lambdas`` (one per
    cut edge ``us``): ``origin + Σ (1 − X)·u`` with ``Σ X^r = 2``. The
    weights go through sin² so the sides land on the face curves' own
    spacing."""
    s = [math.sin(lam * math.pi / 2.0) ** 2 for lam in lambdas]
    total = sum(s)
    out = QVector3D(origin)
    for u, si in zip(us, s):
        x = max(0.0, 1.0 - si / total) ** (1.0 / r)
        out += u * (1.0 - x)
    return out


def plan_vertex_bevel(mesh, vertices, size: float, segments: int = 8,
                      profile: float = CIRCULAR):
    """Plan bevelling ``vertices`` (of ``mesh``) by ``size`` along each of
    their edges. Returns a :class:`FilletPlan`, or a message (str) saying
    why it cannot be done."""
    verts = list(dict.fromkeys(vertices))
    if not verts:
        return tr("Pick a corner to bevel.")
    if size <= 0:
        return tr("The radius must be positive.")
    if not 0.0 < profile < 1.0:
        return tr("The profile must be between 0 and 1.")
    segments = max(int(segments), 1)
    r = _exponent(profile)
    chosen = {id(v) for v in verts}
    plan = FilletPlan(size, segments, profile, "offset", "round")

    # The cut point on each (corner, edge) and the edge vector to it.
    cut: dict[tuple[int, int], QVector3D] = {}
    for v in verts:
        if not v.edges or not v.faces():
            return tr("Only a corner of a face can be bevelled.")
        for e in v.edges:
            if not e.faces:
                return tr("The corner at {p} has an edge with no face.",
                          p=_fmt(v.position))
            if len(e.faces) > 2:
                return tr("The corner at {p} has too many faces to round.",
                          p=_fmt(v.position))
            w = e.other(v)
            need = size * (2.0 if id(w) in chosen else 1.0)
            if need >= e.length() - 1e-9:
                return tr("The size is too large for the edge at {p}.",
                          p=_fmt(v.position))
            d = _unit(w.position - v.position)
            if d is None:
                return tr("A zero-length edge cannot be rounded.")
            cut[(id(v), id(e))] = d * size

    def edge_between(a, b):
        return mesh.find_edge(a, b)

    # Each face's curve at each chosen corner, in the face's loop order.
    curves: dict[tuple[int, int], list] = {}
    touched: dict[int, object] = {}
    for v in verts:
        for f in v.faces():
            touched[id(f)] = f
            for loop in [f.loop] + list(f.hole_loops):
                m = len(loop)
                for i, x in enumerate(loop):
                    if x is not v:
                        continue
                    ep = edge_between(loop[i - 1], v)
                    en = edge_between(v, loop[(i + 1) % m])
                    if ep is None or en is None:
                        return tr("Could not read the faces around the edge.")
                    ua, ub = cut[(id(v), id(ep))], cut[(id(v), id(en))]
                    cos_a = QVector3D.dotProduct(ua, ub) / (size * size)
                    if cos_a < -math.cos(math.radians(MIN_ANGLE_DEG)):
                        return tr("The edges at {p} are too flat to bevel.",
                                  p=_fmt(v.position))
                    curves[(id(f), id(v), id(ep))] = _face_curve(
                        v.position, ua, ub, r, segments)

    # Rebuild every face that loses a corner.
    def rebuilt_loop(face, loop):
        out = []
        m = len(loop)
        for i, x in enumerate(loop):
            if id(x) not in chosen:
                out.append(QVector3D(x.position))
                continue
            ep = edge_between(loop[i - 1], x)
            out.extend(QVector3D(p) for p in curves[(id(face), id(x), id(ep))])
        clean = []
        for p in out:
            if not clean or (p - clean[-1]).length() > 1e-7:
                clean.append(p)
        if len(clean) > 1 and (clean[0] - clean[-1]).length() <= 1e-7:
            clean.pop()
        return clean

    attrs = None
    for f in touched.values():
        loop = rebuilt_loop(f, f.loop)
        holes = [rebuilt_loop(f, h) for h in f.hole_loops]
        if len(loop) < 3 or any(len(h) < 3 for h in holes):
            return tr("A face would collapse — the radius is too large.")
        plan.removed_faces.append(f)
        plan.rebuilt.append((loop, holes, dict(f.attrs), bool(f.interior)))
        keep = {k: f.attrs[k] for k in ("color", "texture", "mat", "opacity")
                if k in (f.attrs or {})}
        attrs = keep if attrs is None else (attrs if attrs == keep else {})
    plan.face_attrs["strip"] = attrs or {}

    # Close each solid corner.
    for v in verts:
        faces = list(v.faces())
        closed = all(len(e.faces) == 2 for e in v.edges)
        face_curves = [pts for key, pts in curves.items() if key[1] == id(v)]
        if not closed:
            for pts in face_curves:
                if segments > 1:
                    plan.curves.append([QVector3D(p) for p in pts])
            continue
        if len(v.edges) < 3:
            return tr("Nothing to bevel at {p}.", p=_fmt(v.position))
        out = QVector3D()
        for f in faces:
            out += f.normal()
        tips = [v.position + cut[(id(v), id(e))] for e in v.edges]
        centre = QVector3D()
        for p in tips:
            centre += p
        centre /= float(len(tips))
        sign = 1.0 if QVector3D.dotProduct(out, v.position - centre) >= 0 else -1.0
        if len(v.edges) == 3:
            cap, soft = _three_edge_cap(v, cut, face_curves, r, segments, sign)
            if cap is None:
                return tr("Could not close the corner at {p}.",
                          p=_fmt(v.position))
            plan.patches.extend(cap)
            plan.soft.extend(soft)
        else:
            if segments > 1:
                return tr("More than three rounded edges meet at {p}.",
                          p=_fmt(v.position))
            poly = _flat_polygon(tips, out)
            if poly is None:
                return tr("The corner at {p} is not flat enough to cut.",
                          p=_fmt(v.position))
            plan.patches.append(_facing(poly, v.position, sign))

    # Old edges go; the shortened ones keep their flags.
    seen = set()
    for v in verts:
        for e in v.edges:
            if id(e) in seen:
                continue
            seen.add(id(e))
            plan.removed_edges.append(e)
            a, b = e.v0, e.v1
            pa = (a.position + cut[(id(a), id(e))] if id(a) in chosen
                  else QVector3D(a.position))
            pb = (b.position + cut[(id(b), id(e))] if id(b) in chosen
                  else QVector3D(b.position))
            plan.flags.append((pa, pb, edge_flags(e)))
    return plan


def _three_edge_cap(v, cut, face_curves, r, segments, sign):
    """Triangles of the cap at a three-edge corner. Its sides ARE the face
    curves, so it closes watertight; the inside follows
    :func:`_cap_point`."""
    n = segments
    edges = list(v.edges)
    us = [cut[(id(v), id(e))] for e in edges]
    tips = [v.position + u for u in us]

    def arc(i, j):
        """The face curve from tip ``i`` to tip ``j``."""
        for pts in face_curves:
            if _same(pts[0], tips[i]) and _same(pts[-1], tips[j]):
                return pts
            if _same(pts[-1], tips[i]) and _same(pts[0], tips[j]):
                return list(reversed(pts))
        return None
    ab, bc, ac = arc(0, 1), arc(1, 2), arc(0, 2)
    if ab is None or bc is None or ac is None:
        return None, None
    grid: dict[tuple[int, int], QVector3D] = {}
    for i in range(n + 1):
        for j in range(n + 1 - i):
            k = n - i - j
            if k == 0:
                grid[(i, j)] = ab[j]
            elif i == 0:
                grid[(i, j)] = bc[k]
            elif j == 0:
                grid[(i, j)] = ac[k]
            else:
                grid[(i, j)] = _cap_point(v.position, us,
                                          (i / n, j / n, k / n), r)
    tris = []
    for i in range(n):
        for j in range(n - i):
            tris.append(_facing([grid[(i, j)], grid[(i + 1, j)],
                                 grid[(i, j + 1)]], v.position, sign))
            if i + j + 1 < n:
                tris.append(_facing([grid[(i + 1, j)], grid[(i + 1, j + 1)],
                                     grid[(i, j + 1)]], v.position, sign))
    soft = []
    for (i, j), p in grid.items():
        for di, dj in ((1, 0), (0, 1), (-1, 1)):
            q = grid.get((i + di, j + dj))
            if q is None:
                continue
            ka, kb = n - i - j, n - (i + di) - (j + dj)
            along_side = ((i == 0 and i + di == 0) or (j == 0 and j + dj == 0)
                          or (ka == 0 and kb == 0))
            if not along_side:
                soft.append((p, q))
    return tris, soft


def _flat_polygon(points, normal):
    """``points`` ordered around ``normal`` — or None when they do not lie
    in one plane."""
    n = _unit(normal)
    if n is None:
        return None
    c = QVector3D()
    for p in points:
        c += p
    c /= float(len(points))
    span = max((p - c).length() for p in points) or 1.0
    for p in points:
        if abs(QVector3D.dotProduct(p - c, n)) > PLANE_TOL * 10 * max(1.0, span):
            return None
    ref = _unit(points[0] - c)
    if ref is None:
        return None
    side = QVector3D.crossProduct(n, ref)

    def angle(p):
        d = p - c
        return math.atan2(QVector3D.dotProduct(d, side),
                          QVector3D.dotProduct(d, ref))
    return sorted((QVector3D(p) for p in points), key=angle)
