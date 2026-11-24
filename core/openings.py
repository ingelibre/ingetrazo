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
  empty gets its face back, facing out, and joins the faces the opening was
  taken from — those alone: a plinth, a change of paint or of BIM tag, any
  line of the wall stays where it was, lines the opening ran over included
  (what they were is kept in the prism's ``was``, see :func:`_note`).

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


def _covered(mesh, face, points) -> bool:
    """Whether the polygon ``points`` lies within ``face``, or within it and
    the faces of its plane that carry it on across a mere division (a
    plinth's line, a change of paint). A line where a third face stands — a
    partition meeting the wall — is an edge no opening crosses."""
    n = _normal(points)
    u, v = _basis(n)
    origin = points[0]
    poly = _to2d(points, origin, u, v)
    scale = max(max(abs(x) for x, _ in poly), max(abs(y) for _, y in poly), 1.0)
    eps = 1e-6 * scale
    if _covers(face, points) and not any(
            _inside(c, poly) and not _on_boundary(c, poly, eps)
            for h in face.holes for c in _to2d(h, origin, u, v)):
        return True
    faces = _coplanar_faces(mesh, points)
    shared: dict = {}
    for f in faces:
        for e in _face_edges(mesh, f):
            shared.setdefault(id(e), [e, 0])[1] += 1
    for e, count in shared.values():
        if count == 2 and len(e.faces) == 2:
            continue                                     # a mere division
        (ax, ay), (bx, by) = _to2d((e.a, e.b), origin, u, v)
        dx, dy = bx - ax, by - ay
        stops = [0.0, 1.0]
        for i, (cx, cy) in enumerate(poly):
            fx, fy = poly[(i + 1) % len(poly)]
            ex, ey = fx - cx, fy - cy
            det = dx * ey - dy * ex
            if abs(det) < 1e-12:
                continue
            t = ((cx - ax) * ey - (cy - ay) * ex) / det
            if 0.0 < t < 1.0:
                stops.append(t)
        stops.sort()
        for t0, t1 in zip(stops, stops[1:]):
            t = (t0 + t1) / 2.0
            mid = (ax + dx * t, ay + dy * t)
            if _inside(mid, poly) and not _on_boundary(mid, poly, eps):
                return False                # the wall ends inside the opening
    for p, c in zip(points, poly):
        if not any(_face_holds(f, p, n) or _on_boundary(
                c, _to2d(f.vertices, origin, u, v), eps) for f in faces):
            return False
    return True


def _face_edges(mesh, face):
    """The edges of ``face``'s loops."""
    for lp in (face.loop, *face.hole_loops):
        for i in range(len(lp)):
            e = mesh.find_edge(lp[i - 1], lp[i])
            if e is not None:
                yield e


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


def _face_around(mesh, points):
    """The face most of the outline ``points`` runs on: what the reveals
    are painted like — not a panel of the wall inside it."""
    n = _normal(points)
    best, most = None, 0.0
    for f in _coplanar_faces(mesh, points):
        on = sum((b - a).length() for a, b in _segments(points)
                 if _face_holds(f, (a + b) / 2.0, n))
        if on > most:
            best, most = f, on
    return best if best is not None else _host_face(mesh, points)


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


#: Length of the arrow that shows the way a hole is cut (metres).
ARROW_LENGTH = 0.5
#: The sides of a component that can be flush with the wall, as the normal
#: that comes out of the wall in the component's own axes.
PLANE_SIDES = {
    "front": (0.0, -1.0, 0.0), "back": (0.0, 1.0, 0.0),
    "left": (-1.0, 0.0, 0.0), "right": (1.0, 0.0, 0.0),
    "top": (0.0, 0.0, 1.0), "bottom": (0.0, 0.0, -1.0),
}
_OPPOSITE = {"front": "back", "back": "front", "left": "right",
             "right": "left", "top": "bottom", "bottom": "top"}


def side_of(group) -> Optional[str]:
    """The side of ``group`` chosen as its cut plane, or None for the base
    plane (local ``z = 0``, the blue axis out of the wall)."""
    plane = _entry(group).get("plane")
    if isinstance(plane, dict):
        n = plane.get("n")
        for name, v in PLANE_SIDES.items():
            if isinstance(n, (list, tuple)) and len(n) == 3 and all(
                    abs(float(a) - b) < 1e-6 for a, b in zip(n, v)):
                return name
    return None


def _distance_out(group, n) -> float:
    """How far the component reaches along ``n`` (its own axes): where its
    face on that side is."""
    from core.group import iter_placements
    inv, ok = _frame(group).inverted()
    if not ok:
        return 0.0
    nv = QVector3D(*n)
    best = float("-inf")
    for g, m in iter_placements(group):
        pts = [v for f in g.mesh.faces for v in f.vertices]
        pts += [p for e in g.mesh.edges for p in (e.a, e.b)]
        for p in pts:
            q = inv.map(m.map(p) if m is not None else QVector3D(p))
            best = max(best, QVector3D.dotProduct(q, nv))
    return best if best != float("-inf") else 0.0


def _plane_frame(group):
    """The matrix of the axes the footprint is taken in: the component's own
    frame, or — with a chosen side — the plane flush with the wall (x along
    the wall, y up it, z out of it)."""
    from PySide6.QtGui import QMatrix4x4
    frame = _frame(group)
    plane = _entry(group).get("plane")
    if not isinstance(plane, dict) or side_of(group) is None:
        return frame
    nv = QVector3D(*plane["n"]).normalized()
    if abs(nv.z()) < 0.9:
        x = QVector3D.crossProduct(QVector3D(0, 0, 1), nv).normalized()
    else:
        x = QVector3D(1, 0, 0)
    y = QVector3D.crossProduct(nv, x).normalized()
    c = nv * float(plane.get("d", 0.0))
    return frame * QMatrix4x4(x.x(), y.x(), nv.x(), c.x(),
                              x.y(), y.y(), nv.y(), c.y(),
                              x.z(), y.z(), nv.z(), c.z(),
                              0, 0, 0, 1)


def footprint(group) -> Optional[list]:
    """The opening's outline in world coordinates, counter-clockwise seen
    from the blue axis of its plane, or None when the component has nothing
    to cut with.

    The plane is the component's base plane (local ``z = 0``) or, when the
    component has chosen one (:func:`side_of`), the plane of that side. The
    outline is the outer loop of the largest face lying on it; with none
    there, the rectangle the component covers on it. A plane whose entry
    says ``"outline": "box"`` always takes the rectangle: a component made of
    parts (a frame's bars) has no single face that is its outline."""
    from core.group import iter_placements
    frame = _plane_frame(group)
    inv, ok = frame.inverted()
    if not ok:
        return None
    plane = _entry(group).get("plane")
    use_faces = not (isinstance(plane, dict) and plane.get("outline") == "box")
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
            if (use_faces and len(local) >= 3
                    and all(abs(p.z()) < _PLANE_EPS for p in local)):
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


def direction(group):
    """``(point, unit vector)`` in world coordinates: the middle of the
    component's opening on the wall's face and the way its hole is cut (into
    the wall), or None — what the arrow over a selected component shows."""
    a = footprint(group)
    if not a:
        return None
    return _centroid(a), -_normal(a)


# ---- Where it cuts -----------------------------------------------------------
def plan_in(mesh, a) -> Optional[dict]:
    """The prism the footprint ``a`` (in ``mesh``'s own coordinates) would
    cut in ``mesh``: ``{"a": front loop, "b": back loop or None}``, or None
    when it lies on no face of it."""
    host = _host_face(mesh, a)
    if host is None or not _covered(mesh, host, a):
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
        if (_face_holds(f, probe - n * d, n)
                and _covered(mesh, f, [p - n * d for p in a])):
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


def _off_segment(p, a, b) -> float:
    """Distance from ``p`` to the segment ``a``-``b``."""
    d = b - a
    ll = d.lengthSquared()
    t = QVector3D.dotProduct(p - a, d) / ll if ll > 1e-18 else 0.0
    return (p - a - d * max(0.0, min(1.0, t))).length()


def _on_outline(p, points) -> bool:
    return any(_off_segment(p, a, b) <= _PLANE_EPS
               for a, b in _segments(points))


def _edge_on_outline(e, points) -> bool:
    return any(_off_segment(e.a, a, b) <= _PLANE_EPS
               and _off_segment(e.b, a, b) <= _PLANE_EPS
               for a, b in _segments(points))


def _chain(mesh, a, b) -> list:
    """The corners met going from ``a`` to ``b`` along the edges drawn
    between them, ``b`` left out — just ``a`` when no edges join them. A
    face built on these shares every edge of the faces around it; one built
    on ``a``-``b`` alone would leave the corners between hanging on its
    side, and the wall open."""
    cur, end = mesh.vertex_at(a), mesh.vertex_at(b)
    if cur is None or end is None:
        return [a]
    d = b - a
    ll = d.lengthSquared()
    out, t = [a], 0.0
    while cur is not end:
        best = None
        for e in cur.edges:
            w = e.other(cur)
            tw = QVector3D.dotProduct(w.position - a, d) / ll
            if (tw <= t + 1e-9 or tw > 1.0 + 1e-5
                    or _off_segment(w.position, a, b) > _PLANE_EPS):
                continue
            rank = (not e.faces, tw)
            if best is None or rank < best[0]:
                best = (rank, w, tw)
        if best is None:
            return [a]
        _rank, cur, t = best
        out.append(QVector3D(cur.position))
    return out[:-1]


def _refined(mesh, points) -> list:
    """``points`` with the corners the mesh already has along its sides."""
    return [p for a, b in _segments(points) for p in _chain(mesh, a, b)]


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
    host = _face_around(mesh, prism["a"])
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
    had = {i: [QVector3D(x.position)
               for x in _corners_on(_coplanar_faces(mesh, polys[i]), polys[i])]
           for i in on_faces}
    for i in on_faces:
        _split_crossed(mesh, polys[i])
    was, inner = {}, {}
    for i in on_faces:
        note, edges = _take(mesh, polys[i], had[i])
        inner.update((id(e), e) for e in edges)
        if note:
            was[str(i)] = note
    prism["was"] = was
    for i, poly in enumerate(polys):
        if i in on_faces or i in keep:
            continue
        face = _add_face(scene, _refined(mesh, poly), paint)
        if face is not None:
            _orient(mesh, face, centre, inward=True)
    for e in inner.values():              # the lines the opening ran over
        if not e.faces and mesh.find_edge(e.v0, e.v1) is e:
            mesh.remove_edge(e)
    _drop_loose(mesh, prism)
    mesh.prune_orphan_vertices()
    scene.version += 1


# ---- What was there ----------------------------------------------------------
def _corners_on(faces, poly) -> list:
    """The corners of ``faces`` on the outline ``poly``."""
    return list({id(x): x for f in faces for lp in (f.loop, *f.hole_loops)
                 for x in lp if _on_outline(x.position, poly)}.values())


def _take(mesh, poly, had) -> tuple:
    """Take the polygon ``poly`` out of the faces of its plane, which keep
    their attrs and their winding. ``(note, edges)``: what healing cannot
    read off the wall around the hole — or ``{}`` — and the edges of the
    pieces taken away, some of them now loose. The note holds:

    - ``pieces``: the pieces taken, when more than one, each ``{"loop",
      "holes"}`` — with its ``attrs`` when it reached the outline nowhere
      but along lines of its own, so no face around it has them;
    - ``seams``: the parts of the outline that already were an edge;
    - ``lines``: the flags of the edges inside, those that have any;
    - ``corners``: ``had``, the corners that already were on the outline.

    Worked out here, and not drawn with the Line tool's plan: that one also
    closes cycles and faces them, over the wall it has just divided."""
    from core.mesh import edge_flags, edge_is_plain
    n = _normal(poly)
    u, v = _basis(n)
    zones = _coplanar_faces(mesh, poly)
    corners = _corners_on(zones, poly)
    ring = []
    for a, b in _segments(poly):
        d = b - a
        on = [x for x in (*corners, mesh.vertex(a))
              if _off_segment(x.position, a, b) <= _PLANE_EPS
              and x is not mesh.vertex_at(b)]
        for x in sorted(on, key=lambda x: QVector3D.dotProduct(
                x.position - a, d)):
            if x not in ring:
                ring.append(x)
    at: dict = {}

    def flat(x):
        c = at.get(x)
        if c is None:
            c = at[x] = _to2d([x.position], poly[0], u, v)[0]
        return c

    def mid(x, y):
        (ax, ay), (bx, by) = flat(x), flat(y)
        return (ax + bx) / 2.0, (ay + by) / 2.0

    outline = [flat(x) for x in ring]
    eps = 1e-5
    sides = [(x, ring[(i + 1) % len(ring)]) for i, x in enumerate(ring)]
    forward = {(id(x), id(y)) for x, y in sides}
    seams, marked, rows, edges = [], [], [], {}
    # The outline first, in its order, as the Line tool would leave it.
    drawn = set()
    for x, y in sides:
        if mesh.find_edge(x, y) is None:
            e = mesh.add_edge(x.position, y.position)
            drawn.add(id(e))
            edges[id(e)] = e
    alone = False
    for f in zones:
        loops = []
        for k, lp in enumerate((f.loop, *f.hole_loops)):
            ccw = _area2d([flat(x) for x in lp]) > 0
            loops.append(list(lp) if ccw == (k == 0) else lp[::-1])
        border = [[flat(x) for x in lp] for lp in loops]
        rest, piece = [], []
        for lp in loops:
            for i, x in enumerate(lp):
                y = lp[(i + 1) % len(lp)]
                if (id(x), id(y)) in forward:
                    piece.append((x, y))
                elif (id(y), id(x)) in forward:
                    rest.append((x, y))
                else:
                    m = mid(x, y)
                    (piece if _inside(m, outline)
                     and not _on_boundary(m, outline, eps)
                     else rest).append((x, y))
        for x, y in sides:
            m = mid(x, y)
            if (_inside(m, border[0])
                    and not any(_inside(m, h) for h in border[1:])
                    and not any(_on_boundary(m, b, eps) for b in border)):
                piece.append((x, y))
                rest.append((y, x))
        if not piece:
            continue
        attrs, interior = f.attrs, f.interior
        turned = QVector3D.dotProduct(f.normal(), n) < 0
        for e in _face_edges(mesh, f):
            edges[id(e)] = e
        taken = _trace(piece, flat)
        for loop, holes in taken:
            joined = False
            for lp in (loop, *holes):
                for i, x in enumerate(lp):
                    y = lp[(i + 1) % len(lp)]
                    e = mesh.find_edge(x, y)
                    if (id(x), id(y)) not in forward:
                        if e is not None and not edge_is_plain(e):
                            marked.append({"at": [x.position, y.position],
                                           "flags": list(edge_flags(e))})
                    elif e is not None and id(e) not in drawn:
                        seams.append([QVector3D(x.position),
                                      QVector3D(y.position)])
                    else:
                        joined = True
            row = {"loop": [QVector3D(x.position) for x in
                            (loop[::-1] if turned else loop)],
                   "holes": [[QVector3D(x.position) for x in h]
                             for h in holes]}
            if not joined:
                alone = True
                row["attrs"] = copy.deepcopy(attrs)
            rows.append(row)
        mesh.remove_face(f)
        for loop, holes in _trace(rest, flat):
            new = mesh.add_face([x.position for x in
                                 (loop[::-1] if turned else loop)],
                                [[x.position for x in h] for h in holes])
            new.attrs = copy.deepcopy(attrs)
            new.interior = interior
    note = {}
    if len(rows) > 1 or alone or any(r["holes"] for r in rows):
        note["pieces"] = rows
    if seams:
        note["seams"] = seams
    if marked:
        note["lines"] = marked
    if had:
        note["corners"] = had
    return note, list(edges.values())


def _trace(sides, flat) -> list:
    """``[(outer loop, [hole loops])]`` of the regions the directed ``sides``
    (the inside on their left) go round."""
    import math
    out: dict = {}
    for x, y in sides:
        out.setdefault(x, []).append(y)
    loops = []
    while out:
        start = next(iter(out))
        x, y = start, out[start].pop()
        if not out[start]:
            del out[start]
        loop = [x]
        while y is not start:
            loop.append(y)
            ways = out.get(y)
            if not ways:
                break                                  # an open chain
            (px, py), (qx, qy) = flat(x), flat(y)
            back = math.atan2(py - qy, px - qx)

            def turn(z, back=back, qx=qx, qy=qy):
                zx, zy = flat(z)
                return (back - math.atan2(zy - qy, zx - qx)) % (2 * math.pi)

            z = min(ways, key=lambda z: turn(z) or 2 * math.pi)
            ways.remove(z)
            if not ways:
                del out[y]
            x, y = y, z
        if len(loop) >= 3:
            loops.append(loop)
    areas = [_area2d([flat(x) for x in lp]) for lp in loops]
    outers = [(lp, a, []) for lp, a in zip(loops, areas) if a > 1e-10]
    for lp, a in zip(loops, areas):
        if a >= -1e-10:
            continue
        (ax, ay), (bx, by) = flat(lp[0]), flat(lp[1])
        m = ((ax + bx) / 2.0, (ay + by) / 2.0)
        around = [o for o in outers if o[1] > -a
                  and _inside(m, [flat(x) for x in o[0]])]
        if around:
            min(around, key=lambda o: o[1])[2].append(lp)
    return [(lp, holes) for lp, _a, holes in outers]


def _map_was(was, fn) -> dict:
    """``was`` with every list of points mapped by ``fn`` (list to list)."""
    out = {}
    for i, note in (was or {}).items():
        new = dict(note)
        if "pieces" in note:
            new["pieces"] = [{**r, "loop": fn(r["loop"]),
                              "holes": [fn(h) for h in r.get("holes") or ()]}
                             for r in note["pieces"]]
        if "seams" in note:
            new["seams"] = [fn(s) for s in note["seams"]]
        if "lines" in note:
            new["lines"] = [{**r, "at": fn(r["at"])} for r in note["lines"]]
        if "corners" in note:
            new["corners"] = fn(note["corners"])
        out[i] = new
    return out


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
    keep = _kept(prism)
    was = prism.get("was") or {}
    empty, loose = [], {}
    polys = [p for i, p in enumerate(_polygons(prism)) if i not in keep]
    _weld_outlines(mesh, polys)
    for i, poly in enumerate(_polygons(prism)):
        if i in keep:
            continue
        reveals = _faces_within(mesh, poly)
        for f in reveals:
            loose.update((id(e), e) for e in _face_edges(mesh, f))
            mesh.remove_face(f)
        if not reveals:
            empty.append((i, poly))
    corners, had = [], []
    for i, poly in empty:
        note = was.get(str(i)) or {}
        had += note.get("corners") or ()
        corners += [*_refined(mesh, poly),
                    *(p for r in note.get("pieces") or () for p in r["loop"])]
        _close(mesh, poly, note, centre)
    for e in list(loose.values()):
        if not e.faces and mesh.find_edge(e.v0, e.v1) is e:
            mesh.remove_edge(e)
    _drop_loose(mesh, prism)
    mesh.prune_orphan_vertices()
    _collapse_corners(mesh, corners, had)
    scene.version += 1
    return True


def _collapse_corners(mesh, corners, had) -> None:
    """The ``corners`` of the outline left in the middle of a straight edge
    once the wall is whole again (a door's foot splits the wall's bottom
    edge) — but for those the wall ``had`` before."""
    had = {_k(p) for p in had}
    for p in corners:
        v = mesh.vertex_at(p)
        if (v is not None and _k(v.position) not in had
                and mesh.collapsible_vertex(v)):
            mesh.collapse_vertex(v)


def _close(mesh, poly, note, centre) -> None:
    """Fill the empty polygon ``poly`` of the prism with the faces the
    opening took, each joined to the face it was taken from."""
    from core.mesh import stamp_edge_flags
    rows = note.get("pieces") or [{"loop": list(poly)}]
    for row in rows:
        for p in row["loop"]:
            _ensure_corner(mesh, p, poly)
    seams = [tuple(s) for s in note.get("seams") or ()]
    chords = []
    for p, q in _divisions_met(mesh, poly):
        (seams if _on_outline((p + q) / 2.0, poly) else chords).append((p, q))
    loops = [(_refined(mesh, r["loop"]),
              [_refined(mesh, h) for h in r.get("holes") or ()],
              r.get("attrs")) for r in rows]
    for chord in chords:
        loops = [part for piece in loops for part in _split_piece(piece, chord)]
    added = []
    for loop, holes, attrs in loops:
        face = mesh.add_face(loop, holes or None)
        if attrs:
            face.attrs = copy.deepcopy(attrs)
        if "pieces" not in note:
            _orient(mesh, face, centre, inward=False)
        added.append(face)
    for row in note.get("lines") or ():
        va, vb = (mesh.vertex_at(p) for p in row["at"])
        e = (mesh.find_edge(va, vb)
             if va is not None and vb is not None else None)
        if e is not None:
            stamp_edge_flags(e, row["flags"])
    new = set(added)
    for face in added:
        new.discard(_rejoin(mesh, face, poly, seams, new))


def _weld_outlines(mesh, polys) -> None:
    """Where a corner of one face hangs in the middle of another's side along
    the outlines ``polys`` (a line drawn up to the jamb, after the opening,
    splits the jamb and not the wall), split that side too — closed as it
    is, the hole would leave the wall open there."""
    faces = {id(f): f for p in polys for f in _coplanar_faces(mesh, p)}
    corners = {id(v): v for f in faces.values()
               for lp in (f.loop, *f.hole_loops) for v in lp
               if any(_on_outline(v.position, p) for p in polys)}
    for f in faces.values():
        for lp in (f.loop, *f.hole_loops):
            i = 0
            while i < len(lp):
                va, vb = lp[i], lp[(i + 1) % len(lp)]
                i += 1
                a, b = va.position, vb.position
                if id(va) not in corners or id(vb) not in corners:
                    continue
                hang = [v for v in corners.values()
                        if v is not va and v is not vb
                        and _off_segment(v.position, a, b) <= _PLANE_EPS]
                if not hang:
                    continue
                d = b - a
                mid = min(hang, key=lambda v: QVector3D.dotProduct(
                    v.position - a, d))
                e = mesh.find_edge(va, vb)
                if e is not None:
                    _split_edge(mesh, e, mid.position)
                    continue
                lp.insert(i, mid)        # a side the split left with no edge
                for x, y in ((va, mid), (mid, vb)):
                    half = mesh.find_edge(x, y)
                    if half is not None and f not in half.faces:
                        half.faces.append(f)
                mesh._chunk_dirty = True
                mesh._mut_serial += 1


def _ensure_corner(mesh, p, poly) -> None:
    """A corner at ``p`` of ``poly``'s outline, where a line the opening ran
    over met it: erased since, the edge there is whole and is split again
    (and whole again once the pieces join)."""
    if mesh.vertex_at(p) is not None:
        return
    for a, b in _segments(poly):
        if _off_segment(p, a, b) > _PLANE_EPS:
            continue
        chain = [*_chain(mesh, a, b), b]
        for q, r in zip(chain, chain[1:]):
            if _off_segment(p, q, r) > _PLANE_EPS:
                continue
            vq, vr = mesh.vertex_at(q), mesh.vertex_at(r)
            e = (mesh.find_edge(vq, vr)
                 if vq is not None and vr is not None else None)
            if e is not None:
                _split_edge(mesh, e, p)
            return


def _split_edge(mesh, e, p) -> None:
    """Split ``e`` at ``p``, both halves keeping its flags (its layer)."""
    from core.mesh import edge_flags, stamp_edge_flags
    flags = edge_flags(e)
    for half in mesh.split_edge(e, p):
        stamp_edge_flags(half, flags)


def _split_crossed(mesh, poly) -> None:
    """Split the edges of ``poly``'s plane its outline meets, where it meets
    them. Drawn over them, the outline would split them too, but what the
    planner splits loses its layer."""
    sides = _segments(poly)
    edges = {id(e): e for f in _coplanar_faces(mesh, poly)
             for e in _face_edges(mesh, f)}
    for e in edges.values():
        points = [p for p in poly if _off_segment(p, e.a, e.b) <= _PLANE_EPS]
        d = e.b - e.a
        for a, b in sides:
            s = b - a
            c = QVector3D.crossProduct(d, s)
            if c.lengthSquared() <= 1e-10 * d.lengthSquared() * s.lengthSquared():
                continue
            t = QVector3D.dotProduct(QVector3D.crossProduct(a - e.a, s), c) \
                / c.lengthSquared()
            p = e.a + d * t
            if (0.0 < t < 1.0 and _off_segment(p, a, b) <= _PLANE_EPS
                    and not any((p - q).length() <= _PLANE_EPS for q in points)):
                points.append(p)
        rest = [e]
        for p in points:
            for k, part in enumerate(rest):
                if (min((p - part.a).length(), (p - part.b).length())
                        > _PLANE_EPS
                        and _off_segment(p, part.a, part.b) <= _PLANE_EPS):
                    va, vb = part.v0, part.v1
                    _split_edge(mesh, part, p)
                    m = mesh.vertex_at(p)
                    rest[k:k + 1] = [x for x in (mesh.find_edge(va, m),
                                                 mesh.find_edge(m, vb)) if x]
                    break


def _in_plane(face, p0, n) -> bool:
    return (abs(QVector3D.dotProduct(face.normal(), n)) >= _PARALLEL
            and all(abs(QVector3D.dotProduct(v.position - p0, n)) <= _PLANE_EPS
                    for v in face.loop[:3]))


def _divisions_met(mesh, poly) -> list:
    """``(p, q)`` for every line of the wall the opening interrupts: one that
    divides two faces of its plane reaches the outline at ``p`` and goes on,
    straight, from ``q``. Drawn after the opening was cut, or cut before
    openings kept note of what they ran over."""
    n = _normal(poly)
    ends = []
    for p in _refined(mesh, poly):
        v = mesh.vertex_at(p)
        if v is None:
            continue
        for e in v.edges:
            if len(set(e.faces)) != 2 or len(e.faces) != 2:
                continue
            if not all(_in_plane(f, poly[0], n) for f in e.faces):
                continue
            o = e.other(v).position
            if _on_outline(o, poly) and _on_outline((o + p) / 2.0, poly):
                continue
            ends.append((p, (p - o).normalized()))
    out = []
    for i, (p, d) in enumerate(ends):
        for q, g in ends[i + 1:]:
            w = q - p
            if w.length() < _PLANE_EPS:
                continue
            w = w.normalized()
            if (QVector3D.dotProduct(w, d) > 0.99999
                    and QVector3D.dotProduct(w, g) < -0.99999):
                out.append((p, q))
    return out


def _split_piece(piece, chord) -> list:
    """``(loop, holes, attrs)`` cut along ``chord`` when it joins two of its
    corners through its inside."""
    loop, holes, attrs = piece
    keys = [_k(p) for p in loop]
    try:
        i, j = sorted(keys.index(_k(p)) for p in chord)
    except ValueError:
        return [piece]
    n = _normal(loop)
    u, v = _basis(n)
    mid = (loop[i] + loop[j]) / 2.0
    if (holes or _on_outline(mid, loop) or not _inside(
            _to2d([mid], loop[0], u, v)[0], _to2d(loop, loop[0], u, v))):
        return [piece]
    return [(loop[i:j + 1], [], attrs), (loop[j:] + loop[:i + 1], [], attrs)]


def _rejoin(mesh, face, poly, seams, new):
    """Give ``face`` back to the wall: what the opening cut it from — the
    faces across the outline, where the outline was not already a line of the
    wall — passes it its attrs (paint of both sides, BIM tag, layer), and is
    one face with it again. Faces that differ, and faces a line of the wall
    divides, are left as they are. Returns ``face``."""
    n = _normal(poly)

    def is_seam(e):
        mid = (e.a + e.b) / 2.0
        return any(_off_segment(mid, a, b) <= _PLANE_EPS for a, b in seams)

    across: dict = {}                     # neighbour -> length shared with it
    for e in _face_edges(mesh, face):
        if len(e.faces) != 2 or not _edge_on_outline(e, poly) or is_seam(e):
            continue
        for g in e.faces:
            if g is not face and g not in new and _in_plane(g, poly[0], n):
                across[g] = across.get(g, 0.0) + e.length()
    if not across:
        return face
    order = sorted(across, key=lambda g: -across[g])
    leader = order[0]
    if QVector3D.dotProduct(face.normal(), leader.normal()) < 0:
        face.loop.reverse()
        for h in face.hole_loops:
            h.reverse()
        mesh._chunk_dirty = True
        mesh._mut_serial += 1
    face.attrs = copy.deepcopy(leader.attrs)
    face.interior = leader.interior
    region, lines = [face, leader], {id(e) for e in _face_edges(mesh, leader)}
    for g in order[1:]:
        own = list(_face_edges(mesh, g))
        if (g.attrs != leader.attrs
                or QVector3D.dotProduct(g.normal(), leader.normal()) < _PARALLEL
                or any(id(e) in lines for e in own)):
            continue
        region.append(g)
        lines.update(id(e) for e in own)
    keep = [e for g in region for e in _face_edges(mesh, g) if is_seam(e)]
    merged = mesh.dissolve_coplanar_region(region, keep=keep)
    if merged is not None:
        merged.attrs = copy.deepcopy(face.attrs)
        merged.interior = face.interior
    return face


def _drop_loose(mesh, prism) -> None:
    """Edges of the prism no face uses any more, and their vertices. A line
    of the user's that only touches one of its corners is not one."""
    polys = _polygons(prism)
    corners = [mesh.vertex_at(p) for loop in (prism["a"], prism.get("b") or ())
               for p in loop]
    loose = {id(e): e for v in corners if v is not None for e in v.edges
             if not e.faces and any(_edge_on_outline(e, p) for p in polys)}
    for e in loose.values():
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
    """``world``: the placement's matrix composed from the context down —
    a wall inside «Ground floor ▸ Walls» sits where its parents put it.
    ``depth`` 0 is a container of the context itself."""

    def __init__(self, scene, group, world=None, depth: int = 0) -> None:
        from PySide6.QtGui import QMatrix4x4
        self.group = group
        self.uid = getattr(group, "uid", None)
        self.depth = depth
        if group is None:
            self.mesh = scene.mesh
            self.frame = QMatrix4x4()
            self.to_world = QMatrix4x4()
        else:
            self.mesh = group.mesh
            if depth == 0:
                world = getattr(group, "xform", None)
            self.to_world = (QMatrix4x4(world) if world is not None
                             else QMatrix4x4())
            axes = getattr(group, "axes", None)
            self.frame = (self.to_world * axes if axes is not None
                          else QMatrix4x4(self.to_world))
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
    for g, m, depth in _placements(scene, skip=group):
        if not _can_host(g):
            continue
        host = _Host(scene, g, m, depth)
        pts = host.mesh_points(a)
        if not _near(_bbox(host.mesh), pts, pad=10 * _PLANE_EPS):
            continue
        prism = plan_in(host.mesh, pts)
        if prism is not None:
            return host, prism
    return None, None


def _placements(scene, skip=None):
    """``(group, world matrix or None, depth)`` of every container of the
    context and every one nested in them, at any depth — leaving out
    ``skip`` and whatever it holds (a window's own parts are not a wall)."""
    for top in context_groups(scene):
        if top is skip:
            continue
        stack = [(top, getattr(top, "xform", None), 0)]
        while stack:
            g, m, depth = stack.pop()
            yield g, m, depth
            for child in getattr(g, "children", None) or ():
                if child is skip:
                    continue
                cm = getattr(child, "xform", None)
                if m is not None:
                    cm = m if cm is None else m * cm
                stack.append((child, cm, depth + 1))


def _find_placement(scene, uid):
    """``(group, world matrix, depth)`` of the container ``uid`` in the
    context, nested or not — None when it is gone. The top level is looked
    at first, without walking any tree."""
    for g in context_groups(scene):
        if getattr(g, "uid", None) == uid:
            return g, getattr(g, "xform", None), 0
    for g, m, depth in _placements(scene):
        if depth and getattr(g, "uid", None) == uid:
            return g, m, depth
    return None


def _host_of(scene, rec) -> Optional[_Host]:
    """The host a record cut in, as it is now — None when it is gone."""
    uid = rec.get("host")
    if uid is None:
        return _Host(scene, None)
    found = _find_placement(scene, uid)
    if found is None:
        return None
    return _Host(scene, *found)


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
    """How many other placements of the model use ``host``'s mesh — other
    containers sharing it, or the same nested container placed again by
    the copies of a component it belongs to."""
    if host.group is None:
        return 0
    from core.group import iter_placements
    n = 0
    for top in getattr(scene, "groups", None) or ():
        for g, _m in iter_placements(top):
            if g.mesh is host.mesh:
                n += 1
    return max(0, n - 1)


def _ready(scene, host, edits: _Edits, refused: list) -> Optional[_Host]:
    """The host, ready to be cut: a copied group sharing its mesh is made
    unique first (as opening it would); a component with other copies is
    refused — cutting it would cut every copy."""
    if host.group is not None and _shared(scene, host):
        # A component's copies, or a wall nested in something placed more
        # than once (a floor copied as a component): cutting it would cut
        # every copy, and making it unique would rebuild a tree the user
        # did not ask to touch.
        if host.group.is_component() or host.depth:
            refused.append(host.group.name)
            return None
        edits.groups.append([host.group, _group_state(host.group), None])
        host.group.make_unique()
        host = _Host(scene, host.group, None, 0)
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
            "keep": list(rec.get("keep") or ()),
            "was": _map_was(rec.get("was"), lambda pts: host.local_to_mesh(
                [QVector3D(*p) for p in pts]))}


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
        if host.depth:
            rec["nested"] = True
        rec["a"] = [list(p.toTuple()) for p in host.mesh_to_local(prism["a"])]
        rec["b"] = ([list(p.toTuple())
                     for p in host.mesh_to_local(prism["b"])]
                    if prism.get("b") else None)
        if prism.get("keep"):
            rec["keep"] = list(prism["keep"])
        if prism.get("was"):
            rec["was"] = _map_was(prism["was"], lambda pts: [
                list(p.toTuple()) for p in host.mesh_to_local(pts)])
    return rec


def _stale(scene, g, rec, by_uid) -> bool:
    """Whether ``g``'s record no longer matches: the component moved, or
    the wall it cut moved or went."""
    if rec.get("xf") != _frame_list(g):
        return True
    uid = rec.get("host")
    if rec.get("a") and uid is not None:
        if rec.get("nested"):
            found = _find_placement(scene, uid)
            if found is None:
                return True
            return rec.get("hxf") != _Host(scene, *found).frame_list()
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


class SetCutPlaneCommand(Command):
    """Choose the side of each container that is flush with the wall (or,
    with ``side`` None, go back to the base plane). The hole it had is marked
    out of date, so the history's follow-up closes it and cuts the new one in
    the same step; the container is marked «Cut opening» too."""

    keeps_paint = True
    keeps_groups = True

    def __init__(self, groups, side: Optional[str]) -> None:
        self.groups = list(groups)
        self.side = side
        self._before = None

    def do(self, scene) -> None:
        self._before = [(g, _copy_ext(g)) for g in self.groups]
        for g in self.groups:
            entry = dict(_entry(g))
            entry["on"] = True
            if self.side is None:
                entry.pop("plane", None)
            else:
                n = PLANE_SIDES[self.side]
                entry["plane"] = {"n": list(n), "d": _distance_out(g, n)}
            made_rec = entry.get("made")
            if isinstance(made_rec, dict):
                entry["made"] = dict(made_rec, xf=None)
            set_ext_entry(g, entry)
        scene.version += 1

    def undo(self, scene) -> None:
        for g, ext in self._before or ():
            g.ext = copy.deepcopy(ext) if ext else None
        scene.version += 1


def flipped_side(group) -> Optional[str]:
    """The side opposite to ``group``'s chosen one; the base plane's opposite
    is the component's bottom (local ``-z``), as the blue axis reversed."""
    cur = side_of(group)
    return _OPPOSITE[cur] if cur else "bottom"


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
