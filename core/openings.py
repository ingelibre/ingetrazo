# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Components that cut an opening in the face they sit on (#1272).

A window or a door marked «Cut opening» opens its own hole in the wall it is
placed on, and the hole follows it: move, rotate or scale the component and
the old hole closes while the new one opens; erase it and the wall closes.

**What cuts.** The component's *footprint*: the outline of its largest face
lying on its own base plane (local ``z = 0``, the blue axis coming out of the
wall), or, with no face there, the rectangle the component covers on that
plane. Placed on a face of the context it lives in (the loose geometry, or
the group open for editing), the footprint cuts that face — and when a face
parallel to it stands behind, within :data:`MAX_THICKNESS`, the cut goes
THROUGH the wall: both sides open and the reveals (jambs, head, sill) are
built. A door standing on the wall's foot opens the wall's bottom face too.

**The prism.** Both operations work on the same solid: the footprint pushed
back through the wall. Each of its faces is one planar polygon:

- cutting, a polygon that lies on an existing face is drawn on it and the
  piece inside taken away (the caps, a door's sill on the wall's foot); one
  that lies on nothing is added, facing into the hole (the reveals);
- healing is the mirror: a polygon filled by a reveal loses it; one that is
  empty gets its face back, facing out, and merges with its coplanar
  neighbours, so the wall reads as it did before.

**Following.** :func:`records` lists, before a command runs, what every
cutting component of the context has cut; :func:`follow`, after it,
compares and brings the holes up to date, as a command of its own that the
history folds into the same undo step. So every tool — Move, Rotate, Scale,
Erase, Paste, an extension — gets it without knowing about openings.

The state lives in the container's ``ext`` (saved in the .igz, copied with
copies): ``{"on": True}`` asks for an opening, and ``"made"`` records the
one cut — by this very container (``uid``), from where (``xf``), and the
prism (``a``, ``b``). A copy carries its original's record with the other
uid, so it is read as not cut yet.
"""
from __future__ import annotations

import copy
from typing import Optional

from PySide6.QtGui import QVector3D

from core.history import Command

#: The ``ext`` key of an opening.
EXT_KEY = "opening"
#: The thickest wall a cut goes through: a face parallel to the footprint
#: further behind than this is another wall, not this one's other side.
MAX_THICKNESS = 1.0
#: Distance below which a point lies on a plane (metres).
_PLANE_EPS = 1e-4
#: Two normals this aligned are parallel.
_PARALLEL = 0.999


# ---- The mark ----------------------------------------------------------------
def wants_opening(group) -> bool:
    """Whether ``group`` is marked «Cut opening»."""
    ext = getattr(group, "ext", None)
    return bool(isinstance(ext, dict) and isinstance(ext.get(EXT_KEY), dict)
                and ext[EXT_KEY].get("on"))


def _entry(group) -> dict:
    ext = getattr(group, "ext", None)
    entry = ext.get(EXT_KEY) if isinstance(ext, dict) else None
    return entry if isinstance(entry, dict) else {}


def made(group) -> Optional[dict]:
    """The opening ``group`` itself cut, or None — a copy's inherited record
    belongs to its original and does not count."""
    rec = _entry(group).get("made")
    if not isinstance(rec, dict) or rec.get("uid") != getattr(group, "uid", None):
        return None
    return rec


def set_ext_entry(group, entry: Optional[dict]) -> None:
    """Write (or with None, drop) the opening entry of ``group``'s ``ext``."""
    ext = dict(group.ext) if isinstance(getattr(group, "ext", None), dict) else {}
    if entry:
        ext[EXT_KEY] = entry
    else:
        ext.pop(EXT_KEY, None)
    group.ext = ext or None


def siblings(scene, group) -> list:
    """``group`` and the other copies of the same component in the context —
    the mark belongs to the component, as its definition does."""
    out = [group]
    if getattr(group, "is_component", lambda: False)():
        out += [g for g in context_groups(scene)
                if g is not group and getattr(g, "mesh", None) is group.mesh
                and g.is_component()]
    return out


# ---- Plane geometry ----------------------------------------------------------
def _basis(n: QVector3D):
    """Two unit vectors square to ``n`` and to each other."""
    ref = QVector3D(0, 0, 1) if abs(n.z()) < 0.9 else QVector3D(1, 0, 0)
    u = QVector3D.crossProduct(ref, n).normalized()
    v = QVector3D.crossProduct(n, u).normalized()
    return u, v


def _to2d(points, origin, u, v):
    return [(QVector3D.dotProduct(p - origin, u),
             QVector3D.dotProduct(p - origin, v)) for p in points]


def _inside(pt, poly) -> bool:
    """Even-odd point-in-polygon, in 2D."""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xc = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xc > x:
                inside = not inside
    return inside


def _area2d(poly) -> float:
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
                     - poly[(i + 1) % len(poly)][0] * poly[i][1]
                     for i in range(len(poly)))


def _normal(points) -> QVector3D:
    """Newell normal of a planar loop."""
    nx = ny = nz = 0.0
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        nx += (a.y() - b.y()) * (a.z() + b.z())
        ny += (a.z() - b.z()) * (a.x() + b.x())
        nz += (a.x() - b.x()) * (a.y() + b.y())
    v = QVector3D(nx, ny, nz)
    return v.normalized() if v.length() > 1e-12 else QVector3D(0, 0, 0)


def _centroid(points) -> QVector3D:
    c = QVector3D(0, 0, 0)
    for p in points:
        c += p
    return c / max(1, len(points))


def _interior_point(points) -> QVector3D:
    """A point surely inside a planar polygon (its centroid, nudged off a
    concave notch toward the first corner's inside)."""
    c = _centroid(points)
    n = _normal(points)
    u, v = _basis(n)
    poly = _to2d(points, points[0], u, v)
    if _inside(_to2d([c], points[0], u, v)[0], poly):
        return c
    for i in range(len(points)):
        a, b, d = points[i - 1], points[i], points[(i + 1) % len(points)]
        cand = (a + b + d) / 3.0
        if _inside(_to2d([cand], points[0], u, v)[0], poly):
            return cand
    return c


def _face_holds(face, point: QVector3D, n: QVector3D) -> bool:
    """Whether ``point``, on ``face``'s plane, lies inside it and not in one
    of its holes."""
    loop = face.vertices
    if len(loop) < 3:
        return False
    u, v = _basis(n)
    p2 = _to2d([point], loop[0], u, v)[0]
    if not _inside(p2, _to2d(loop, loop[0], u, v)):
        return False
    return not any(_inside(p2, _to2d(h, loop[0], u, v)) for h in face.holes)


def _covers(face, points) -> bool:
    """Whether the polygon ``points``, on ``face``'s plane, lies within it:
    every corner inside or on its outline, none inside one of its holes —
    an opening that ran off the wall, or into another opening, would cut
    what is not there."""
    loop = face.vertices
    n = face.normal()
    u, v = _basis(n)
    outer = _to2d(loop, loop[0], u, v)
    holes = [_to2d(h, loop[0], u, v) for h in face.holes]
    scale = max(max(abs(x) for x, _ in outer), max(abs(y) for _, y in outer), 1.0)
    eps = 1e-6 * scale
    for c in _to2d(points, loop[0], u, v):
        if not (_inside(c, outer) or _on_boundary(c, outer, eps)):
            return False
        if any(_inside(c, h) and not _on_boundary(c, h, eps) for h in holes):
            return False
    return True


def _coplanar_faces(mesh, points):
    """The faces of ``mesh`` in the plane of the loop ``points``."""
    n = _normal(points)
    if n.length() < 0.5:
        return []
    nx, ny, nz = n.x(), n.y(), n.z()
    d0 = nx * points[0].x() + ny * points[0].y() + nz * points[0].z()
    out = []
    for f in mesh.faces:
        # Off the plane is the common case: three corners say so before
        # any normal is worked out (a model of a million faces).
        off = False
        for v in f.loop[:3]:
            x, y, z = v.position.toTuple()
            if abs(nx * x + ny * y + nz * z - d0) > _PLANE_EPS:
                off = True
                break
        if off:
            continue
        if abs(QVector3D.dotProduct(f.normal(), n)) < _PARALLEL:
            continue
        out.append(f)
    return out


def _host_face(mesh, points):
    """The face the polygon ``points`` lies on, or None."""
    n = _normal(points)
    probe = _interior_point(points)
    for f in _coplanar_faces(mesh, points):
        if _face_holds(f, probe, n):
            return f
    return None


def _faces_within(mesh, points):
    """The coplanar faces lying inside the polygon ``points`` (every corner
    inside or on it, the inside of the face inside it too)."""
    n = _normal(points)
    u, v = _basis(n)
    poly = _to2d(points, points[0], u, v)
    scale = max(max(abs(x) for x, _ in poly), max(abs(y) for _, y in poly), 1.0)
    eps = 1e-6 * scale
    out = []
    for f in _coplanar_faces(mesh, points):
        corners = _to2d(f.vertices, points[0], u, v)
        if not _inside(_to2d([_interior_point(f.vertices)], points[0], u, v)[0],
                       poly):
            continue
        if all(_inside(c, poly) or _on_boundary(c, poly, eps) for c in corners):
            out.append(f)
    return out


def _on_boundary(pt, poly, eps) -> bool:
    x, y = pt
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        ll = dx * dx + dy * dy
        if ll < 1e-24:
            continue
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / ll))
        if (x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2 <= eps * eps:
            return True
    return False


# ---- The footprint -----------------------------------------------------------
def _frame(group):
    from PySide6.QtGui import QMatrix4x4

    from core.group import group_frame
    f = group_frame(group)
    return QMatrix4x4(f) if f is not None else QMatrix4x4()


def footprint(group) -> Optional[list]:
    """The opening's outline in world coordinates, counter-clockwise seen
    from the blue axis, or None when the component has nothing to cut with.

    The outer loop of the largest face lying on the component's base plane;
    with none there, the rectangle it covers on that plane."""
    from core.group import iter_placements
    frame = _frame(group)
    inv, ok = frame.inverted()
    if not ok:
        return None
    best, best_area = None, 0.0
    lo = [float("inf")] * 2
    hi = [float("-inf")] * 2
    for g, m in iter_placements(group):
        for f in g.mesh.faces:
            loop = [m.map(p) if m is not None else QVector3D(p) for p in f.vertices]
            local = [inv.map(p) for p in loop]
            for p in local:
                lo[0], lo[1] = min(lo[0], p.x()), min(lo[1], p.y())
                hi[0], hi[1] = max(hi[0], p.x()), max(hi[1], p.y())
            if all(abs(p.z()) < _PLANE_EPS for p in local) and len(local) >= 3:
                area = abs(_area2d([(p.x(), p.y()) for p in local]))
                if area > best_area:
                    best, best_area = local, area
        for e in g.mesh.edges:
            for p in (e.a, e.b):
                q = inv.map(m.map(p) if m is not None else QVector3D(p))
                lo[0], lo[1] = min(lo[0], q.x()), min(lo[1], q.y())
                hi[0], hi[1] = max(hi[0], q.x()), max(hi[1], q.y())
    if best is None:
        if not (hi[0] - lo[0] > 1e-4 and hi[1] - lo[1] > 1e-4):
            return None
        best = [QVector3D(lo[0], lo[1], 0), QVector3D(hi[0], lo[1], 0),
                QVector3D(hi[0], hi[1], 0), QVector3D(lo[0], hi[1], 0)]
    flat = [QVector3D(p.x(), p.y(), 0.0) for p in best]
    if _area2d([(p.x(), p.y()) for p in flat]) < 0:
        flat.reverse()
    return [frame.map(p) for p in flat]


# ---- Where it cuts -----------------------------------------------------------
def plan_in(mesh, a) -> Optional[dict]:
    """The prism the footprint ``a`` (in ``mesh``'s own coordinates) would
    cut in ``mesh``: ``{"a": front loop, "b": back loop or None}``, or None
    when it lies on no face of it."""
    host = _host_face(mesh, a)
    if host is None or not _covers(host, a):
        return None
    n = _normal(a)
    probe = _interior_point(a)
    best = None
    for f in mesh.faces:
        # The distance first: it is cheap, and rules out nearly every face.
        d = QVector3D.dotProduct(probe - f.loop[0].position, n)
        if not (_PLANE_EPS < d <= MAX_THICKNESS):
            continue
        if abs(QVector3D.dotProduct(f.normal(), n)) < _PARALLEL:
            continue
        if best is not None and d >= best[0]:
            continue
        if _face_holds(f, probe - n * d, n) and _covers(f, [p - n * d for p in a]):
            best = (d, f)
    b = [p - n * best[0] for p in a] if best is not None else None
    return {"a": a, "b": b}


def plan(mesh, group) -> Optional[dict]:
    """The prism ``group`` would cut in ``mesh`` (in world coordinates)
    where it stands now, or None."""
    a = footprint(group)
    return plan_in(mesh, a) if a is not None else None


def _polygons(prism) -> list:
    """The planar faces of the prism: caps first, then the sides."""
    a, b = prism["a"], prism.get("b")
    polys = [list(a)]
    if b:
        polys.append(list(b))
        n = len(a)
        polys += [[a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]] for i in range(n)]
    return polys


def _prism_centre(prism) -> QVector3D:
    a, b = prism["a"], prism.get("b")
    if b:
        return (_centroid(a) + _centroid(b)) / 2.0
    return _centroid(a) - _normal(a) * 0.01


def _orient(mesh, face, centre: QVector3D, inward: bool) -> None:
    """Turn ``face`` to look toward the prism's centre (``inward``) or
    away from it."""
    looks_in = QVector3D.dotProduct(face.normal(), centre - face.centroid()) > 0
    if looks_in != inward:
        face.loop.reverse()
        for h in face.hole_loops:
            h.reverse()
        mesh._chunk_dirty = True
        mesh._mut_serial += 1


def _segments(points):
    n = len(points)
    return [(QVector3D(points[i]), QVector3D(points[(i + 1) % n]))
            for i in range(n)]


def _draw_on(scene, points) -> None:
    """Draw the polygon's outline into the mesh, splitting the faces it
    crosses — the Line tool's own plan. A side already drawn is left out:
    drawn again, it closes cycles of its own on the OTHER planes it lies in
    (a door's sill runs along the front's foot, and faced the whole front
    once more)."""
    from core.edits import build_add_edges
    mesh = scene.mesh
    new = []
    for a, b in _segments(points):
        va, vb = mesh.vertex_at(a), mesh.vertex_at(b)
        if va is not None and vb is not None and mesh.find_edge(va, vb):
            continue
        new.append((a, b))
    if new:
        build_add_edges(scene, new, detect_faces=True).do(scene)


def _add_face(scene, points, paint: Optional[dict]):
    from core.edits import build_add_edges
    from core.history import AddFaceCommand
    face_cmd = AddFaceCommand([QVector3D(p) for p in points], auto=False)
    build_add_edges(scene, _segments(points), detect_faces=False,
                    extra=[face_cmd]).do(scene)
    face = getattr(face_cmd, "face", None)
    if face is None:
        face = _exact_face(scene.mesh, points)
    if face is not None and paint:
        face.attrs = dict(paint)
    return face


def _exact_face(mesh, points):
    keys = {_k(p) for p in points}
    for f in _coplanar_faces(mesh, points):
        if {_k(p) for p in f.vertices} == keys and not f.hole_loops:
            return f
    return None


def _k(p: QVector3D):
    return (round(p.x(), 5), round(p.y(), 5), round(p.z(), 5))


def _paint_of(face) -> Optional[dict]:
    from core.mesh import PAINT_KEYS
    attrs = getattr(face, "attrs", None) or {}
    paint = {k: attrs[k] for k in PAINT_KEYS if k in attrs}
    return paint or None


def _floor_like(mesh, face, prism) -> bool:
    """Whether a face a side of the prism lies on goes on beyond the wall —
    a floor the wall stands on, not the wall's own foot. The floor stays
    under a door; only the wall's own foot is opened."""
    a, b = prism["a"], prism.get("b")
    if not b:
        return True
    n = _normal(a)
    a0 = a[0]
    d = QVector3D.dotProduct(a0 - b[0], n)
    for v in face.loop:
        s = QVector3D.dotProduct(v.position - a0, n)
        if s > _PLANE_EPS or s < -d - _PLANE_EPS:
            return True
    fn = face.normal()
    p0 = face.loop[0].position
    for lp in (face.loop, *face.hole_loops):
        m = len(lp)
        for i in range(m):
            e = mesh.find_edge(lp[i], lp[(i + 1) % m])
            for g in (e.faces if e is not None else ()):
                if g is face:
                    continue
                if (abs(QVector3D.dotProduct(g.normal(), fn)) >= _PARALLEL
                        and abs(QVector3D.dotProduct(
                            g.loop[0].position - p0, fn)) <= _PLANE_EPS):
                    return True
    return False


def _kept(prism) -> set:
    return set(prism.get("keep") or ())


def cut(scene, prism) -> None:
    """Open ``prism`` in ``scene.mesh``. The sides lying on a floor that
    goes on beyond the wall are left alone, and listed in ``prism["keep"]``
    so the hole heals the same way."""
    mesh = scene.mesh
    centre = _prism_centre(prism)
    host = _host_face(mesh, prism["a"])
    paint = _paint_of(host) if host is not None else None
    polys = _polygons(prism)
    on_faces, keep = [], []
    for i, poly in enumerate(polys):
        under = _host_face(mesh, poly)
        if under is None:
            continue
        if i >= 2 and _floor_like(mesh, under, prism):
            keep.append(i)
        else:
            on_faces.append(i)
    prism["keep"] = keep
    # Every outline is drawn BEFORE any piece is taken away: drawing on a
    # plane rebuilds the planes its edges touch, and a door's sill drawn on
    # the wall's foot would face the front's emptied cap all over again.
    for i in on_faces:
        _draw_on(scene, polys[i])
    for i in on_faces:
        for f in _faces_within(mesh, polys[i]):
            mesh.remove_face(f)
    for i, poly in enumerate(polys):
        if i in on_faces or i in keep:
            continue
        face = _add_face(scene, poly, paint)
        if face is not None:
            _orient(mesh, face, centre, inward=True)
    _drop_loose(mesh, prism)
    scene.version += 1


def intact(mesh, prism) -> bool:
    """Whether the hole ``prism`` cut is still as it was made: every reveal
    in place and nothing drawn across the openings."""
    keep = _kept(prism)
    for i, poly in enumerate(_polygons(prism)):
        if i in keep:
            continue
        if i < 2:
            if _faces_within(mesh, poly):
                return False            # a cap was filled or drawn over
        elif _host_face(mesh, poly) is None and not _faces_within(mesh, poly):
            # A side holds a reveal, or the face of the wall it opened (a
            # door's sill on the wall's foot leaves no face): one of the two.
            if _side_was_open(mesh, poly):
                continue
            return False
    return True


def _side_was_open(mesh, poly) -> bool:
    """A side of the prism lying in the plane of an existing face whose
    region it opened (the sill of a door on a wall's foot): its plane holds
    a face touching it, but none inside it."""
    for f in _coplanar_faces(mesh, poly):
        keys = {_k(p) for p in f.vertices}
        if any(_k(p) in keys for p in poly):
            return True
    return False


def heal(scene, prism) -> bool:
    """Close the hole ``prism`` cut, as if it had never been there. False,
    and nothing touched, when the hole was edited since."""
    mesh = scene.mesh
    if not intact(mesh, prism):
        return False
    centre = _prism_centre(prism)
    added = []
    paint = None
    for f in mesh.faces:
        if _face_borders(f, prism["a"]):
            paint = _paint_of(f)
            break
    keep = _kept(prism)
    for i, poly in enumerate(_polygons(prism)):
        if i in keep:
            continue
        inner = _faces_within(mesh, poly)
        if inner:
            for f in inner:
                mesh.remove_face(f)
            continue
        face = _add_face(scene, poly, paint)
        if face is not None:
            _orient(mesh, face, centre, inward=False)
            added.append(face)
    for face in added:
        _merge_into_neighbours(mesh, face)
    _drop_loose(mesh, prism)
    _collapse_corners(mesh, prism)
    scene.version += 1
    return True


def _collapse_corners(mesh, prism) -> None:
    """The prism's corners left in the middle of a straight edge once the
    wall is whole again (a door's foot splits the wall's bottom edge)."""
    for loop in (prism["a"], prism.get("b") or ()):
        for p in loop:
            v = mesh.vertex_at(p)
            if v is not None and mesh.collapsible_vertex(v):
                mesh.collapse_vertex(v)


def _face_borders(face, points) -> bool:
    keys = {_k(p) for p in points}
    return any(_k(v.position) in keys
               for lp in (face.loop, *face.hole_loops) for v in lp)


def _merge_into_neighbours(mesh, face) -> None:
    """Melt a healed face into the coplanar faces around it."""
    if face not in mesh.faces:
        return
    n = face.normal()
    region = {face}
    stack = [face]
    while stack:
        f = stack.pop()
        for lp in (f.loop, *f.hole_loops):
            m = len(lp)
            for i in range(m):
                e = mesh.find_edge(lp[i], lp[(i + 1) % m])
                if e is None:
                    continue
                for g in e.faces:
                    if g in region:
                        continue
                    if QVector3D.dotProduct(g.normal(), n) < _PARALLEL:
                        continue
                    if abs(QVector3D.dotProduct(g.loop[0].position
                                                - face.loop[0].position, n)) \
                            > _PLANE_EPS:
                        continue
                    region.add(g)
                    stack.append(g)
    if len(region) > 1:
        mesh.dissolve_coplanar_region(region)


def _drop_loose(mesh, prism) -> None:
    """Edges of the prism no face uses any more, and their vertices."""
    keys = {_k(p) for loop in (prism["a"], prism.get("b") or ()) for p in loop}
    loose = [e for e in mesh.edges if not e.faces
             and (_k(e.v0.position) in keys or _k(e.v1.position) in keys)]
    for e in loose:
        mesh.remove_edge(e)
    if loose:
        mesh.prune_orphan_vertices()


# ---- Hosts: where a hole is cut ---------------------------------------------
# The wall may be loose geometry, or a group of its own — the usual way to
# keep a wall — and the window or door a component beside it. A HOST is
# where a hole goes: the context's loose mesh (``group`` None), or one of
# the context's containers. Its hole is remembered in the host's own frame,
# so moving the wall and the window together moves the hole with them.
class _Host:
    def __init__(self, scene, group) -> None:
        from PySide6.QtGui import QMatrix4x4
        self.group = group
        self.uid = getattr(group, "uid", None)
        if group is None:
            self.mesh = scene.mesh
            self.frame = QMatrix4x4()
            self.to_world = QMatrix4x4()
        else:
            self.mesh = group.mesh
            self.frame = _frame(group)
            self.to_world = (QMatrix4x4(group.xform)
                             if getattr(group, "xform", None) is not None
                             else QMatrix4x4())
        inv, ok = self.to_world.inverted()
        self.to_mesh = inv if ok else QMatrix4x4()
        finv, ok = self.frame.inverted()
        self.from_world = finv if ok else QMatrix4x4()

    def mesh_points(self, world_points) -> list:
        """World points in the host mesh's own coordinates."""
        return [self.to_mesh.map(p) for p in world_points]

    def local_to_mesh(self, local_points) -> list:
        """Points in the host's frame, in its mesh's coordinates."""
        m = self.to_mesh * self.frame
        return [m.map(p) for p in local_points]

    def mesh_to_local(self, mesh_points) -> list:
        """Points of the host mesh, in the host's frame."""
        m = self.from_world * self.to_world
        return [m.map(p) for p in mesh_points]

    def frame_list(self) -> list:
        return [round(x, 7) for x in self.frame.data()]


def _can_host(group) -> bool:
    """A container whose own faces may take a hole: not a window or a door
    itself, not a face-me cutout, not hidden or locked, not 3D text."""
    return not (wants_opening(group) or getattr(group, "billboard", False)
                or getattr(group, "hidden", False)
                or getattr(group, "locked", False)
                or getattr(group, "text3d", None) is not None
                or not group.mesh.faces)


def _bbox(mesh):
    """``(lo, hi)`` of ``mesh``'s vertices, cached on its edit serial."""
    key = getattr(mesh, "_mut_serial", None)
    cached = getattr(mesh, "_opening_bbox", None)
    if cached is not None and key is not None and cached[0] == key:
        return cached[1]
    xs, ys, zs = [], [], []
    for v in mesh.vertices:
        x, y, z = v.position.toTuple()
        xs.append(x)
        ys.append(y)
        zs.append(z)
    box = (((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
           if xs else None)
    try:
        mesh._opening_bbox = (key, box)
    except AttributeError:
        pass
    return box


def _near(box, points, pad) -> bool:
    """Whether every point lies within ``box`` (grown by ``pad``)."""
    if box is None:
        return False
    lo, hi = box
    for p in points:
        for i, c in enumerate(p.toTuple()):
            if c < lo[i] - pad or c > hi[i] + pad:
                return False
    return True


def find_host(scene, group):
    """``(host, prism in the host mesh's coordinates)`` for what ``group``
    would cut where it stands: the loose geometry first, then the other
    containers of the context. ``(None, None)`` when it sits on no face."""
    a = footprint(group)
    if a is None:
        return None, None
    loose = _Host(scene, None)
    prism = plan_in(loose.mesh, a)
    if prism is not None:
        return loose, prism
    for g in context_groups(scene):
        if g is group or not _can_host(g):
            continue
        host = _Host(scene, g)
        pts = host.mesh_points(a)
        if not _near(_bbox(host.mesh), pts, pad=10 * _PLANE_EPS):
            continue
        prism = plan_in(host.mesh, pts)
        if prism is not None:
            return host, prism
    return None, None


def _host_of(scene, rec) -> Optional[_Host]:
    """The host a record cut in, as it is now — None when it is gone."""
    uid = rec.get("host")
    if uid is None:
        return _Host(scene, None)
    for g in context_groups(scene):
        if getattr(g, "uid", None) == uid:
            return _Host(scene, g)
    return None


class _Edits:
    """What a follow-up changed, to undo and redo it exactly: each mesh it
    touched (its state before, captured on first touch, and after), and
    each container made unique on the way (a copied wall group shares its
    mesh with the original until it is edited)."""

    def __init__(self) -> None:
        self.meshes: list = []          # [mesh, before, after]
        self._seen: set = set()
        self.groups: list = []          # [group, before, after]

    def touch(self, mesh) -> None:
        if id(mesh) not in self._seen:
            self._seen.add(id(mesh))
            self.meshes.append([mesh, mesh.capture_state(), None])

    def seal(self) -> None:
        for row in self.meshes:
            row[2] = row[0].capture_state()
        for row in self.groups:
            row[2] = _group_state(row[0])

    def any(self) -> bool:
        return bool(self.meshes or self.groups)


def _group_state(g):
    from PySide6.QtGui import QMatrix4x4
    return (g.mesh, QMatrix4x4(g.xform) if g.xform is not None else None,
            QMatrix4x4(g.axes) if g.axes is not None else None,
            list(g.children or ()), g.component)


def _put_group_state(g, st) -> None:
    from PySide6.QtGui import QMatrix4x4
    g.mesh = st[0]
    g.xform = QMatrix4x4(st[1]) if st[1] is not None else None
    g.axes = QMatrix4x4(st[2]) if st[2] is not None else None
    g.children = list(st[3])
    g.component = st[4]


def _shared(scene, host) -> int:
    """How many other containers of the model use ``host``'s mesh."""
    if host.group is None:
        return 0
    from core.purge import iter_groups
    return sum(1 for g in iter_groups(getattr(scene, "groups", None))
               if g is not host.group and g.mesh is host.mesh)


def _ready(scene, host, edits: _Edits, refused: list) -> Optional[_Host]:
    """The host, ready to be cut: a copied group sharing its mesh is made
    unique first (as opening it would); a component with other copies is
    refused — cutting it would cut every copy."""
    if host.group is not None and _shared(scene, host):
        if host.group.is_component():
            refused.append(host.group.name)
            return None
        edits.groups.append([host.group, _group_state(host.group), None])
        host.group.make_unique()
        host = _Host(scene, host.group)
    edits.touch(host.mesh)
    return host


def _in_mesh(scene, mesh, fn):
    """Run ``fn`` with the scene's working mesh pointing at ``mesh`` — the
    drawing plan (``build_add_edges``) edits ``scene.mesh``."""
    current = scene.mesh
    scene.mesh = mesh
    try:
        return fn()
    finally:
        scene.mesh = current


def _prism_from(host, rec) -> dict:
    return {"a": host.local_to_mesh([QVector3D(*p) for p in rec["a"]]),
            "b": (host.local_to_mesh([QVector3D(*p) for p in rec["b"]])
                  if rec.get("b") else None),
            "keep": list(rec.get("keep") or ())}


def _cut_at(scene, host, prism, edits, refused):
    """Cut ``prism`` (in the host mesh's coordinates) — the host made
    unique first when it must be. The host it was cut in, or None."""
    host2 = _ready(scene, host, edits, refused)
    if host2 is None:
        return None
    if host2.mesh is not host.mesh:                    # made unique
        prism = {"a": host2.mesh_points([host.to_world.map(p)
                                         for p in prism["a"]]),
                 "b": (host2.mesh_points([host.to_world.map(p)
                                          for p in prism["b"]])
                       if prism.get("b") else None)}
    _in_mesh(scene, host2.mesh, lambda: cut(scene, prism))
    return host2, prism


def _heal_at(scene, rec, edits, refused) -> bool:
    """Close what ``rec`` cut. True when there is nothing left to close (or
    its wall is gone); False when the hole was edited by hand."""
    if not rec.get("a"):
        return True
    host = _host_of(scene, rec)
    if host is None:
        return True                       # the wall itself was erased
    if not intact(host.mesh, _prism_from(host, rec)):
        return False
    host = _ready(scene, host, edits, refused)
    if host is None:
        return False
    prism = _prism_from(host, rec)
    return bool(_in_mesh(scene, host.mesh, lambda: heal(scene, prism)))


# ---- Following the components ------------------------------------------------
def context_groups(scene) -> list:
    """The containers that live where the tools draw now: the open group's
    children, or the model's top level."""
    edit = getattr(scene, "edit_group", None)
    if edit is not None:
        return getattr(edit, "children", None) or ()
    return getattr(scene, "groups", None) or ()


def _frame_list(group) -> list:
    f = _frame(group)
    return [round(x, 7) for x in f.data()]


def _marked(scene) -> list:
    """The containers of the context whose ``ext`` holds an opening entry —
    one quick pass: on a model of 21 000 groups, nearly all with no
    ``ext`` at all, every command pays only this."""
    key = EXT_KEY
    return [g for g in context_groups(scene)
            if g.ext and key in g.ext]


def records(scene) -> dict:
    """``{uid: (group, made)}`` of every container of the context that has
    cut an opening — what :func:`follow` compares against."""
    out = {}
    for g in _marked(scene):
        rec = made(g)
        if rec is not None:
            out[g.uid] = (g, rec)
    return out


def _record(group, host, prism) -> dict:
    """What ``group`` cut where it stands, in ``host``'s own frame — or,
    with ``prism`` None, that it stood on no face, so the next command does
    not look again until it moves."""
    rec = {"uid": group.uid, "xf": _frame_list(group), "a": None, "b": None,
           "host": None, "hxf": None}
    if prism is not None:
        rec["host"] = host.uid
        rec["hxf"] = host.frame_list()
        rec["a"] = [list(p.toTuple()) for p in host.mesh_to_local(prism["a"])]
        rec["b"] = ([list(p.toTuple())
                     for p in host.mesh_to_local(prism["b"])]
                    if prism.get("b") else None)
        if prism.get("keep"):
            rec["keep"] = list(prism["keep"])
    return rec


def _stale(scene, g, rec, by_uid) -> bool:
    """Whether ``g``'s record no longer matches: the component moved, or
    the wall it cut moved or went."""
    if rec.get("xf") != _frame_list(g):
        return True
    uid = rec.get("host")
    if rec.get("a") and uid is not None:
        host = by_uid.get(uid)
        if host is None or rec.get("hxf") != _Host(scene, host).frame_list():
            return True
    return False


def pending(scene, before: dict) -> bool:
    """Whether anything is out of date after a command, given the records
    taken before it: a cutting container added, moved, unmarked or gone,
    or the wall it cut moved or erased."""
    now = {g.uid: g for g in _marked(scene)}
    if any(uid not in now for uid in before):
        return True
    by_uid = None
    for g in now.values():
        rec, want = made(g), wants_opening(g)
        if want and rec is None:
            return True
        if rec is None:
            continue
        if not want:
            return True
        if rec.get("host") is not None and by_uid is None:
            by_uid = {getattr(x, "uid", None): x
                      for x in context_groups(scene)}
        if _stale(scene, g, rec, by_uid or {}):
            return True
    return False


def bring_up_to_date(scene, before: dict, edits: _Edits) -> tuple:
    """Heal what moved or went, cut what is new or moved. Returns the names
    of the containers whose old hole had been edited by hand and was left
    as it is, and of the shared components that could not be cut."""
    edited, refused = [], []
    now = {g.uid: g for g in _marked(scene)}
    by_uid = {getattr(x, "uid", None): x for x in context_groups(scene)}
    for uid, (g, rec) in before.items():
        if uid not in now and not _heal_at(scene, rec, edits, refused):
            edited.append(g.name)
    for g in now.values():
        rec, want = made(g), wants_opening(g)
        if rec is None and not want:
            continue
        if rec is not None and want and not _stale(scene, g, rec, by_uid):
            continue
        entry = dict(_entry(g))
        entry.pop("made", None)
        if rec is not None and not _heal_at(scene, rec, edits, refused):
            edited.append(g.name)
        if want:
            host, prism = find_host(scene, g)
            if host is not None:
                done = _cut_at(scene, host, prism, edits, refused)
                host, prism = done if done is not None else (None, None)
            entry["made"] = _record(g, host, prism)
        set_ext_entry(g, entry)
    return edited, refused


def _copy_ext(group):
    ext = getattr(group, "ext", None)
    return copy.deepcopy(ext) if ext else None


def _concerned(scene, before: dict) -> dict:
    """``{uid: group}``: the containers of the context that ask for an
    opening or hold a record, and the ones that held one before."""
    out = {g.uid: g for g in _marked(scene)}
    for uid, (g, _r) in before.items():
        out.setdefault(uid, g)
    return out


class FollowOpeningsCommand(Command):
    """The holes brought up to date after a command — already applied when
    built, undone by restoring every mesh it touched, the containers it
    made unique and the containers' ``ext``."""

    keeps_paint = True
    keeps_groups = True

    def __init__(self, edits: _Edits, ext_before, ext_after, edited,
                 refused=()) -> None:
        self._edits = edits
        self._ext_before, self._ext_after = ext_before, ext_after
        self.edited = edited
        self.refused = list(refused)

    def _settle(self, scene) -> None:
        scene.version += 1
        if self._edits.groups or any(
                m is not scene.mesh for m, _b, _a in self._edits.meshes):
            from core.history import _dirty_group_chunks
            _dirty_group_chunks(scene)

    def do(self, scene) -> None:
        for g, _b, after in self._edits.groups:
            _put_group_state(g, after)
        for mesh, _b, after in self._edits.meshes:
            mesh.restore_state(after)
        for g, ext in self._ext_after.values():
            g.ext = copy.deepcopy(ext) if ext else None
        self._settle(scene)

    def undo(self, scene) -> None:
        for mesh, before, _a in reversed(self._edits.meshes):
            mesh.restore_state(before)
        for g, before, _a in reversed(self._edits.groups):
            _put_group_state(g, before)
        for g, ext in self._ext_before.values():
            g.ext = copy.deepcopy(ext) if ext else None
        self._settle(scene)


def follow(scene, before: dict) -> Optional[FollowOpeningsCommand]:
    """After a command: bring every opening of the context up to date, as a
    command already applied (for the history to fold into the same step),
    or None when nothing changed."""
    if not pending(scene, before):
        return None
    edits = _Edits()
    ext_before = {uid: (g, _copy_ext(g))
                  for uid, g in _concerned(scene, before).items()}
    try:
        edited, refused = bring_up_to_date(scene, before, edits)
    except Exception:
        for mesh, snap, _a in reversed(edits.meshes):
            mesh.restore_state(snap)
        for g, st, _a in reversed(edits.groups):
            _put_group_state(g, st)
        for g, ext in ext_before.values():
            g.ext = copy.deepcopy(ext) if ext else None
        scene.version += 1
        raise
    edits.seal()
    ext_after = {uid: (g, _copy_ext(g))
                 for uid, (g, _e) in ext_before.items()}
    cmd = FollowOpeningsCommand(edits, ext_before, ext_after, edited, refused)
    if edits.any():
        cmd._settle(scene)
    return cmd


class SetCutOpeningCommand(Command):
    """Mark or unmark containers «Cut opening»; the history's follow-up
    then cuts or closes their holes in the same step."""

    keeps_paint = True
    keeps_groups = True

    def __init__(self, groups, on: bool) -> None:
        self.groups = list(groups)
        self.on = bool(on)
        self._before = None

    def do(self, scene) -> None:
        self._before = [(g, _copy_ext(g)) for g in self.groups]
        for g in self.groups:
            entry = dict(_entry(g))
            if self.on:
                entry["on"] = True
            else:
                entry.pop("on", None)
            set_ext_entry(g, entry)
        scene.version += 1

    def undo(self, scene) -> None:
        for g, ext in self._before or ():
            g.ext = copy.deepcopy(ext) if ext else None
        scene.version += 1


def cutting_targets(scene, selection) -> list:
    """The containers a «Cut opening» toggle acts on: the selected groups
    and components, with every copy of each component."""
    from core.group import Group
    out = []
    seen = set()
    for e in selection:
        if not isinstance(e, Group) or getattr(e, "billboard", False):
            continue
        for g in siblings(scene, e):
            if id(g) not in seen:
                seen.add(id(g))
                out.append(g)
    return out
