# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Group: a self-contained chunk of geometry with its own mesh.

The scene's main mesh welds every coincident vertex (sticky geometry), so a
block drawn against a wall fuses with it. A Group isolates geometry into its
*own* :class:`~core.mesh.Mesh` (still in world coordinates for now — no instance
transform yet, that's Components): nothing welds across the group boundary, so it
moves and edits as a unit without dragging the rest of the model.

Selected as a unit and moved/exploded via the commands in :mod:`core.history`.
"""
from __future__ import annotations

import itertools

from core.mesh import Mesh

_counter = itertools.count(1)


class Group:
    __slots__ = ("mesh", "name", "layer", "ifc", "billboard", "xform")

    def __init__(self, mesh: Mesh | None = None, name: str | None = None) -> None:
        self.mesh = mesh if mesh is not None else Mesh()
        self.name = name or f"Group {next(_counter)}"
        # Layer / tag name (None = default layer).
        self.layer = None
        # BIM tag ({"class": "IfcWall", "name": ...}) or None — see core/bim.py.
        self.ifc = None
        # Face-me billboard (SketchUp): the group's textured quad rotates
        # around its vertical anchor axis to face the camera every frame.
        self.billboard = False
        # Component instance (SketchUp): when set, ``mesh`` is a PROTOTYPE in
        # local coordinates SHARED with sibling instances, and ``xform`` maps
        # local -> world. ``None`` = classic group (mesh in world coords).
        # Instances render/pick through transformed chunk arrays; transform
        # tools compose into ``xform`` (O(1)); geometry edits first
        # ``materialize`` the instance (SketchUp's "make unique").
        self.xform = None

    def is_instance(self) -> bool:
        return self.xform is not None

    def materialize(self) -> None:
        """Bake this instance into its OWN world-space mesh (SketchUp 'make
        unique'): sibling instances keep the shared prototype untouched."""
        if self.xform is None:
            return
        self.mesh = world_mesh(self)
        self.xform = None

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        kind = " instance" if self.xform is not None else ""
        return (f"Group({self.name!r}{kind}: {len(self.mesh.faces)} faces, "
                f"{len(self.mesh.edges)} edges)")


def make_billboard_group(image_path: str, height: float, name: str,
                         aspect: float, position=None) -> Group:
    """A face-me billboard group: one textured quad, ``height`` metres tall,
    anchored at ``position`` (origin by default). The viewport rotates it
    around that anchor to face the camera."""
    from PySide6.QtGui import QVector3D
    mesh = Mesh()
    w = height * aspect
    p = position if position is not None else QVector3D(0, 0, 0)
    quad = [p + QVector3D(-w / 2, 0, 0), p + QVector3D(w / 2, 0, 0),
            p + QVector3D(w / 2, 0, height), p + QVector3D(-w / 2, 0, height)]
    face = mesh.add_face(quad)
    face.attrs["texture"] = {"path": str(image_path), "sw": w, "sh": height}
    g = Group(mesh, name=name)
    g.billboard = True
    return g


def _remap_uvws(mesh, m) -> None:
    """Rewrite each face's world→UV affine map (``uvw``) so that evaluating
    it at the TRANSFORMED positions reproduces the prototype's UVs:
    g' = L⁻ᵀ·g, c' = c − g'·t."""
    minv, ok = m.inverted()
    if not ok:
        return
    tx, ty, tz = m(0, 3), m(1, 3), m(2, 3)
    for f in mesh.faces:
        t = f.attrs.get("texture") if f.attrs else None
        uvw = t.get("uvw") if t else None
        if not uvw or len(uvw) != 8:
            continue
        new = list(uvw)
        for base in (0, 4):
            gx, gy, gz, c = uvw[base:base + 4]
            gpx = minv(0, 0) * gx + minv(1, 0) * gy + minv(2, 0) * gz
            gpy = minv(0, 1) * gx + minv(1, 1) * gy + minv(2, 1) * gz
            gpz = minv(0, 2) * gx + minv(1, 2) * gy + minv(2, 2) * gz
            new[base:base + 4] = [gpx, gpy, gpz,
                                  c - (gpx * tx + gpy * ty + gpz * tz)]
        f.attrs["texture"] = {**t, "uvw": new}


def world_mesh(group) -> Mesh:
    """A world-space mesh for a group: the mesh itself for classic groups,
    a transformed DEEP copy (positions + texture UV maps) for component
    instances — the shared prototype is never touched. (``capture_state``
    keeps object identity, so it can NOT be used to copy: restoring it into
    a new mesh aliases the prototype's vertices and a later move would
    corrupt every sibling.)"""
    m = getattr(group, "xform", None)
    if m is None:
        return group.mesh
    return transformed_mesh(group.mesh, m)


def transformed_mesh(src: Mesh, m) -> Mesh:
    """A DEEP copy of ``src`` with every position mapped through ``m``,
    carrying face attrs, soft/curve flags and re-fitted texture UV maps."""
    from PySide6.QtGui import QVector3D
    new = Mesh()

    def W(p) -> QVector3D:
        return m.map(p)

    for f in src.faces:
        try:
            nf = new.add_face([W(v) for v in f.vertices],
                              [[W(v) for v in h] for h in f.holes] or None)
        except Exception:  # noqa: BLE001 — degenerate under the transform
            continue
        if f.attrs:
            nf.attrs.update(dict(f.attrs))
    for e in src.edges:
        v0, v1 = new.vertex_at(W(e.a)), new.vertex_at(W(e.b))
        ne = (new.find_edge(v0, v1)
              if v0 is not None and v1 is not None else None)
        if ne is None:
            try:
                ne = new.add_edge(W(e.a), W(e.b))
            except Exception:  # noqa: BLE001
                continue
        ne.soft = e.soft
        ne.curve = e.curve
    new.resplit_curves()
    _remap_uvws(new, m)
    return new


def transformed_attrs(attrs, m) -> dict:
    """A copy of face ``attrs`` with the texture's world→UV affine map
    (``uvw``) re-fitted for geometry mapped through ``m`` — the single-face
    analogue of :func:`_remap_uvws` (g' = L⁻ᵀ·g, c' = c − g'·t). Used when a
    transform duplicates loose faces (rotate-a-copy)."""
    out = dict(attrs) if attrs else {}
    t = out.get("texture")
    uvw = t.get("uvw") if t else None
    if not uvw or len(uvw) != 8:
        return out
    minv, ok = m.inverted()
    if not ok:
        return out
    tx, ty, tz = m(0, 3), m(1, 3), m(2, 3)
    new = list(uvw)
    for base in (0, 4):
        gx, gy, gz, c = uvw[base:base + 4]
        gpx = minv(0, 0) * gx + minv(1, 0) * gy + minv(2, 0) * gz
        gpy = minv(0, 1) * gx + minv(1, 1) * gy + minv(2, 1) * gz
        gpz = minv(0, 2) * gx + minv(1, 2) * gy + minv(2, 2) * gz
        new[base:base + 4] = [gpx, gpy, gpz,
                              c - (gpx * tx + gpy * ty + gpz * tz)]
    out["texture"] = {**t, "uvw": new}
    return out


def translated_attrs(attrs, delta) -> dict:
    """A copy of face ``attrs`` re-anchored for geometry moved by ``delta``:
    the texture's world→UV affine map (``uvw``) is position-anchored, so its
    constant term must follow the translation (the gradient is unchanged) or
    the texture stays behind while the face moves."""
    out = dict(attrs) if attrs else {}
    t = out.get("texture")
    uvw = t.get("uvw") if t else None
    if uvw and len(uvw) == 8:
        new = list(uvw)
        for base in (0, 4):
            gx, gy, gz, c = uvw[base:base + 4]
            new[base + 3] = c - (gx * delta.x() + gy * delta.y()
                                 + gz * delta.z())
        out["texture"] = {**t, "uvw": new}
    return out


def copy_group(group, delta=None):
    """A pastable duplicate of ``group``, optionally translated by ``delta``.

    A component instance stays an instance: the duplicate SHARES the prototype
    mesh and only gets its own transform (SketchUp: copying an instance adds a
    sibling, O(1)). A classic group gets a deep mesh copy."""
    from PySide6.QtGui import QMatrix4x4, QVector3D
    t = QMatrix4x4()
    if delta is not None:
        t.translate(QVector3D(delta))
    if group.xform is not None:
        g = Group(group.mesh, name=group.name)
        g.xform = t * group.xform
    else:
        g = Group(transformed_mesh(group.mesh, t), name=group.name)
    g.layer = group.layer
    g.ifc = dict(group.ifc) if group.ifc else None
    g.billboard = group.billboard
    return g
