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
    __slots__ = ("mesh", "name", "layer", "ifc", "billboard", "xform",
                 "children", "owner")

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
        # Nested placements the group OWNS: each a Group with an ``xform``
        # over a SHARED prototype mesh, in this group's coordinates. They
        # render, pick and export as part of their parent — one object to
        # the user, however deep the tree — which is what lets an imported
        # component keep the sharing SketchUp gave it.
        #
        # Without them a component's internal repetition was flattened on
        # import: the hedge in piscina.igz is 4480 + 5120 faces placed 48
        # times, and it arrived as 230400 real ones. Twenty-four times the
        # geometry, for the element that is 89% of that model — which is
        # why the .skp we wrote was 80 MB against the original's 14, and
        # why SketchUp Web laboured over our copy of a model it draws
        # fluently itself.
        self.children: list = []
        # Set only on the throwaway placement proxies the viewport builds for
        # nested children: the top-level object a click must select. A real
        # group in ``scene.groups`` always has ``owner is None``.
        self.owner = None

    def adopt(self, children) -> None:
        """Take ``children`` as nested placements, guaranteeing the invariant
        every consumer relies on: **a group that owns placements is always an
        instance**.

        Move, Rotate and Scale compose into ``xform`` for an instance and walk
        the vertices otherwise — and walking the vertices would move the
        group's own mesh while leaving its children behind. An identity
        transform costs nothing and closes that road."""
        from PySide6.QtGui import QMatrix4x4
        self.children = list(children)
        if self.children and self.xform is None:
            self.xform = QMatrix4x4()

    def is_instance(self) -> bool:
        return self.xform is not None

    def materialize(self) -> None:
        """Bake this instance into its OWN world-space mesh (SketchUp 'make
        unique'): sibling instances keep the shared prototype untouched.

        Nested placements are baked in too and then dropped — ``world_mesh``
        already folded them, so keeping them would draw and export the
        child geometry a second time."""
        if self.xform is None and not self.children:
            return
        self.mesh = world_mesh(self)
        self.xform = None
        self.children = []

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
    corrupt every sibling.)

    A group's nested placements (``children``) are folded in, each through
    its own transform composed with this one — the group's full geometry,
    which is what every consumer that used to read ``group.mesh`` directly
    needs once a component keeps its internal sharing."""
    m = getattr(group, "xform", None)
    kids = getattr(group, "children", None)
    if not kids:
        return group.mesh if m is None else transformed_mesh(group.mesh, m)
    return _merged_placements(group)


def _merged_placements(group) -> Mesh:
    """Every placement of ``group`` welded into ONE mesh, in a single
    vectorized pass.

    Folding the children by copying each subtree and appending it face by
    face cost 20 s on the hedge against 4.5 s for the old single
    ``transformed_mesh`` — the per-entity walk this codebase already learned
    to avoid. Here each placement's corners are transformed as one array and
    the whole component welds once, the same recipe ``transformed_mesh`` and
    the ``.igz`` loader use."""
    import numpy as np
    from core.topology import _maximal_holes
    new = Mesh()
    edge_parts: list = []
    face_parts: list = []
    edge_flags: list = []
    ring_sizes: list = []
    ring_counts: list = []
    attrs_list: list = []
    for g, m in iter_placements(group):
        src = g.mesh
        epts: list = []
        fpts: list = []
        for e in src.edges:
            epts.append((e.a.x(), e.a.y(), e.a.z()))
            epts.append((e.b.x(), e.b.y(), e.b.z()))
            edge_flags.append((e.soft, e.curve, None))
        for f in src.faces:
            holes = f.holes or []
            if len(holes) > 1:
                holes = _maximal_holes([list(h) for h in holes])
            ring_counts.append(1 + len(holes))
            ring_sizes.append(len(f.vertices))
            fpts.extend((v.x(), v.y(), v.z()) for v in f.vertices)
            for h in holes:
                ring_sizes.append(len(h))
                fpts.extend((v.x(), v.y(), v.z()) for v in h)
            # The texture's world->UV map travels with the placement, so a
            # nested leaf keeps its wood grain instead of inheriting the
            # parent's frame.
            attrs_list.append(transformed_attrs(f.attrs, m)
                              if (f.attrs and m is not None)
                              else (dict(f.attrs) if f.attrs else None))
        if m is not None:
            rot, trans = np_affine(m)
            if epts:
                epts = np.asarray(epts, dtype=np.float64) @ rot.T + trans
            if fpts:
                fpts = np.asarray(fpts, dtype=np.float64) @ rot.T + trans
        else:
            epts = np.asarray(epts, dtype=np.float64) if epts else None
            fpts = np.asarray(fpts, dtype=np.float64) if fpts else None
        if epts is not None and len(epts):
            edge_parts.append(epts)
        if fpts is not None and len(fpts):
            face_parts.append(fpts)
    e_all = (np.concatenate(edge_parts) if edge_parts
             else np.empty((0, 3), dtype=np.float64))
    f_all = (np.concatenate(face_parts) if face_parts
             else np.empty((0, 3), dtype=np.float64))
    if not len(e_all) and not len(f_all):
        return new
    pts = np.concatenate([e_all, f_all])
    n_edge_pts = len(e_all)
    vobjs, inverse = new.bulk_weld(pts)
    emap = None
    if n_edge_pts:
        emap = new.add_edges_welded(
            vobjs, inverse[0:n_edge_pts:2], inverse[1:n_edge_pts:2],
            edge_flags)
    if ring_counts:
        new.add_faces_welded(vobjs, inverse[n_edge_pts:], ring_sizes,
                             ring_counts, attrs_list, edge_map=emap)
    new.resplit_curves()
    return new


def iter_placements(group, base=None):
    """Yield ``(group, world_matrix)`` for ``group`` and every nested
    placement below it, depth first, each matrix already composed from the
    root down.

    One call is all a consumer needs to walk a component that keeps its
    internal sharing: the geometry lives in ``g.mesh`` (prototype, local
    coordinates) and the matrix puts it in the world. Consumers that want a
    single merged mesh instead should use :func:`world_mesh`; consumers that
    draw or pick per prototype want this, because it does NOT copy anything.
    ``world_matrix`` is ``None`` only when the whole chain is untransformed,
    i.e. a classic group whose mesh already sits in world coordinates."""
    m = getattr(group, "xform", None)
    if base is not None:
        m = base if m is None else base * m
    yield group, m
    for child in getattr(group, "children", None) or ():
        yield from iter_placements(child, m)


def _copy_mesh(mesh) -> Mesh:
    from PySide6.QtGui import QMatrix4x4
    return transformed_mesh(mesh, QMatrix4x4())


def _append_mesh(dst, src) -> None:
    """Add every face and loose edge of ``src`` to ``dst`` (positions only —
    the meshes are independent, so nothing aliases)."""
    for f in src.faces:
        nf = dst.add_face([v.position for v in f.loop],
                          [[v.position for v in h] for h in f.hole_loops]
                          or None)
        nf.attrs = dict(f.attrs)
        nf.interior = f.interior
    for e in src.edges:
        if not e.faces:
            dst.add_edge(e.a, e.b)


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
    # Nested placements ride along untranslated: ``delta`` already moved the
    # parent, and a child's transform is relative to it.
    g.children = [copy_group(c) for c in (group.children or ())]
    return g


def _hull_2d(pts):
    """Convex hull of 2D points (monotone chain), counter-clockwise.

    Points strictly inside the quadrilateral of the four axis extremes cannot
    be hull vertices, so they are dropped first (Akl-Toussaint). That test is
    one vectorised pass and typically discards almost everything: the 189k
    vertices of the hedge in piscina.igz come down to a few hundred before the
    Python scan, which is the difference between half a second and a blink."""
    import numpy as np
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) > 64:
        quad = pts[[int(np.argmin(pts[:, 0])), int(np.argmin(pts[:, 1])),
                    int(np.argmax(pts[:, 0])), int(np.argmax(pts[:, 1]))]]
        inside = np.ones(len(pts), dtype=bool)
        for i in range(4):
            a, b = quad[i], quad[(i + 1) % 4]
            side = ((b[0] - a[0]) * (pts[:, 1] - a[1])
                    - (b[1] - a[1]) * (pts[:, 0] - a[0]))
            inside &= side > 1e-12          # strictly left of every edge
        keep = ~inside
        if keep.any():
            pts = pts[keep]
    p = pts[np.lexsort((pts[:, 1], pts[:, 0]))]
    if len(p) < 3:
        return p

    def half(seq):
        out: list = []
        for q in seq:
            while len(out) >= 2:
                a, b = out[-2], out[-1]
                if (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0]) > 0:
                    break
                out.pop()
            out.append(q)
        return out

    lower, upper = half(p), half(p[::-1])
    return np.array(lower[:-1] + upper[:-1])


def frame_from_points(positions) -> tuple:
    """An orthonormal frame for a group, derived from its vertices: the yaw
    about Z whose footprint is tightest, with Z kept upright.

    SketchUp gives every group its own axes and draws the selection box in
    them, so the box hugs the object. Nothing stores those axes here yet (an
    imported group is baked to world coordinates, a classic group never had
    a frame), so they are derived — and derived *exactly*: the minimum-area
    rectangle around a point set always has a side flush with an edge of its
    convex hull, so trying each hull edge finds the true optimum rather than
    guessing at it. The barbecue in piscina.igz sits at 23.5 degrees and needs
    half the footprint the world axes give it.

    Keeping Z upright is the domain's assumption, not a shortcut: buildings,
    walls and furniture stand up, and a box tilted off vertical would read as
    an error even where it wrapped tighter. An earlier attempt derived the
    frame from face geometry instead and picked triangulation DIAGONALS for
    the long axis, which is how a rectangle ends up with a skew frame."""
    import numpy as np
    from PySide6.QtGui import QVector3D
    world = (QVector3D(1.0, 0.0, 0.0), QVector3D(0.0, 1.0, 0.0),
             QVector3D(0.0, 0.0, 1.0))
    if positions is None or len(positions) < 3:
        return world
    hull = _hull_2d(np.asarray(positions, dtype=np.float64)[:, :2])
    if len(hull) < 3:
        return world
    best = None
    for i in range(len(hull)):
        d = hull[(i + 1) % len(hull)] - hull[i]
        length = float(np.hypot(d[0], d[1]))
        if length < 1e-12:
            continue
        u = d / length
        v = np.array([-u[1], u[0]])
        a, b = hull @ u, hull @ v
        area = float((a.max() - a.min()) * (b.max() - b.min()))
        if best is None or area < best[0]:
            best = (area, u)
    if best is None:
        return world
    u = best[1]
    return (QVector3D(float(u[0]), float(u[1]), 0.0),
            QVector3D(float(-u[1]), float(u[0]), 0.0),
            QVector3D(0.0, 0.0, 1.0))


def placement_points(group):
    """Every vertex position of ``group`` and its nested placements, in WORLD
    space, as an ``(N, 3)`` float64 array.

    A bounding box only ever needed the POINTS, but the only way to get them
    used to be ``world_mesh`` — which welds a merged copy of the whole
    component to answer a question about eight corners. On the hedge that was
    23 s per selection once its geometry moved into nested placements (5 s
    before, already the wrong shape of work). Here each prototype's array is
    built ONCE and every placement is one matrix multiply over it."""
    import numpy as np
    out: list = []
    cache: dict = {}
    for g, m in iter_placements(group):
        verts = g.mesh.vertices
        if not verts:
            continue
        arr = cache.get(id(g.mesh))
        if arr is None:
            arr = cache[id(g.mesh)] = np.array(
                [[v.position.x(), v.position.y(), v.position.z()]
                 for v in verts], dtype=np.float64)
        if m is not None:
            d = m.data()                      # column-major
            rot = np.array([[d[0], d[4], d[8]],
                            [d[1], d[5], d[9]],
                            [d[2], d[6], d[10]]])
            arr = arr @ rot.T + np.array([d[12], d[13], d[14]])
        out.append(arr)
    return np.concatenate(out) if out else np.empty((0, 3))


def oriented_bounds(mesh, frame=None, points=None) -> tuple:
    """``(frame, lo, hi)`` — the mesh's extent along ``frame``'s axes (derived
    with :func:`local_frame` when not given). ``lo``/``hi`` are the min/max
    coordinates in that frame, so the box corners are
    ``sum(axis * c for axis, c in zip(frame, corner))``.

    ``points`` short-circuits the mesh: an ``(N, 3)`` world-space array from
    :func:`placement_points`, so a component with nested placements is not
    merged into one mesh just to be measured."""
    import numpy as np
    from PySide6.QtGui import QVector3D
    if frame is None:
        frame = (QVector3D(1.0, 0.0, 0.0), QVector3D(0.0, 1.0, 0.0),
                 QVector3D(0.0, 0.0, 1.0))
    if points is not None:
        if len(points) == 0:
            return frame, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        pos = points
    else:
        verts = mesh.vertices
        if not verts:
            return frame, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        pos = np.array([[v.position.x(), v.position.y(), v.position.z()]
                        for v in verts], dtype=np.float64)
    axes = np.array([[a.x(), a.y(), a.z()] for a in frame], dtype=np.float64)
    proj = pos @ axes.T
    return frame, tuple(proj.min(axis=0)), tuple(proj.max(axis=0))


def oriented_box_corners(frame, lo, hi) -> list:
    """The eight corners of an oriented box, in world coordinates."""
    from PySide6.QtGui import QVector3D
    u, v, w = frame
    out = []
    for i in range(8):
        out.append(u * (hi[0] if i & 1 else lo[0])
                   + v * (hi[1] if i & 2 else lo[1])
                   + w * (hi[2] if i & 4 else lo[2]))
    return [QVector3D(p) for p in out]
