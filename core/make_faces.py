# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Make Faces: the faces that the selected edges close, in place.

Lines that never got their faces — a plan imported from a drawing file,
an outline drawn with faces deleted — are turned into faces without
redrawing them. Only the selected edges count: the rest of the model is
left alone, so one strip of an imported plan can be faced next to an
existing 3D model.

* The faces are built on the selected edges themselves, in the current
  context (loose geometry or the group being edited): the lines become
  their edges, nothing is duplicated, and Push/Pull works on them at once.
* Edges at several heights are handled one plane per level (a plan with
  the floor at 0 and a sill at 0.90). Endpoints off the plane by less than
  :data:`PLANE_TOL` (the noise an import brings) are moved onto it.
* Crossing lines are split where they cross, as drawing them would.
* A new face looks up, or towards the camera if it is not horizontal —
  the rule for a face with no neighbour (``face_up_or_toward``).
* A loop that already has its face keeps it; a loose face wound the wrong
  way is turned over. A loop inside an existing face is not covered twice.

Headless: :func:`make_faces` does the work on a mesh; the menu command runs
it as one undo step. :func:`faces_from_linework` does it for a whole mesh
when a DXF/DWG is imported with that option on.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right

from PySide6.QtGui import QVector3D

from core.arrangement import coplanar_plane, planar_rebuild
from core.edits import face_up_or_toward
from core.mesh import Edge, turn_face_over

#: Edges this far off one plane still make a face with it (1 mm): the
#: noise of an imported plan must not stop the face.
PLANE_TOL = 1e-3
#: The mesh welds points closer than this (core/mesh.py, 4 decimals).
_WELD = 1e-4


class MakeFacesError(ValueError):
    """The selection makes no face; the message says why (English source
    text, translated by the caller)."""


def selected_edges(mesh, selection) -> list:
    """The selected edges that belong to ``mesh``, in a stable order."""
    live = set(map(id, mesh.edges))
    return [e for e in selection if isinstance(e, Edge) and id(e) in live]


def _plane_clusters(edges):
    """``[(edges, origin, normal), …]`` — the planes the edges lie on, or
    ``None`` when they are not on one plane nor on horizontal levels.

    * Everything at one height (±``PLANE_TOL``) → one horizontal plane.
    * Every edge horizontal but at SEVERAL heights → one plane per level.
    * Otherwise one vertical or sloped plane, or ``None``."""
    pts = [p for e in edges for p in (e.a, e.b)]
    zs = [p.z() for p in pts]
    if max(zs) - min(zs) <= PLANE_TOL:
        return [(list(edges), QVector3D(0, 0, _level(zs)),
                 QVector3D(0, 0, 1))]
    if all(abs(e.a.z() - e.b.z()) <= PLANE_TOL for e in edges):
        ordered = sorted(edges, key=lambda e: e.a.z() + e.b.z())
        clusters, cur, last = [], [], None
        for e in ordered:
            z = (e.a.z() + e.b.z()) / 2
            if last is not None and z - last > PLANE_TOL:
                clusters.append(cur)
                cur = []
            cur.append(e)
            last = z
        clusters.append(cur)
        out = []
        for cl in clusters:
            cz = [p.z() for e in cl for p in (e.a, e.b)]
            out.append((cl, QVector3D(0, 0, _level(cz)),
                        QVector3D(0, 0, 1)))
        return out
    plane = coplanar_plane(pts, tol=PLANE_TOL)
    if plane is None:
        return None
    return [(list(edges), plane[0], plane[1])]


def _level(zs) -> float:
    """The height of a level: the median of its points, so a clean plan
    keeps its exact height and only the stray points move onto it."""
    zs = sorted(zs)
    return zs[len(zs) // 2]


def _clusters_or_raise(edges):
    clusters = _plane_clusters(edges)
    if clusters is None:
        raise MakeFacesError(
            "The selected edges are not on one plane (nor on horizontal "
            "planes at different heights): Make Faces only builds flat "
            "faces.")
    return clusters


def _onto_plane(mesh, edges, origin, normal) -> None:
    """Move the endpoints of ``edges`` that are slightly off the plane onto
    it — only those no face uses, so no other face is bent."""
    for v in {id(v): v for e in edges for v in (e.v0, e.v1)}.values():
        d = QVector3D.dotProduct(v.position - origin, normal)
        if _WELD * 0.5 < abs(d) <= PLANE_TOL and not v.faces():
            mesh.place_vertex(v, v.position - normal * d)


class _Sorted:
    """The loop corners sorted along each axis: the ones inside an edge's
    box are found by bisecting along the axis where that box is thinnest
    (a line of a plan runs along one axis), not by walking them all — a
    big imported plan has thousands."""

    def __init__(self, points) -> None:
        pts = [(p.x(), p.y(), p.z(), p) for p in points]
        self._by = []
        for axis in range(3):
            ordered = sorted(pts, key=lambda t: t[axis])
            self._by.append(([t[axis] for t in ordered], ordered))

    def inside(self, lo, hi):
        axis = min(range(3), key=lambda i: hi[i] - lo[i])
        keys, ordered = self._by[axis]
        i = bisect_left(keys, lo[axis] - _WELD)
        j = bisect_right(keys, hi[axis] + _WELD)
        for t in ordered[i:j]:
            if all(lo[k] - _WELD <= t[k] <= hi[k] + _WELD for k in range(3)):
                yield t[3]


def _split_at(mesh, edges, points) -> None:
    """Split each edge at the loop corners that lie inside it (a crossing,
    a T): the faces then share the lines instead of laying a second,
    shorter edge over them."""
    index = _Sorted(points)
    work = list(edges)
    while work:
        e = work.pop()
        a, b = e.a, e.b
        ab = b - a
        l2 = QVector3D.dotProduct(ab, ab)
        if l2 < 1e-18:
            continue
        lo = (min(a.x(), b.x()), min(a.y(), b.y()), min(a.z(), b.z()))
        hi = (max(a.x(), b.x()), max(a.y(), b.y()), max(a.z(), b.z()))
        for p in index.inside(lo, hi):
            t = QVector3D.dotProduct(p - a, ab) / l2
            if t <= 0.0 or t >= 1.0:
                continue
            if (a + ab * t - p).length() > _WELD:
                continue
            if (p - a).length() <= _WELD or (p - b).length() <= _WELD:
                continue
            e0, e1 = mesh.split_edge(e, p)
            if e0 is not e:
                work.extend((e0, e1))
            break


def _cell(p) -> tuple:
    return (math.floor(p.x() / PLANE_TOL), math.floor(p.y() / PLANE_TOL),
            math.floor(p.z() / PLANE_TOL))


def _vertex_grid(vertices) -> dict:
    """The vertices filed by cells of ``PLANE_TOL``, for
    :func:`_snap_to_vertices`."""
    grid: dict = {}
    for v in vertices:
        grid.setdefault(_cell(v.position), []).append(v)
    return grid


def _snap_to_vertices(loop, grid):
    """Each corner of ``loop`` on the existing vertex it stands for (the
    arrangement hands back fresh, rounded points)."""
    out = []
    for p in loop:
        best, dist = None, PLANE_TOL
        cx, cy, cz = _cell(p)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for v in grid.get((cx + dx, cy + dy, cz + dz), ()):
                        d = (v.position - p).length()
                        if d <= dist:
                            best, dist = v, d
        out.append(QVector3D(best.position) if best is not None else p)
    return out


def _ring_key(points) -> frozenset:
    return frozenset((round(p.x(), 4), round(p.y(), 4), round(p.z(), 4))
                     for p in points)


def _probe(outer, holes, normal):
    """A point well inside the region (the centroid of its largest
    triangle), or ``None`` for a degenerate one."""
    from core.triangulate import triangulate
    tris = triangulate(outer, holes, normal)
    if not tris:
        return None
    big = max(tris, key=lambda t: QVector3D.crossProduct(
        t[1] - t[0], t[2] - t[0]).lengthSquared())
    return (big[0] + big[1] + big[2]) / 3.0


def _faces_on_plane(faces, origin, normal) -> list:
    """``[(face, lo, hi), …]``: the faces lying on the plane, with their
    boxes — read once per plane, not once per loop."""
    out = []
    for f in faces:
        if abs(QVector3D.dotProduct(f.normal(), normal)) < 0.999:
            continue
        if abs(QVector3D.dotProduct(f.loop[0].position - origin,
                                    normal)) > PLANE_TOL:
            continue
        xyz = [(p.x(), p.y(), p.z()) for p in f.vertices]
        out.append((f, tuple(min(c) for c in zip(*xyz)),
                    tuple(max(c) for c in zip(*xyz))))
    return out


def _covering_face(on_plane, probe):
    """A face of ``on_plane`` (see :func:`_faces_on_plane`) whose surface
    holds ``probe``."""
    from core.history import _point_in_tri
    q = (probe.x(), probe.y(), probe.z())
    for f, lo, hi in on_plane:
        if any(q[i] < lo[i] - PLANE_TOL or q[i] > hi[i] + PLANE_TOL
               for i in range(3)):
            continue
        if any(_point_in_tri(probe, *t) for t in f.triangulate()):
            return f
    return None


def _neighbours(mesh, face) -> bool:
    """Whether another face shares an edge with ``face``: then its winding
    agrees with that neighbour (a face of a solid) and is not turned."""
    for loop in (face.loop, *face.hole_loops):
        for a, b in zip(loop, loop[1:] + loop[:1]):
            e = mesh.find_edge(a, b)
            if e is not None and any(f is not face for f in e.faces):
                return True
    return False


def plan(edges):
    """``[(outer, holes), …]`` — the loops ``edges`` close,
    without touching the mesh. Raises :class:`MakeFacesError` with the
    reason when there is nothing to make."""
    if not edges:
        raise MakeFacesError(
            "Select the edges of the loops to turn into faces.")
    clusters = _clusters_or_raise(edges)
    found = []
    for cl_edges, origin, normal in clusters:
        segments = [(QVector3D(e.a), QVector3D(e.b)) for e in cl_edges]
        _, regions = planar_rebuild(segments, origin, normal)
        for outer, holes in regions:
            if len(outer) >= 3:
                found.append((outer, [h for h in holes if len(h) >= 3]))
    if not found:
        raise MakeFacesError(
            "The selected edges close no loop.")
    return found


def make_faces(mesh, edges, eye=None) -> dict:
    """Make the faces the ``edges`` close, in ``mesh``.

    Returns ``{"faces": [...], "new": n, "kept": n, "turned": n,
    "covered": n}``: every face of the result (new and kept, the ones to
    select), how many were made, how many loops already had their face,
    how many of those were turned over, and how many loops were left
    alone because an existing face already covers them."""
    out = _make_in(mesh, _clusters_or_raise(edges), eye)
    mesh.resplit_curves()
    return out


def faces_from_linework(mesh) -> int:
    """Make the faces of a whole drawing's loose lines, as an import does:
    returns how many. Unlike the command, nothing was chosen, so a mesh with
    lines off any one plane is not an error: horizontal lines go level by
    level (lines that cross without sharing a point still meet there), a
    connected drawing on a wall or a slope goes on its own plane, and the
    rest of a 3D wireframe stays as lines. Faces the file brought (a
    3DFACE) are left as they came."""
    loose = [e for e in mesh.edges if not e.faces]
    level, clusters = [], []
    for comp in _connected(loose):
        flat = [e for e in comp if abs(e.a.z() - e.b.z()) <= PLANE_TOL]
        if len(flat) == len(comp):
            level.extend(comp)
            continue
        plane = coplanar_plane([p for e in comp for p in (e.a, e.b)],
                               tol=PLANE_TOL)
        if plane is None:
            level.extend(flat)
        else:
            clusters.append((comp, plane[0], plane[1]))
    if level:
        clusters[:0] = _plane_clusters(level)
    made = _make_in(mesh, clusters, None)["new"]
    if clusters:
        mesh.resplit_curves()
    return made


def _connected(edges) -> list:
    """``edges`` split into the sets that touch through shared vertices."""
    by_vertex: dict = {}
    for e in edges:
        by_vertex.setdefault(id(e.v0), []).append(e)
        by_vertex.setdefault(id(e.v1), []).append(e)
    seen: set = set()
    out = []
    for start in edges:
        if id(start) in seen:
            continue
        seen.add(id(start))
        comp, work = [], [start]
        while work:
            e = work.pop()
            comp.append(e)
            for v in (e.v0, e.v1):
                for other in by_vertex[id(v)]:
                    if id(other) not in seen:
                        seen.add(id(other))
                        work.append(other)
        out.append(comp)
    return out


def _make_in(mesh, clusters, eye) -> dict:
    """The work of :func:`make_faces`, plane by plane; the caller re-splits
    the curves once, when every plane is done."""
    out = {"faces": [], "new": 0, "kept": 0, "turned": 0, "covered": 0}
    for cl_edges, origin, normal in clusters:
        _onto_plane(mesh, cl_edges, origin, normal)
        live = set(map(id, mesh.edges))
        cl_edges = [e for e in cl_edges if id(e) in live]
        segments = [(QVector3D(e.a), QVector3D(e.b)) for e in cl_edges]
        _, regions = planar_rebuild(segments, origin, normal)
        regions = [(o, [h for h in (hs or []) if len(h) >= 3])
                   for o, hs in regions if len(o) >= 3]
        if not regions:
            continue
        grid = _vertex_grid({id(v): v for e in cl_edges
                             for v in (e.v0, e.v1)}.values())
        regions = [(_snap_to_vertices(o, grid),
                    [_snap_to_vertices(h, grid) for h in hs])
                   for o, hs in regions]
        corners = list({_ring_key([p]): p for o, hs in regions
                        for ring in (o, *hs) for p in ring}.values())
        _split_at(mesh, cl_edges, corners)

        on_plane = _faces_on_plane(mesh.faces, origin, normal)
        by_ring = {}
        for f, _lo, _hi in on_plane:
            by_ring.setdefault(_ring_key(f.vertices), []).append(f)
        todo = []
        for outer, holes in regions:
            same = [f for f in by_ring.get(_ring_key(outer), ())
                    if _ring_key_holes(f) == _holes_key(holes)]
            if same:
                face = same[0]
                want = face_up_or_toward([QVector3D(p) for p in outer], eye)
                if (QVector3D.dotProduct(face.normal(), _normal_of(want)) < 0
                        and not _neighbours(mesh, face)):
                    turn_face_over(face)
                    out["turned"] += 1
                out["kept"] += 1
                out["faces"].append(face)
                continue
            probe = _probe(outer, holes, normal)
            if probe is None:
                continue
            if _covering_face(on_plane, probe) is not None:
                out["covered"] += 1
                continue
            todo.append((outer, holes))
        for outer, holes in todo:
            oriented = face_up_or_toward([QVector3D(p) for p in outer], eye)
            if list(oriented) != [QVector3D(p) for p in outer]:
                holes = [list(reversed(h)) for h in holes]
            face = mesh.add_face(oriented, holes or None)
            out["faces"].append(face)
            out["new"] += 1
    return out


def _normal_of(loop) -> QVector3D:
    nx = ny = nz = 0.0
    n = len(loop)
    for i in range(n):
        p, q = loop[i], loop[(i + 1) % n]
        nx += (p.y() - q.y()) * (p.z() + q.z())
        ny += (p.z() - q.z()) * (p.x() + q.x())
        nz += (p.x() - q.x()) * (p.y() + q.y())
    return QVector3D(nx, ny, nz)


def _holes_key(holes) -> frozenset:
    return frozenset(_ring_key(h) for h in holes or ())


def _ring_key_holes(face) -> frozenset:
    return _holes_key(face.holes)
