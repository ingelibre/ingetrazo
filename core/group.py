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


def np_affine(m):
    """``QMatrix4x4`` → ``(rot, trans)`` NumPy arrays: ``pts @ rot.T + trans``
    is ``m.map(p)`` for every row. ``data()`` is column-major."""
    import numpy as np
    d = m.data()
    rot = np.array([[d[0], d[4], d[8]],
                    [d[1], d[5], d[9]],
                    [d[2], d[6], d[10]]], dtype=np.float64)
    return rot, np.array([d[12], d[13], d[14]], dtype=np.float64)


def transformed_mesh(src: Mesh, m) -> Mesh:
    """A DEEP copy of ``src`` with every position mapped through ``m``,
    carrying face attrs, soft/curve flags and re-fitted texture UV maps.

    Big meshes go through one vectorized ``bulk_weld`` pass (same recipe as
    the ``.igz`` loader): the per-entity ``add_face``/``add_edge`` walk froze
    the UI for ~16 s copying a 17k-face plant group (piscina report) — and
    ran TWICE, once at copy and once per paste stamp. Small meshes keep the
    plain walk (the bulk pass's fixed cost loses there)."""
    if len(src.edges) * 2 + len(src.faces) * 4 < 1024:
        return _transformed_mesh_walk(src, m)
    import numpy as np
    from core.topology import _maximal_holes
    new = Mesh()
    flat: list = []
    for e in src.edges:
        flat.append((e.a.x(), e.a.y(), e.a.z()))
        flat.append((e.b.x(), e.b.y(), e.b.z()))
    n_edge_pts = len(flat)
    ring_sizes: list = []
    ring_counts: list = []
    attrs_list: list = []
    for f in src.faces:
        holes = f.holes or []
        if len(holes) > 1:
            holes = _maximal_holes([list(h) for h in holes])
        ring_counts.append(1 + len(holes))
        ring_sizes.append(len(f.vertices))
        flat.extend((v.x(), v.y(), v.z()) for v in f.vertices)
        for h in holes:
            ring_sizes.append(len(h))
            flat.extend((v.x(), v.y(), v.z()) for v in h)
        attrs_list.append(dict(f.attrs) if f.attrs else None)
    if not flat:
        return new
    rot, trans = np_affine(m)
    pts = np.array(flat, dtype=np.float64) @ rot.T + trans
    vobjs, inverse = new.bulk_weld(pts)
    emap = None
    if src.edges:
        flags = [(e.soft, e.curve, None) for e in src.edges]
        emap = new.add_edges_welded(
            vobjs, inverse[0:n_edge_pts:2], inverse[1:n_edge_pts:2], flags)
    if ring_counts:
        new.add_faces_welded(vobjs, inverse[n_edge_pts:], ring_sizes,
                             ring_counts, attrs_list, edge_map=emap)
    new.resplit_curves()
    _remap_uvws(new, m)
    return new


def _transformed_mesh_walk(src: Mesh, m) -> Mesh:
    """Sequential per-entity copy — exact semantics for small meshes."""
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
