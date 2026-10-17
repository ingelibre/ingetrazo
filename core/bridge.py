# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Bridge (issue #614): side faces between two profiles.

A profile is a face (its outline, and its holes), a closed loop of edges or
an open chain of them. Two selected profiles are joined:

* face to face — the faces stay as the two caps, so two loose rectangles
  become a closed box;
* face to line — the line is walked there and back as a flat loop, so a
  rectangle and a ridge line become a hip roof;
* line to line — a ruled surface between the two chains.

Points are paired one to one when both profiles have as many; otherwise by
the fraction of the length walked along each, which gives quads where the
two meet and triangles in between. Closed profiles are first turned and, if
need be, reversed so the bridge does not twist. A side that is not flat is
split along its shorter diagonal, softened so it still reads as one surface.

Headless: :func:`profiles_from_selection` reads the selection and
:func:`bridge` builds the faces; the menu command is a thin shell over them.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import run_stitch
from core.mesh import Edge, Face
from core.orient import orient_outward
from core.sweep import _CURVE_FACET_COS, _wall, order_path_edges
from core.topology import _key

_EPS = 1e-9
#: Two length fractions closer than this pair their points with a quad.
_SAME_T = 1e-6
#: A quad is flat when its fourth corner is off the plane of the other three
#: by less than this fraction of its size.
_FLAT = 1e-5


class BridgeError(ValueError):
    """The selection cannot be bridged; the message says why (English
    source text, translated by the caller)."""


class Profile:
    """One side of a bridge: ``loops`` of points (a face's outline then its
    holes, or a single chain), ``closed`` or not, and the ``face`` it came
    from (kept as a cap) when it is one."""

    def __init__(self, loops, closed: bool, face=None) -> None:
        self.loops = [list(lp) for lp in loops]
        self.closed = closed
        self.face = face

    @property
    def points(self) -> list:
        return [p for lp in self.loops for p in lp]


# ---------------------------------------------------------------- selection

def profiles_from_selection(mesh, selection) -> list[Profile]:
    """The two profiles a selection holds, or :class:`BridgeError`.

    Selected faces count as faces; the selected edges that are not the
    outline of a selected face (picking a face by double click selects its
    edges too) are chained into lines or closed loops."""
    # Sets of ids, not ``in mesh.faces``: those are lists, and checking each
    # selected element against them made a big selection quadratic.
    mesh_faces = {id(f) for f in mesh.faces}
    mesh_edges = {id(e) for e in mesh.edges}
    faces = [e for e in selection
             if isinstance(e, Face) and id(e) in mesh_faces]
    if len(faces) > 2:
        raise BridgeError("Select two faces, a face and a line, or two "
                          "lines to bridge")
    face_ids = {id(f) for f in faces}
    edges = [e for e in selection
             if isinstance(e, Edge) and id(e) in mesh_edges
             and not any(id(f) in face_ids for f in e.faces)]
    profiles = [Profile([f.vertices] + f.holes, True, f) for f in faces]
    chains = _connected(edges, most=2 - len(faces))
    if chains is None:
        raise BridgeError("Select two faces, a face and a line, or two "
                          "lines to bridge")
    for chain in chains:
        got = order_path_edges(chain)
        if got is None:
            raise BridgeError("Each line to bridge must be one chain "
                              "of edges, without branches")
        points, closed = got
        if closed and len(points) > 1 and \
                (points[0] - points[-1]).length() < _EPS:
            points = points[:-1]
        profiles.append(Profile([points], closed))
    if len(profiles) != 2:
        raise BridgeError("Select two faces, a face and a line, or two "
                          "lines to bridge")
    return profiles


def _connected(edges, most: int | None = None) -> list[list] | None:
    """The selected edges split into the pieces they form; ``None`` as soon
    as there are more than ``most`` of them (the right-click menu asks on
    every click, and a selection of thousands of loose edges must not be
    walked and sorted only to say no)."""
    left = set(edges)
    by_vertex: dict = {}
    for e in edges:
        by_vertex.setdefault(e.v0, []).append(e)
        by_vertex.setdefault(e.v1, []).append(e)
    pieces = []
    while left:
        seed = left.pop()
        piece, stack = [seed], [seed]
        while stack:
            e = stack.pop()
            for v in (e.v0, e.v1):
                for n in by_vertex[v]:
                    if n in left:
                        left.remove(n)
                        piece.append(n)
                        stack.append(n)
        pieces.append(piece)
        if most is not None and len(pieces) > most:
            return None
    # Stable order: the order the user's selection set happens to give
    # must not decide which profile is "first".
    pieces.sort(key=lambda p: min(_key(v.position) for e in p
                                  for v in (e.v0, e.v1)))
    return pieces


# ---------------------------------------------------------------- pairing

def _centre(points) -> QVector3D:
    c = QVector3D()
    for p in points:
        c += p
    return c / len(points)


def _normalised(points) -> list:
    """The points about their centre, scaled to a unit mean radius, so two
    profiles of different size and place can be compared by shape."""
    c = _centre(points)
    rel = [p - c for p in points]
    r = sum(v.length() for v in rel) / len(rel)
    return [v / r for v in rel] if r > _EPS else rel


def _fractions(points, closed: bool) -> list[float]:
    """Length walked to each point, as a fraction of the whole (the closing
    side included for a closed loop). The list has one more entry than the
    points for a closed loop: its return to the start, at 1."""
    pts = list(points) + ([points[0]] if closed else [])
    acc = [0.0]
    for a, b in zip(pts, pts[1:]):
        acc.append(acc[-1] + (b - a).length())
    total = acc[-1]
    if total < _EPS:
        n = len(acc) - 1
        return [i / n for i in range(len(acc))] if n else [0.0]
    return [t / total for t in acc]


def _resample(points, ts, targets) -> list:
    """The points at the increasing length fractions ``targets`` along
    ``points`` (with ``ts`` their fractions, closing point included when
    closed) — one walk, not a search per target."""
    n = len(points)
    out, i = [], 0
    for t in targets:
        while i < len(ts) - 2 and ts[i + 1] < t:
            i += 1
        span = ts[i + 1] - ts[i] if i + 1 < len(ts) else 0.0
        k = min(max((t - ts[i]) / span, 0.0), 1.0) if span > _EPS else 0.0
        out.append(points[i] + (points[(i + 1) % n] - points[i]) * k)
    return out


def _params(a, b, closed: bool):
    """The fraction of each point of ``a`` and ``b``: its index when both
    have as many points (a quad per side), else its length walked."""
    if len(a) == len(b):
        n = len(a) if closed else max(len(a) - 1, 1)
        ts = [i / n for i in range(n + 1)]
        return ts, ts
    return _fractions(a, closed), _fractions(b, closed)


def _score(a, b, closed: bool) -> float:
    """How far apart the shapes of ``a`` and ``b`` lie when walked side by
    side: lower is a straighter bridge."""
    na, nb = _normalised(a), _normalised(b)
    if len(a) == len(b):
        along = nb                               # paired one to one
    else:
        ta, tb = _params(a, b, closed)
        along = _resample(nb, tb, ta[:len(a)])
    return sum((p - q).lengthSquared() for p, q in zip(na, along))


def align_loop(a, b) -> list:
    """``b`` turned (and reversed, if better) so that walking it alongside
    the closed loop ``a`` twists the least."""
    best, best_s = list(b), None
    for d in (list(b), list(reversed(b))):
        for s in range(len(d)):
            cand = d[s:] + d[:s]
            sc = _score(a, cand, True)
            if best_s is None or sc < best_s - 1e-12:
                best, best_s = cand, sc
    return best


def _align_loops(a, b) -> tuple[list, list]:
    """``a`` and ``b`` with the one of MORE points turned to match the
    other. Turned the other way round, a square against a circle could only
    start at one of its four corners, a step of a quarter turn: the circle
    came out a corner's worth (45°) twisted whenever it was the first one
    selected."""
    if len(b) >= len(a):
        return a, align_loop(a, b)
    return align_loop(b, a), b


def align_chain(a, b) -> list:
    """``b`` in the direction that puts its ends by the open chain ``a``'s."""
    fwd = (a[0] - b[0]).length() + (a[-1] - b[-1]).length()
    rev = (a[0] - b[-1]).length() + (a[-1] - b[0]).length()
    return list(b) if fwd <= rev + 1e-12 else list(reversed(b))


def strips(a, b, closed: bool) -> list[list]:
    """The side polygons between ``a`` and ``b`` (already aligned): a quad
    wherever the two advance together, a triangle where one runs ahead.

    Of the two triangles possible at each step, the one whose new edge
    joins the closer fractions wins, so every point goes to the nearest
    point of the other side: a circle's points fan out from the square
    corner each is nearest to, not all from the corner a side starts at
    (which left one long twisted face to the next corner)."""
    ta, tb = _params(a, b, closed)
    pa = list(a) + ([a[0]] if closed else [])
    pb = list(b) + ([b[0]] if closed else [])
    na, nb = len(pa) - 1, len(pb) - 1
    i = j = 0
    out = []
    while i < na or j < nb:
        if i < na and j < nb and abs(ta[i + 1] - tb[j + 1]) <= _SAME_T:
            out.append([pa[i], pa[i + 1], pb[j + 1], pb[j]])
            i += 1
            j += 1
        elif j >= nb or (i < na and
                         abs(ta[i + 1] - tb[j]) < abs(tb[j + 1] - ta[i])):
            out.append([pa[i], pa[i + 1], pb[j]])
            i += 1
        else:
            out.append([pa[i], pb[j + 1], pb[j]])
            j += 1
    return out


def _there_and_back(chain) -> list:
    """An open chain as a flat closed loop: out along it and back."""
    return list(chain) + list(reversed(chain[1:-1]))


def _pairs(p: Profile, q: Profile) -> list[tuple]:
    """The loops of ``p`` and ``q`` to bridge, as (a, b, closed)."""
    if not p.closed and not q.closed:
        a, b = p.loops[0], q.loops[0]
        return [(a, align_chain(a, b), False)]
    if p.closed != q.closed:
        loop, line = (p, q) if p.closed else (q, p)
        if len(loop.loops) > 1:
            raise BridgeError("A face with holes can only be bridged to "
                              "another face with as many holes")
        return [(*_align_loops(loop.loops[0],
                               _there_and_back(line.loops[0])), True)]
    if len(p.loops) != len(q.loops):
        raise BridgeError("A face with holes can only be bridged to "
                          "another face with as many holes")
    a, b = p.loops[0], q.loops[0]
    out = [(*_align_loops(a, b), True)]
    # Each hole goes to the other's hole that sits in the same place
    # relative to its face, so two rings make a pipe.
    ca, cb = _centre(a), _centre(b)
    left = list(q.loops[1:])
    for h in p.loops[1:]:
        rel = _centre(h) - ca
        k = min(range(len(left)),
                key=lambda i: ((_centre(left[i]) - cb) - rel).lengthSquared())
        out.append((*_align_loops(h, left.pop(k)), True))
    return out


# ---------------------------------------------------------------- building

def _flat(quad) -> bool:
    a, b, c, d = quad
    n = QVector3D.crossProduct(b - a, c - a)
    if n.length() < _EPS:
        n = QVector3D.crossProduct(c - a, d - a)
    if n.length() < _EPS:
        return True
    size = max((p - a).length() for p in quad)
    return abs(QVector3D.dotProduct(d - a, n.normalized())) <= _FLAT * size


def _polygons(poly) -> tuple[list, tuple | None]:
    """The faces one side polygon makes — a non-flat quad split along its
    shorter diagonal — and that diagonal (to soften), if any."""
    poly = _wall(poly)
    if poly is None:
        return [], None
    if len(poly) < 4 or _flat(poly):
        return [poly], None
    a, b, c, d = poly
    if (c - a).length() <= (d - b).length():
        return [[a, b, c], [a, c, d]], (a, c)
    return [[a, b, d], [b, c, d]], (b, d)


def _all_flat(points) -> bool:
    if len(points) < 4:
        return True
    a = points[0]
    n = QVector3D()
    for p in points[1:]:
        for q in points[1:]:
            c = QVector3D.crossProduct(p - a, q - a)
            if c.length() > n.length():
                n = c
    if n.length() < _EPS:
        return True
    n = n.normalized()
    size = max((p - a).length() for p in points)
    return all(abs(QVector3D.dotProduct(p - a, n)) <= _FLAT * size
               for p in points)


def plan(profiles) -> list[list]:
    """The side polygons that bridge two profiles, without touching any
    mesh (also what a preview would draw)."""
    p, q = profiles
    if (p.face is not None or q.face is not None) and \
            _all_flat(p.points + q.points):
        raise BridgeError("Both lie on one plane: nothing to bridge")
    if set(map(_key, p.points)) & set(map(_key, q.points)) and \
            (p.closed or q.closed):
        raise BridgeError("The two to bridge must not touch")
    polys = []
    for a, b, closed in _pairs(p, q):
        polys.extend(strips(a, b, closed))
    return polys


def bridge(mesh, profiles) -> list[Face]:
    """Add the side faces between two profiles to ``mesh``; the faces among
    them stay, as caps. Returns the new faces. No undo bookkeeping: the
    caller snapshots."""
    polys = plan(profiles)
    before = {id(f) for f in mesh.faces}
    diagonals = []
    for poly in polys:
        faces, diag = _polygons(poly)
        for f in faces:
            mesh.add_face(f)
        if diag is not None:
            diagonals.append(diag)
    seed = {_key(pt) for poly in polys for pt in poly}
    new = [f for f in mesh.faces if id(f) not in before]
    run_stitch(mesh, seed, set(new), coplanar_merge=True)
    new = [f for f in mesh.faces if id(f) not in before]
    for a, b in diagonals:
        va, vb = mesh.vertex_at(a), mesh.vertex_at(b)
        e = mesh.find_edge(va, vb) if va and vb else None
        if e is not None:
            e.soft = True
    # Soften the seams of a curved bridge (two circles make a smooth
    # cylinder); real corners stay hard. Same rule as Follow Me's.
    new_ids = {id(f) for f in new}
    for e in mesh.edges:
        if e.soft or len(e.faces) != 2 or \
                not all(id(f) in new_ids for f in e.faces):
            continue
        d = QVector3D.dotProduct(e.faces[0].normal().normalized(),
                                 e.faces[1].normal().normalized())
        if _CURVE_FACET_COS < d < 0.99995:
            e.soft = True
    if new:
        orient_outward(mesh, only=new)
    return new
