# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Make Faces and Extrude: the faces the selected edges close, each one
turned straight into a solid of the given height, in one step.

The step after an imported plan is nearly always the same: make the faces,
then pull every one of them up to the same height (walls, a slab, the
kerbs of a plaza). This does both at once.

* The faces are found exactly as :mod:`core.make_faces` finds them (one
  plane per level, crossings split, a new face looking up or towards the
  camera), so a positive height never goes into the floor or into the
  wall.
* Every face becomes its OWN group: a closed prism built in a fresh mesh.
  Two faces that share an edge do not fuse into one block nor drag each
  other, and each solid can be moved, hidden or tagged on its own.
* The face is replaced by its solid; the lines stay where they were, so
  the plan is still there to make the next storey from. A face that was
  already part of a solid (it has neighbours) is left alone and only gets
  its new solid beside it.
* A loop inside the hole of another (the room ringed by the walls) is
  left as a hole, unless asked to extrude the inner loops too (a column
  inside a slab).
* Paint, layer and BIM tag travel from the face to its solid. A curve
  (a circle, an arc) stays a curve: its seams on the sides are soft, as
  Push/Pull leaves them, and the two rings are curves again.

Headless: :func:`extrude_faces_to_groups` and :func:`prism_group` work on
meshes; :class:`MakeFacesExtrudeCommand` runs everything as one undo step
in the open context (the model or the group being edited).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QVector3D

from core.group import Group
from core.history import Command, InsertGroupCommand, SnapshotMutation
from core.make_faces import MakeFacesError, _ring_key, make_faces, plan
from core.mesh import Mesh

#: Heights closer to zero than this (0.1 mm) make no solid.
MIN_HEIGHT = 1e-4
#: The dihedral rule Push/Pull softens a swept curve's seams with
#: (``PushPullTool._CURVE_FACET_COS``): a 24-side circle reads smooth, a
#: hexagon keeps its edges.
_CURVE_FACET_COS = 0.85


class MakeFacesExtrudeError(MakeFacesError):
    """Nothing to make or extrude; the message says why (English source
    text, translated by the caller)."""


def _newell(points) -> QVector3D:
    nx = ny = nz = 0.0
    n = len(points)
    for i in range(n):
        p, q = points[i], points[(i + 1) % n]
        nx += (p.y() - q.y()) * (p.z() + q.z())
        ny += (p.z() - q.z()) * (p.x() + q.x())
        nz += (p.x() - q.x()) * (p.y() + q.y())
    return QVector3D(nx, ny, nz)


def _wound(points, axis: QVector3D, ccw: bool) -> tuple:
    """``(points, reversed)`` — ``points`` wound counter-clockwise (``ccw``)
    or clockwise seen from ``axis``, and whether they had to be turned
    round for that."""
    pts = [QVector3D(p) for p in points]
    turns_ccw = QVector3D.dotProduct(_newell(pts), axis) >= 0.0
    if turns_ccw == ccw:
        return pts, False
    return list(reversed(pts)), True


def _ring_curves(mesh, ring) -> list:
    """The curve id of each edge of the vertex ``ring`` (``None`` for a
    straight segment), edge ``i`` running from ``ring[i]`` to the next."""
    n = len(ring)
    out = []
    for i in range(n):
        e = mesh.find_edge(ring[i], ring[(i + 1) % n]) if mesh is not None \
            else None
        out.append(getattr(e, "curve", None) if e is not None else None)
    return out


def prism_group(face, height: float, mesh: Optional[Mesh] = None) -> Group:
    """A new group holding ``face`` pushed ``height`` along its normal: a
    closed prism in its own mesh, in world coordinates (the face's).

    A negative height goes the other way. ``mesh`` is the mesh the face
    lives in; when given, its curves (a circle, an arc) are carried to the
    solid."""
    normal = face.normal()
    axis = normal if height >= 0 else -normal
    shift = normal * float(height)

    rings = [face.loop, *face.hole_loops]
    curves = [_ring_curves(mesh, r) for r in rings]
    positions = []
    for k, ring in enumerate(rings):
        pts = [QVector3D(v.position) for v in ring]
        wound, turned = _wound(pts, axis, ccw=(k == 0))
        if turned:
            # Reversed: edge i now runs between what were i+1 and i, so the
            # curve list turns round too (edge i ↔ old edge n-2-i).
            ids = curves[k]
            curves[k] = [ids[(len(ids) - 2 - i) % len(ids)]
                         for i in range(len(ids))]
        positions.append(wound)

    solid = Mesh()
    outer, holes = positions[0], positions[1:]
    # Bottom looks against the push, the top along it, the sides out.
    solid.add_face(list(reversed(outer)),
                   [list(reversed(h)) for h in holes] or None)
    solid.add_face([p + shift for p in outer],
                   [[p + shift for p in h] for h in holes] or None)
    for ring in positions:
        n = len(ring)
        for i in range(n):
            a, b = ring[i], ring[(i + 1) % n]
            solid.add_face([a, b, b + shift, a + shift])

    paint = dict(face.attrs or {})
    for f in solid.faces:
        f.attrs.update(paint)

    # Curves: each run of one curve id becomes a curve again on both rings.
    for ring, ids in zip(positions, curves):
        n = len(ring)
        fresh: dict = {}
        for i, cid in enumerate(ids):
            if cid is None:
                continue
            for top, lift in enumerate((QVector3D(), shift)):
                key = (cid, top)
                if key not in fresh:
                    fresh[key] = Mesh.next_curve_id()
                va = solid.vertex_at(ring[i] + lift)
                vb = solid.vertex_at(ring[(i + 1) % n] + lift)
                e = solid.find_edge(va, vb) if va is not None and vb is not None else None
                if e is not None:
                    e.curve = fresh[key]
    for e in solid.edges:
        if len(e.faces) != 2 or e.soft:
            continue
        d = QVector3D.dotProduct(e.faces[0].normal(), e.faces[1].normal())
        if _CURVE_FACET_COS < d < 0.99995:
            e.soft = True

    group = Group(solid)
    group.layer = paint.get("layer")
    return group


def _has_neighbours(mesh, face, besides=frozenset()) -> bool:
    """Whether ``face`` shares an edge with a face outside ``besides`` (ids
    of the faces extruded with it): then it belongs to a solid or a
    surface, and taking it out would open a hole."""
    for ring in (face.loop, *face.hole_loops):
        n = len(ring)
        for i in range(n):
            e = mesh.find_edge(ring[i], ring[(i + 1) % n])
            if e is not None and any(f is not face and id(f) not in besides
                                     for f in e.faces):
                return True
    return False


def extrude_faces_to_groups(mesh, faces, height: float) -> list:
    """One solid group per face of ``faces`` (faces of ``mesh``), each
    ``height`` tall; the faces are taken out of ``mesh`` — their solids
    replace them — while their edges stay. Two of them side by side both
    go; one that also touches a face left out (a solid's) stays. Returns
    the groups."""
    groups = [prism_group(f, height, mesh) for f in faces]
    batch = frozenset(map(id, faces))
    gone = [f for f in faces
            if f in mesh.faces and not _has_neighbours(mesh, f, batch)]
    for f in gone:
        mesh.remove_face(f)
    return groups


def inner_faces(faces) -> list:
    """The faces of ``faces`` that fill the hole of another one: the inside
    of a room ringed by walls, the bore of a tube. Their outline is a hole
    ring of a sibling."""
    holes = set()
    for f in faces:
        for h in f.holes:
            holes.add(_ring_key(h))
    return [f for f in faces if _ring_key(f.vertices) in holes]


def check(edges, height: float) -> None:
    """Raise :class:`MakeFacesError` when ``edges`` close no loop or the
    height is zero — before anything is touched."""
    if abs(float(height)) < MIN_HEIGHT:
        raise MakeFacesExtrudeError("The height cannot be zero.")
    plan(edges)


class MakeFacesExtrudeCommand(Command):
    """Make Faces and Extrude as one undo step in the open context: the
    faces are made on ``edges``, each one becomes its own solid group of
    ``height``, and the new groups end up selected.

    ``fill_holes`` off (the default) leaves a loop that sits in the hole of
    another as a hole: the room inside the walls is not filled with a
    block. Its face is not kept either when it was only made for this —
    the lines stay, as they came. On, it becomes a solid of its own too (a
    column inside a slab).

    ``self.result`` holds what :func:`core.make_faces.make_faces` reported,
    plus ``"groups"`` and ``"inner"`` (the loops left as holes)."""

    def __init__(self, edges, height: float, eye=None,
                 fill_holes: bool = False) -> None:
        self.edges = list(edges)
        self.height = float(height)
        self.eye = eye
        self.fill_holes = bool(fill_holes)
        self.result: dict = {}
        self.groups: list = []
        self._mutation: Optional[SnapshotMutation] = None
        self._inserts: list = []

    def _mutate(self, scene) -> None:
        mesh = scene.mesh
        before = set(map(id, mesh.faces))
        out = make_faces(mesh, self.edges, self.eye)
        faces = [f for f in out.get("faces", ()) if f in mesh.faces]
        inner = [] if self.fill_holes else inner_faces(faces)
        if inner:
            skip = set(map(id, inner))
            faces = [f for f in faces if id(f) not in skip]
            for f in inner:
                if id(f) not in before:      # made only now: back to lines
                    mesh.remove_face(f)
        self.groups = extrude_faces_to_groups(mesh, faces, self.height)
        out["groups"] = self.groups
        out["inner"] = len(inner)
        self.result = out

    def do(self, scene) -> None:
        if self._mutation is None:
            self._mutation = SnapshotMutation(self._mutate)
            self._mutation.do(scene)
            self._inserts = [InsertGroupCommand(g) for g in self.groups]
        else:
            self._mutation.do(scene)
        for cmd in self._inserts:
            cmd.do(scene)
        scene.selection.clear()
        scene.selection.update(self.groups)
        scene.version += 1

    def undo(self, scene) -> None:
        for cmd in reversed(self._inserts):
            cmd.undo(scene)
        if self._mutation is not None:
            self._mutation.undo(scene)
        scene.selection.clear()
        scene.version += 1
