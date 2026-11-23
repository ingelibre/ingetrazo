# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Terrain meshes — editable ground made of triangles (Draw ▸ Terrain).

The georeferenced 3D terrain (``georef/terrain.py``) is display-only: it
never enters ``Scene.mesh``. A terrain mesh is the opposite — ordinary
model geometry, triangles whose inner edges are soft, so it reads as one
smooth surface and can be painted, cut, exported and deformed like any
other face.

The pieces are pure and work on ANY triangulated geometry, not only on
what :func:`grid_terrain` makes: a terrain that an extension builds, a
mesh read from a DXF or a group of loose triangles deform the same way.

- :func:`grid_terrain` — a rectangular grid, two triangles per cell, flat
  or with natural irregularities (:func:`relief_heights`)
  (Draw ▸ Terrain ▸ Terrain from Scratch).
- :func:`terrain_group` — a ``Group`` holding those triangles, inner
  edges soft.
- :func:`falloff` / :func:`deform_offsets` — how far each vertex rises
  when the ground is pushed up or down at a point: all of it at the
  centre, nothing at the radius, a smooth cosine in between.
- :func:`imprint_segments` — cut lines drawn in plan into the ground: the
  triangles they cross are split along them, the new points lie on the
  ground, and the lines become hard edges (Draw ▸ Terrain ▸ Drape).
- :func:`stamp_platform` — a level platform the shape of a footprint, cut
  into the ground, with a straight slope out to a given width that meets
  the ground (Draw ▸ Terrain ▸ Stamp).
- :class:`DeformTerrainCommand`, :class:`DrapeCommand`,
  :class:`StampCommand` — one undo step each, on the loose geometry or on
  a group's own mesh from outside it.

Only the faces that look UP are ground: a terrain's vertical sides or its
bottom (an extension may add both) are left alone by the cuts.
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtGui import QVector3D

from core.history import Command

#: The most cells a grid takes along one side. A typed cell far too small
#: for the rectangle is widened to this, so a slip of the keyboard cannot
#: ask for millions of triangles: 200 × 200 cells = 80 000 triangles.
MAX_CELLS_PER_SIDE = 200

#: The shortest side or cell a grid accepts, in model units (metres).
MIN_SIZE = 1e-3


# ---- Grid --------------------------------------------------------------------

def grid_cells(width: float, depth: float, cell: float) -> tuple[int, int]:
    """How many cells a ``width`` × ``depth`` grid gets along X and Y for a
    wanted ``cell`` size: the nearest whole count (at least one, at most
    :data:`MAX_CELLS_PER_SIDE`), so the cells fill the rectangle exactly and
    come out as close to square and to ``cell`` as the sides allow."""
    width, depth = abs(width), abs(depth)
    cell = max(abs(cell), MIN_SIZE)

    def count(side: float) -> int:
        return max(1, min(MAX_CELLS_PER_SIDE, int(round(side / cell))))

    return count(width), count(depth)


def relief_heights(xs, ys, relief: float, seed=None):
    """Natural irregularities for ground at the plan points ``xs``, ``ys``:
    gentle swells and hollows, never a spike, ``relief`` at the highest or
    deepest point and averaging zero — so the ground keeps the level it was
    laid at.

    Value noise: random heights on a coarse lattice, eased between its
    nodes with a cosine, at three scales (the whole patch in two or three
    waves, then half and a quarter of that, each half as tall). ``seed``
    repeats a terrain; ``None`` draws a new one. Returns a NumPy array, one
    height per point."""
    import numpy as np

    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    out = np.zeros_like(xs)
    if relief <= 0.0 or not len(xs):
        return out
    rng = np.random.default_rng(seed)
    x0, y0 = xs.min(), ys.min()
    span = max(xs.max() - x0, ys.max() - y0, MIN_SIZE)

    def ease(t):
        return 0.5 - 0.5 * np.cos(np.pi * t)

    for octave in range(3):
        wave = span / (2.5 * 2 ** octave)
        u, v = (xs - x0) / wave, (ys - y0) / wave
        nu, nv = int(np.floor(u.max())) + 2, int(np.floor(v.max())) + 2
        lattice = rng.uniform(-1.0, 1.0, size=(nv, nu))
        i, j = np.floor(u).astype(int), np.floor(v).astype(int)
        tu, tv = ease(u - i), ease(v - j)
        top = lattice[j, i] * (1 - tu) + lattice[j, i + 1] * tu
        bot = lattice[j + 1, i] * (1 - tu) + lattice[j + 1, i + 1] * tu
        out += (top * (1 - tv) + bot * tv) * 0.5 ** octave
    out -= out.mean()
    peak = np.abs(out).max()
    if peak > 1e-12:
        out *= relief / peak
    return out


def grid_terrain(corner_a: QVector3D, corner_b: QVector3D, cell: float,
                 relief: float = 0.0, seed=None):
    """A grid over the rectangle with opposite corners ``corner_a`` and
    ``corner_b``, laid at ``corner_a``'s height — flat, or with natural
    irregularities up to ``relief`` above and below it
    (:func:`relief_heights`; ``seed`` repeats the same ones).

    Returns ``(vertices, triangles)``: ``vertices`` a list of
    :class:`QVector3D`, row by row from the low-Y side, and ``triangles``
    index triples, counter-clockwise seen from above (normals point up).
    Each cell is split along alternating diagonals, a chequer that keeps
    the grid from leaning one way when it is later pushed into a mound.
    ``([], [])`` for a rectangle with no area."""
    x0, x1 = sorted((corner_a.x(), corner_b.x()))
    y0, y1 = sorted((corner_a.y(), corner_b.y()))
    z = corner_a.z()
    if x1 - x0 < MIN_SIZE or y1 - y0 < MIN_SIZE:
        return [], []
    nx, ny = grid_cells(x1 - x0, y1 - y0, cell)
    dx, dy = (x1 - x0) / nx, (y1 - y0) / ny
    plan = [(x0 + i * dx if i < nx else x1, y0 + j * dy if j < ny else y1)
            for j in range(ny + 1) for i in range(nx + 1)]
    rise = relief_heights([p[0] for p in plan], [p[1] for p in plan],
                          relief, seed)
    vertices = [QVector3D(x, y, z + float(h))
                for (x, y), h in zip(plan, rise)]
    row = nx + 1
    triangles = []
    for j in range(ny):
        for i in range(nx):
            a = j * row + i          # (i, j)
            b = a + 1                # (i+1, j)
            c = a + row + 1          # (i+1, j+1)
            d = a + row              # (i, j+1)
            if (i + j) % 2 == 0:
                triangles += [(a, b, c), (a, c, d)]
            else:
                triangles += [(a, b, d), (b, c, d)]
    return vertices, triangles


def soften_inner_edges(mesh) -> int:
    """Mark every edge two faces share as soft, so the triangles read as one
    surface; the rim stays a hard edge. Returns how many were softened."""
    n = 0
    for e in mesh.edges:
        if len(e.faces) >= 2 and not e.soft:
            e.soft = True
            n += 1
    return n


def terrain_mesh(vertices, triangles):
    """A :class:`core.mesh.Mesh` holding ``triangles`` over ``vertices``,
    inner edges soft."""
    import numpy as np
    from core.mesh import Mesh

    mesh = Mesh()
    if not triangles:
        return mesh
    pos = np.array([(vertices[k].x(), vertices[k].y(), vertices[k].z())
                    for tri in triangles for k in tri], dtype=np.float64)
    count = len(triangles)
    mesh.add_faces_bulk(pos, np.full(count, 3, dtype=np.int64),
                        np.ones(count, dtype=np.int64))
    soften_inner_edges(mesh)
    return mesh


def terrain_group(vertices, triangles, name: Optional[str] = None):
    """A new :class:`core.group.Group` holding the terrain triangles."""
    from core.group import Group
    from core.i18n import tr

    return Group(terrain_mesh(vertices, triangles), name or tr("Terrain"))


# ---- Deform ------------------------------------------------------------------

def falloff(distance: float, radius: float) -> float:
    """The share of the push a point ``distance`` from the centre takes: 1 at
    the centre, 0 at ``radius`` and beyond, a cosine in between — level at
    both ends, so the mound neither peaks nor leaves a step at its rim."""
    if radius <= 0.0 or distance >= radius:
        return 0.0
    return 0.5 * (1.0 + math.cos(math.pi * max(distance, 0.0) / radius))


def _world(xform, p: QVector3D) -> QVector3D:
    return xform.map(p) if xform is not None else QVector3D(p)


def deform_offsets(mesh, center: QVector3D, radius: float, height: float,
                   xform=None) -> dict:
    """``{vertex: local offset}`` for the vertices a push of ``height`` at
    ``center`` moves: straight up (down for a negative height) in the world,
    by the :func:`falloff` of their distance from ``center`` measured in plan
    (X and Y only — a slope rises evenly, whatever its tilt).

    ``mesh`` is in its own coordinates, placed in the world by ``xform``
    (``None`` = already in the world, a classic group or the loose
    geometry); the offsets come back in those same local coordinates."""
    out = {}
    if radius <= 0.0 or abs(height) < 1e-9:
        return out
    inv = None
    if xform is not None:
        inv, ok = xform.inverted()
        if not ok:
            return out
    cx, cy = center.x(), center.y()
    r2 = radius * radius
    for v in mesh.vertices:
        w = _world(xform, v.position)
        d2 = (w.x() - cx) ** 2 + (w.y() - cy) ** 2
        if d2 >= r2:
            continue
        rise = falloff(math.sqrt(d2), radius) * height
        if abs(rise) < 1e-9:
            continue
        up = QVector3D(0.0, 0.0, rise)
        out[v] = inv.mapVector(up) if inv is not None else up
    return out


def deform_preview(mesh, center, radius, height, xform=None):
    """The edges a push would move, as world ``[(a, b), ...]`` at their new
    places — the live preview while the height is being chosen."""
    offsets = deform_offsets(mesh, center, radius, height, xform)
    if not offsets:
        return []
    seen = set()
    lines = []
    zero = QVector3D()
    for v in offsets:
        for e in v.edges:
            if id(e) in seen:
                continue
            seen.add(id(e))
            a = e.v0.position + offsets.get(e.v0, zero)
            b = e.v1.position + offsets.get(e.v1, zero)
            lines.append((_world(xform, a), _world(xform, b)))
    return lines


def deform_mesh(mesh, center, radius, height, xform=None) -> int:
    """Push the ground at ``center`` up (or down) by ``height`` over
    ``radius``. Faces with more than three corners that the push bends out
    of their plane are folded into planar pieces, the way a moved vertex
    folds them. Returns how many vertices moved."""
    from core.mesh import _key
    from core.topology import fold_nonplanar_faces

    offsets = deform_offsets(mesh, center, radius, height, xform)
    for v, off in offsets.items():
        mesh.place_vertex(v, v.position + off)
    if offsets and any(len(f.loop) > 3 or f.hole_loops for f in mesh.faces):
        fold_nonplanar_faces(mesh, moved={_key(v.position) for v in offsets})
    return len(offsets)


# ---- Cutting lines into the ground ------------------------------------------

#: Closer than this (model units, in plan) to a vertex or an edge's end
#: counts as on it — a cut never leaves a sliver thinner than this.
SNAP = 1e-3
#: A face whose normal points up at least this much (its Z) is ground.
UPWARD = 0.05


def _vertical(xform) -> bool:
    """Whether ``xform`` keeps the vertical vertical (it turns round Z,
    moves and scales evenly): then plan in the world is plan in the mesh."""
    if xform is None:
        return True
    up = xform.mapVector(QVector3D(0.0, 0.0, 1.0))
    return (up.length() > 1e-9
            and math.hypot(up.x(), up.y()) <= 1e-6 * up.length())


def _bbox_xy(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _along(a: QVector3D, b: QVector3D, x: float, y: float):
    """``(t, distance)`` of plan point ``(x, y)`` from segment a→b: where
    along it the nearest point lies (``t``, unclamped) and how far, in
    plan, from the segment itself."""
    dx, dy = b.x() - a.x(), b.y() - a.y()
    l2 = dx * dx + dy * dy
    if l2 < 1e-24:
        return 0.0, math.hypot(x - a.x(), y - a.y())
    t = ((x - a.x()) * dx + (y - a.y()) * dy) / l2
    tc = max(0.0, min(1.0, t))
    return t, math.hypot(x - (a.x() + dx * tc), y - (a.y() + dy * tc))


def _cross(ax, ay, bx, by, p: QVector3D, q: QVector3D):
    """``(t, s)`` where plan segments A→B and p→q cross (``t`` along A→B,
    ``s`` along p→q), or ``None`` when they are parallel or miss."""
    rx, ry = bx - ax, by - ay
    sx, sy = q.x() - p.x(), q.y() - p.y()
    den = rx * sy - ry * sx
    if abs(den) < 1e-14:
        return None
    qx, qy = p.x() - ax, p.y() - ay
    t = (qx * sy - qy * sx) / den
    s = (qx * ry - qy * rx) / den
    if t < 0.0 or t > 1.0 or s < 0.0 or s > 1.0:
        return None
    return t, s


class _Ground:
    """The upward faces of a mesh within a plan rectangle, as triangles in a
    bucket index, and the splits that cut lines into them. Faces with more
    corners are triangulated first (inner edges soft): a cut works on
    triangles."""

    def __init__(self, mesh, rect, margin: float) -> None:
        from collections import defaultdict
        self.mesh = mesh
        x0, y0, x1, y1 = rect
        x0, y0, x1, y1 = x0 - margin, y0 - margin, x1 + margin, y1 + margin
        self.faces = set()
        self.buckets = defaultdict(set)
        candidates = []
        for f in list(mesh.faces):
            if f.normal().z() <= UPWARD:
                continue
            fx0, fy0, fx1, fy1 = self._fbox(f)
            if fx1 < x0 or fx0 > x1 or fy1 < y0 or fy0 > y1:
                continue
            candidates.append(f)
        area = max((x1 - x0) * (y1 - y0), 1e-6)
        self.size = max(math.sqrt(area / max(len(candidates), 1)) * 1.5, 0.05)
        for f in candidates:
            self._add(f)
        for f in candidates:
            if len(f.loop) != 3 or f.hole_loops:
                tris = f.triangulate()
                if tris:
                    self._replace(f, [list(t) for t in tris])

    # ---- Index ----------------------------------------------------------
    @staticmethod
    def _fbox(f):
        return _bbox_xy([(v.position.x(), v.position.y()) for v in f.loop])

    def _cells(self, x0, y0, x1, y1):
        s = self.size
        for i in range(int(math.floor(x0 / s)), int(math.floor(x1 / s)) + 1):
            for j in range(int(math.floor(y0 / s)),
                           int(math.floor(y1 / s)) + 1):
                yield i, j

    def _add(self, f) -> None:
        self.faces.add(f)
        for c in self._cells(*self._fbox(f)):
            self.buckets[c].add(f)

    def _drop(self, f) -> None:
        self.faces.discard(f)
        for c in self._cells(*self._fbox(f)):
            self.buckets[c].discard(f)

    def near(self, x0, y0, x1, y1) -> set:
        out = set()
        for c in self._cells(min(x0, x1), min(y0, y1),
                             max(x0, x1), max(y0, y1)):
            got = self.buckets.get(c)
            if got:
                out |= got
        return out

    def vertices(self) -> set:
        return {v for f in self.faces for v in f.loop}

    # ---- Edits ----------------------------------------------------------
    def _replace(self, old, loops) -> list:
        """Swap face ``old`` for faces on ``loops`` (corners — vertices or
        points — in the same turn), carrying its paint; the edges the new
        faces add are soft. Returns the new faces."""
        mesh = self.mesh
        before = {id(e) for e in mesh.edges}
        attrs = dict(old.attrs)
        indexed = old in self.faces
        if indexed:
            self._drop(old)
        mesh.remove_face(old)
        out = []
        for loop in loops:
            f = mesh.add_face([QVector3D(c.position) if hasattr(c, "position")
                               else QVector3D(c) for c in loop])
            f.attrs = dict(attrs)
            out.append(f)
            if indexed:
                self._add(f)
        for f in out:
            n = len(f.loop)
            for k in range(n):
                e = mesh.find_edge(f.loop[k], f.loop[(k + 1) % n])
                if e is not None and id(e) not in before:
                    e.soft = True
        return out

    def split_edge(self, e, t: float):
        """Split edge ``e`` at ``t`` along it (0 = ``e.v0``): every face on
        it takes the new corner — a triangle is cut in two toward its
        opposite corner, a larger face just gains the corner. The two
        halves keep the edge's flags. Returns the new vertex."""
        from core.mesh import edge_flags, stamp_edge_flags
        mesh = self.mesh
        v0, v1 = e.v0, e.v1
        p = v0.position + (v1.position - v0.position) * t
        flags = edge_flags(e)
        jobs = []
        for f in list(e.faces):
            loop = f.loop
            n = len(loop)
            for k in range(n):
                u, w = loop[k], loop[(k + 1) % n]
                if {id(u), id(w)} != {id(v0), id(v1)}:
                    continue
                if n == 3 and not f.hole_loops:
                    c = loop[(k + 2) % 3]
                    jobs.append((f, [[u, p, c], [p, w, c]]))
                elif not f.hole_loops:
                    jobs.append((f, [loop[:k + 1] + [p] + loop[k + 1:]]))
                break
        for f, loops in jobs:
            self._replace(f, loops)
        if not e.faces and e in v0.edges:
            mesh.remove_edge(e)
        v = mesh.vertex_at(p)
        if v is not None:
            for end in (v0, v1):
                half = mesh.find_edge(end, v)
                if half is not None:
                    stamp_edge_flags(half, flags)
        return v

    def locate(self, x: float, y: float):
        """``(face, weights)`` of the ground triangle under ``(x, y)``."""
        for f in self.near(x, y, x, y):
            if len(f.loop) != 3:
                continue
            a, b, c = (v.position for v in f.loop)
            d = ((b.y() - c.y()) * (a.x() - c.x())
                 + (c.x() - b.x()) * (a.y() - c.y()))
            if abs(d) < 1e-14:
                continue
            l0 = ((b.y() - c.y()) * (x - c.x())
                  + (c.x() - b.x()) * (y - c.y())) / d
            l1 = ((c.y() - a.y()) * (x - c.x())
                  + (a.x() - c.x()) * (y - c.y())) / d
            l2 = 1.0 - l0 - l1
            if min(l0, l1, l2) >= -1e-9:
                return f, (l0, l1, l2)
        return None, None

    def insert_point(self, x: float, y: float):
        """A vertex of the ground at ``(x, y)`` in plan, on the ground:
        the one already there, a new one splitting the edge it lies on, or
        one splitting the triangle round it. ``None`` off the ground."""
        f, w = self.locate(x, y)
        if f is None:
            return None
        loop = f.loop
        for v in loop:
            if math.hypot(v.position.x() - x, v.position.y() - y) < SNAP:
                return v
        for k in range(3):
            u, v = loop[k], loop[(k + 1) % 3]
            t, d = _along(u.position, v.position, x, y)
            if d < SNAP and 0.0 < t < 1.0:
                e = self.mesh.find_edge(u, v)
                if e is not None:
                    return self.split_edge(e, t if e.v0 is u else 1.0 - t)
        a, b, c = (v.position for v in loop)
        z = a.z() * w[0] + b.z() * w[1] + c.z() * w[2]
        p = QVector3D(x, y, z)
        self._replace(f, [[loop[0], loop[1], p], [loop[1], loop[2], p],
                          [loop[2], loop[0], p]])
        return self.mesh.vertex_at(p)

    def cut_segment(self, ax, ay, bx, by) -> list:
        """Cut the plan segment A→B into the ground. Returns the ground
        edges that now run along it, in order."""
        length = math.hypot(bx - ax, by - ay)
        if length < SNAP:
            return []
        self.insert_point(ax, ay)
        self.insert_point(bx, by)
        tiny = SNAP / length
        crossings = []
        seen = set()
        for f in self.near(ax, ay, bx, by):
            n = len(f.loop)
            for k in range(n):
                e = self.mesh.find_edge(f.loop[k], f.loop[(k + 1) % n])
                if e is None or id(e) in seen:
                    continue
                seen.add(id(e))
                hit = _cross(ax, ay, bx, by, e.v0.position, e.v1.position)
                if hit is None:
                    continue
                t, s = hit
                elen = math.hypot(e.v1.position.x() - e.v0.position.x(),
                                  e.v1.position.y() - e.v0.position.y())
                es = SNAP / max(elen, 1e-12)
                if tiny < t < 1.0 - tiny and es < s < 1.0 - es:
                    crossings.append((t, e, s))
        for _t, e, s in sorted(crossings, key=lambda c: c[0]):
            if e in e.v0.edges:
                self.split_edge(e, s)
        # The ground vertices now on the segment, in order along it.
        a = QVector3D(ax, ay, 0.0)
        b = QVector3D(bx, by, 0.0)
        on = {}
        for f in self.near(ax, ay, bx, by):
            for v in f.loop:
                t, d = _along(a, b, v.position.x(), v.position.y())
                if d < SNAP and -tiny <= t <= 1.0 + tiny:
                    on[id(v)] = (t, v)
        chain = sorted(on.values(), key=lambda tv: tv[0])
        edges = []
        for (_t0, u), (_t1, v) in zip(chain, chain[1:]):
            e = self.mesh.find_edge(u, v)
            if e is not None:
                edges.append(e)
        return edges


def _to_local_xy(points, xform):
    """World plan points → the mesh's own plan (``xform`` keeps vertical)."""
    if xform is None:
        return [(p.x(), p.y()) for p in points]
    inv, _ok = xform.inverted()
    out = []
    for p in points:
        q = inv.map(QVector3D(p.x(), p.y(), 0.0))
        out.append((q.x(), q.y()))
    return out


def imprint_segments(mesh, segments, xform=None) -> list:
    """Cut world segments ``[(a, b), ...]`` into the ground of ``mesh``,
    seen from above: each becomes ground edges along it, on the ground,
    hard (shown). Returns those edges; ``[]`` when none crosses the
    ground or the mesh is placed tilted (``xform`` not keeping vertical)."""
    if not segments or not _vertical(xform):
        return []
    flat = _to_local_xy([p for seg in segments for p in seg], xform)
    pairs = list(zip(flat[0::2], flat[1::2]))
    ground = _Ground(mesh, _bbox_xy(flat), SNAP * 10)
    out = []
    for (ax, ay), (bx, by) in pairs:
        for e in ground.cut_segment(ax, ay, bx, by):
            e.soft = False
            e.hidden = False
            out.append(e)
    return out


# ---- Platform ----------------------------------------------------------------

def _signed_distance(px, py, poly):
    """Signed plan distance from points ``px, py`` (arrays) to the closed
    polygon ``poly`` (``[(x, y), ...]``): negative inside."""
    import numpy as np
    px = np.asarray(px, dtype=np.float64)
    py = np.asarray(py, dtype=np.float64)
    best = np.full(px.shape, np.inf)
    inside = np.zeros(px.shape, dtype=bool)
    n = len(poly)
    for k in range(n):
        x0, y0 = poly[k]
        x1, y1 = poly[(k + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        l2 = dx * dx + dy * dy
        if l2 > 1e-24:
            t = np.clip(((px - x0) * dx + (py - y0) * dy) / l2, 0.0, 1.0)
        else:
            t = np.zeros(px.shape)
        best = np.minimum(best, np.hypot(px - (x0 + t * dx),
                                         py - (y0 + t * dy)))
        if dy != 0.0:
            crosses = (y0 > py) != (y1 > py)
            xi = x0 + (py - y0) * dx / dy
            inside ^= crosses & (px < xi)
    return np.where(inside, -best, best)


def platform_heights(points, footprint, height: float, slope: float):
    """New world heights for world ``points`` under a platform: ``height``
    inside the plan ``footprint`` (``[(x, y), ...]``), then a straight
    slope back to the ground over ``slope`` of plan width, the ground's own
    height beyond."""
    import numpy as np
    xs = np.array([p.x() for p in points])
    ys = np.array([p.y() for p in points])
    zs = np.array([p.z() for p in points])
    d = _signed_distance(xs, ys, footprint)
    out = zs.copy()
    inside = d <= SNAP
    out[inside] = height
    if slope > 0.0:
        band = (~inside) & (d < slope)
        out[band] = height + (zs[band] - height) * (d[band] / slope)
    return out


def stamp_platform(mesh, footprint, height: float, slope: float,
                   xform=None) -> int:
    """Cut a level platform into the ground of ``mesh``: the plan of the
    world ``footprint`` (its outline, a list of points) at world
    ``height``, its edge cut exactly into the ground and shown, and a
    straight slope ``slope`` wide out to where it meets the ground —
    cutting where the ground stands higher, filling where it is lower.
    Returns how many ground vertices moved; 0 when the footprint is not
    on the ground or the mesh is placed tilted."""
    from core.mesh import _key
    from core.topology import fold_nonplanar_faces

    footprint = [QVector3D(p) for p in footprint]
    pts = [(p.x(), p.y()) for p in footprint]
    if len(pts) < 3 or not _vertical(xform):
        return 0
    imprint_segments(mesh, list(zip(footprint, footprint[1:] + footprint[:1])),
                     xform)
    flat = _to_local_xy(footprint, xform)
    scale = 1.0
    if xform is not None:
        scale = max(xform.mapVector(QVector3D(1.0, 0.0, 0.0)).length(), 1e-12)
    ground = _Ground(mesh, _bbox_xy(flat), max(slope, 0.0) / scale + SNAP * 10)
    verts = list(ground.vertices())
    if not verts:
        return 0
    world = [_world(xform, v.position) for v in verts]
    zs = platform_heights(world, pts, height, max(slope, 0.0))
    inv = xform.inverted()[0] if xform is not None else None
    moved = []
    for v, w, z in zip(verts, world, zs):
        if abs(float(z) - w.z()) < 1e-9:
            continue
        target = QVector3D(w.x(), w.y(), float(z))
        mesh.place_vertex(v, inv.map(target) if inv is not None else target)
        moved.append(v)
    if moved and any(len(f.loop) > 3 or f.hole_loops for f in mesh.faces):
        fold_nonplanar_faces(mesh, moved={_key(v.position) for v in moved})
    return len(moved)


# ---- Flip edge ---------------------------------------------------------------

#: Why an edge cannot be flipped — the keys :func:`flip_problem` returns.
FLIP_RIM = "rim"            # one triangle only: the terrain's rim
FLIP_POLYGON = "polygon"    # not between two plain triangles
FLIP_HARD = "hard"          # a line drawn or cut on the ground
FLIP_CONCAVE = "concave"    # the other diagonal would fold the pair


def _opposite(face, u, w):
    """The corner of triangle ``face`` that is neither ``u`` nor ``w``."""
    for v in face.loop:
        if v is not u and v is not w:
            return v
    return None


def flip_pair(edge):
    """``(x, y, c, d)`` of the two triangles on ``edge``: ``x → y`` the
    edge the way the first triangle turns, ``c`` that triangle's third
    corner, ``d`` the other's — the quad ``x, d, y, c`` in its turn."""
    f1, f2 = edge.faces[0], edge.faces[1]
    loop = f1.loop
    for k in range(3):
        x, y = loop[k], loop[(k + 1) % 3]
        if {id(x), id(y)} == {id(edge.v0), id(edge.v1)}:
            return x, y, loop[(k + 2) % 3], _opposite(f2, x, y)
    return None


def flip_problem(mesh, edge, xform=None):
    """``None`` when ``edge`` can be flipped — turned to the other diagonal
    of the two triangles that share it — or why not (a ``FLIP_*`` key).
    Only soft (or hidden) edges flip: a hard edge inside the ground is a
    line someone drew or cut — a platform's outline, a draped path."""
    faces = list(edge.faces)
    if len(faces) < 2:
        return FLIP_RIM
    if len(faces) > 2 or any(len(f.loop) != 3 or f.hole_loops
                             for f in faces):
        return FLIP_POLYGON
    if not (edge.soft or edge.hidden):
        return FLIP_HARD
    pair = flip_pair(edge)
    if pair is None or pair[3] is None or pair[2] is pair[3]:
        return FLIP_POLYGON
    x, y, c, d = pair
    if mesh.find_edge(c, d) is not None:
        return FLIP_CONCAVE
    # Seen from above, the new diagonal must cross the old one inside
    # both: the pair is a convex quad, and the two new triangles cover
    # just the ground the old ones did.
    px, py, pc, pd = (_world(xform, v.position) for v in (x, y, c, d))
    hit = _cross(pc.x(), pc.y(), pd.x(), pd.y(), px, py)
    eps = 1e-6
    if hit is None or not (eps < hit[0] < 1.0 - eps
                           and eps < hit[1] < 1.0 - eps):
        return FLIP_CONCAVE
    return None


def flip_preview(edge, xform=None):
    """The world lines of a flip: the quad round the two triangles and
    the diagonal it would take; ``[]`` when the edge has no such pair."""
    if len(edge.faces) != 2 or any(len(f.loop) != 3 for f in edge.faces):
        return []
    pair = flip_pair(edge)
    if pair is None or pair[3] is None:
        return []
    x, y, c, d = (_world(xform, v.position) for v in pair)
    return [(x, d), (d, y), (y, c), (c, x), (c, d)]


def flip_edge(mesh, edge, xform=None) -> bool:
    """Turn ``edge`` into the other diagonal of its two triangles, when
    :func:`flip_problem` allows it. Each new triangle keeps the paint of
    the one it mostly comes from; the new diagonal takes the old one's
    flags (soft, hidden…). Returns whether it flipped."""
    from core.mesh import edge_flags, stamp_edge_flags
    if flip_problem(mesh, edge, xform) is not None:
        return False
    x, y, c, d = flip_pair(edge)
    f1, f2 = edge.faces[0], edge.faces[1]
    flags = edge_flags(edge)
    attrs1, attrs2 = dict(f1.attrs), dict(f2.attrs)
    pos = {k: QVector3D(v.position) for k, v in
           (("x", x), ("y", y), ("c", c), ("d", d))}
    mesh.remove_face(f1)
    mesh.remove_face(f2)
    if not edge.faces and edge in edge.v0.edges:
        mesh.remove_edge(edge)
    a = mesh.add_face([pos["x"], pos["d"], pos["c"]])
    b = mesh.add_face([pos["d"], pos["y"], pos["c"]])
    a.attrs = attrs1
    b.attrs = attrs2
    diag = mesh.find_edge(mesh.vertex_at(pos["c"]), mesh.vertex_at(pos["d"]))
    if diag is not None:
        stamp_edge_flags(diag, flags)
    return True


# ---- Add detail --------------------------------------------------------------

def _plan_distance_to_triangle(x, y, a, b, c) -> float:
    """Plan distance from ``(x, y)`` to triangle ``a b c`` (0 inside)."""
    def side(p, q):
        return (q.x() - p.x()) * (y - p.y()) - (q.y() - p.y()) * (x - p.x())
    s = (side(a, b), side(b, c), side(c, a))
    if all(v >= -1e-12 for v in s) or all(v <= 1e-12 for v in s):
        return 0.0
    return min(_along(p, q, x, y)[1] for p, q in ((a, b), (b, c), (c, a)))


def _detail_marks(mesh, center: QVector3D, radius: float, xform=None):
    """``(chosen, marked)``: the ground triangles within ``radius`` of
    ``center`` in plan (world) — touching it, or under it at radius 0 —
    and the ids of the edges a split at their middles cuts. A triangle
    outside whose three sides are all cut joins the chosen, so no
    neighbour is left with a corner on each side."""
    def is_tri(f):
        return len(f.loop) == 3 and not f.hole_loops

    cx, cy = center.x(), center.y()
    r = max(float(radius), 0.0)
    chosen = []
    for f in mesh.faces:
        if not is_tri(f):
            continue
        a, b, c = (_world(xform, v.position) for v in f.loop)
        n = QVector3D.crossProduct(b - a, c - a)
        if n.length() < 1e-12 or n.z() / n.length() <= UPWARD:
            continue
        if _plan_distance_to_triangle(cx, cy, a, b, c) <= r:
            chosen.append(f)
    marked = {}
    for f in chosen:
        for k in range(3):
            e = mesh.find_edge(f.loop[k], f.loop[(k + 1) % 3])
            if e is not None and not any(g.hole_loops for g in e.faces):
                marked[id(e)] = e
    picked = {id(f) for f in chosen}
    grew = True
    while grew:
        grew = False
        for e in list(marked.values()):
            for f in e.faces:
                if id(f) in picked or not is_tri(f):
                    continue
                sides = [mesh.find_edge(f.loop[k], f.loop[(k + 1) % 3])
                         for k in range(3)]
                if all(s is not None and id(s) in marked for s in sides):
                    picked.add(id(f))
                    chosen.append(f)
                    grew = True
    return chosen, marked


def _mid(e) -> QVector3D:
    return (e.v0.position + e.v1.position) * 0.5


def _split_loops(mesh, face, marked):
    """The loops (positions) ``face`` becomes once its ``marked`` edges
    are cut at their middles: a triangle in 4, 3 or 2 (no corner left on
    a side), a larger face just gaining the corners."""
    loop = face.loop
    n = len(loop)
    pts = [QVector3D(v.position) for v in loop]
    mids = []
    for k in range(n):
        e = mesh.find_edge(loop[k], loop[(k + 1) % n])
        mids.append(_mid(e) if e is not None and id(e) in marked else None)
    if n != 3:
        out = []
        for k in range(n):
            out.append(pts[k])
            if mids[k] is not None:
                out.append(mids[k])
        return [out]
    count = sum(m is not None for m in mids)
    if count == 3:
        m0, m1, m2 = mids
        return [[pts[0], m0, m2], [m0, pts[1], m1], [m2, m1, pts[2]],
                [m0, m1, m2]]
    if count == 1:
        k = next(i for i, m in enumerate(mids) if m is not None)
        p0, p1, p2 = pts[k], pts[(k + 1) % 3], pts[(k + 2) % 3]
        return [[p0, mids[k], p2], [mids[k], p1, p2]]
    # Two sides cut: the corner between them, and the quad left split
    # along its shorter diagonal.
    k = next(i for i, m in enumerate(mids) if m is None)   # the whole side
    p0, p1, p2 = pts[k], pts[(k + 1) % 3], pts[(k + 2) % 3]
    ma, mb = mids[(k + 1) % 3], mids[(k + 2) % 3]           # on p1p2, p2p0
    tri = [ma, p2, mb]
    if (ma - p0).length() <= (p1 - mb).length():
        return [tri, [p0, p1, ma], [p0, ma, mb]]
    return [tri, [p0, p1, mb], [p1, ma, mb]]


def detail_preview(mesh, center: QVector3D, radius: float, xform=None):
    """The new edges Add Detail would draw, as world lines — the middle
    triangle of every chosen one; ``[]`` when nothing is within reach."""
    chosen, marked = _detail_marks(mesh, center, radius, xform)
    lines = []
    for f in chosen:
        loop = f.loop
        es = [mesh.find_edge(loop[k], loop[(k + 1) % 3]) for k in range(3)]
        mids = [_world(xform, _mid(e)) for e in es if e is not None
                and id(e) in marked]
        for k in range(len(mids)):
            lines.append((mids[k], mids[(k + 1) % len(mids)]))
    return lines


def add_detail(mesh, center: QVector3D, radius: float, xform=None) -> int:
    """Split the ground triangles within ``radius`` of world ``center``
    (in plan; at 0, the one under it) into four, cutting each side at its
    middle — the ground keeps its shape, with more corners to deform or
    stamp. Neighbours that take a new corner are split too (in two or
    three), so no crack opens. The new edges are soft; the halves of a cut
    edge keep its flags and every piece its face's paint. Returns how many
    triangles were split in four."""
    from core.mesh import edge_flags, stamp_edge_flags
    chosen, marked = _detail_marks(mesh, center, radius, xform)
    if not chosen:
        return 0
    faces = {}
    for e in marked.values():
        for f in e.faces:
            faces[id(f)] = f
    jobs = [(f, _split_loops(mesh, f, marked), dict(f.attrs))
            for f in faces.values()]
    cuts = [(QVector3D(e.v0.position), QVector3D(e.v1.position), _mid(e),
             edge_flags(e)) for e in marked.values()]
    before = {id(e) for e in mesh.edges}
    for f, _loops, _attrs in jobs:
        mesh.remove_face(f)
    for e in marked.values():
        if not e.faces and e in e.v0.edges:
            mesh.remove_edge(e)
    new_faces = []
    for _f, loops, attrs in jobs:
        for loop in loops:
            g = mesh.add_face(loop)
            g.attrs = dict(attrs)
            new_faces.append(g)
    for g in new_faces:
        n = len(g.loop)
        for k in range(n):
            e = mesh.find_edge(g.loop[k], g.loop[(k + 1) % n])
            if e is not None and id(e) not in before:
                e.soft = True
    for a, b, m, flags in cuts:
        vm = mesh.vertex_at(m)
        for end in (a, b):
            half = mesh.find_edge(mesh.vertex_at(end), vm) if vm else None
            if half is not None:
                stamp_edge_flags(half, flags)
    return len(chosen)


# ---- Commands ----------------------------------------------------------------

class _TerrainEdit(Command):
    """An edit of one mesh — the loose geometry (the open group's, inside
    one) or a group's own mesh, edited from outside without opening it —
    placed in the world by ``xform`` (``None`` when it already is). Undo and
    redo restore snapshots of that mesh, so object identity survives for
    the history around it. ``result`` is what :meth:`apply` returned."""

    keeps_paint = True

    def __init__(self, mesh, xform=None) -> None:
        self.mesh = mesh
        self.xform = xform
        self.result = 0
        self._before: Optional[dict] = None
        self._after: Optional[dict] = None

    def apply(self) -> int:  # pragma: no cover - overridden
        raise NotImplementedError

    def do(self, scene) -> None:
        if self._after is not None:              # redo
            self.mesh.restore_state(self._after)
            scene.version += 1
            return
        self._before = self.mesh.capture_state()
        self.result = self.apply()
        self._after = self.mesh.capture_state()
        scene.version += 1

    def undo(self, scene) -> None:
        if self._before is not None:
            self.mesh.restore_state(self._before)
            scene.version += 1


class DeformTerrainCommand(_TerrainEdit):
    """Push the ground up or down at a point, one undo step; ``moved`` is
    how many vertices it moved."""

    def __init__(self, mesh, center: QVector3D, radius: float, height: float,
                 xform=None) -> None:
        super().__init__(mesh, xform)
        self.center = QVector3D(center)
        self.radius = float(radius)
        self.height = float(height)

    @property
    def moved(self) -> int:
        return self.result

    def apply(self) -> int:
        return deform_mesh(self.mesh, self.center, self.radius, self.height,
                           self.xform)


class DrapeCommand(_TerrainEdit):
    """Cut world segments into the ground, one undo step; ``result`` is how
    many ground edges they became."""

    def __init__(self, mesh, segments, xform=None) -> None:
        super().__init__(mesh, xform)
        self.segments = [(QVector3D(a), QVector3D(b)) for a, b in segments]

    def apply(self) -> int:
        return len(imprint_segments(self.mesh, self.segments, self.xform))


class StampCommand(_TerrainEdit):
    """Cut a level platform with its slope into the ground, one undo step;
    ``result`` is how many ground vertices moved."""

    def __init__(self, mesh, footprint, height: float, slope: float,
                 xform=None) -> None:
        super().__init__(mesh, xform)
        self.footprint = [QVector3D(p) for p in footprint]
        self.height = float(height)
        self.slope = float(slope)

    def apply(self) -> int:
        return stamp_platform(self.mesh, self.footprint, self.height,
                              self.slope, self.xform)


class FlipEdgeCommand(_TerrainEdit):
    """Flip one edge of the ground to the other diagonal of its two
    triangles, one undo step. The edge is found again by its ends (local
    positions), so the command does not hold on to objects a snapshot
    replaces. ``result`` is 1 when it flipped, 0 when not; ``problem``
    the ``FLIP_*`` key of why not."""

    def __init__(self, mesh, a: QVector3D, b: QVector3D, xform=None) -> None:
        super().__init__(mesh, xform)
        self.a = QVector3D(a)
        self.b = QVector3D(b)
        self.problem = None

    def apply(self) -> int:
        va, vb = self.mesh.vertex_at(self.a), self.mesh.vertex_at(self.b)
        edge = self.mesh.find_edge(va, vb) if va and vb else None
        if edge is None:
            self.problem = FLIP_POLYGON
            return 0
        self.problem = flip_problem(self.mesh, edge, self.xform)
        if self.problem is not None:
            return 0
        return int(flip_edge(self.mesh, edge, self.xform))


class AddDetailCommand(_TerrainEdit):
    """Split the ground triangles round a point in four, one undo step;
    ``result`` is how many were split."""

    def __init__(self, mesh, center: QVector3D, radius: float,
                 xform=None) -> None:
        super().__init__(mesh, xform)
        self.center = QVector3D(center)
        self.radius = float(radius)

    def apply(self) -> int:
        return add_detail(self.mesh, self.center, self.radius, self.xform)



class SetHeightCommand(_TerrainEdit):
    """Put a line's vertices at one world height — a flat contour lifted
    to its level — one undo step; ``result`` is how many moved."""

    def __init__(self, mesh, vertices, height: float, xform=None) -> None:
        super().__init__(mesh, xform)
        self.vertices = list(vertices)
        self.height = float(height)

    def apply(self) -> int:
        inv = None
        if self.xform is not None:
            inv, ok = self.xform.inverted()
            if not ok:
                return 0
        moved = 0
        for v in self.vertices:
            w = _world(self.xform, v.position)
            if abs(w.z() - self.height) < 1e-9:
                continue
            target = QVector3D(w.x(), w.y(), self.height)
            self.mesh.place_vertex(v, inv.map(target) if inv is not None
                                   else target)
            moved += 1
        return moved


class SetGuideHeightCommand(Command):
    """Put a guide point at a height, one undo step."""

    keeps_paint = True

    def __init__(self, guide, height: float) -> None:
        self.guide = guide
        self.height = float(height)
        self._old: Optional[float] = None

    def do(self, scene) -> None:
        p = self.guide.point
        if self._old is None:
            self._old = p.z()
        self.guide.point = QVector3D(p.x(), p.y(), self.height)
        scene.version += 1

    def undo(self, scene) -> None:
        if self._old is not None:
            p = self.guide.point
            self.guide.point = QVector3D(p.x(), p.y(), self._old)
            scene.version += 1
