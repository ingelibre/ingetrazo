# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Resize by measuring: the Tape Measure's «resize the model» and «resize
the active group or component».

Measure between two points with the Tape Measure, then type the length that
distance should have: everything in the open context scales uniformly by
``wanted / measured``, so the two points end up exactly that far apart. It
is how a plan imported at the wrong scale, or a sketch traced over a photo,
is brought to its real size from one dimension you know.

- **Inside a group or component** its content scales about the context's
  own origin (its axes), so it grows or shrinks in place. Inside a
  component instance the session edits a world copy of the shared
  definition (``Scene.begin_group_edit``): leaving shares the resize back,
  and every copy of the component takes it — as any edit inside it does.
- **At the top level** the whole model scales about the world origin: the
  loose geometry, every group and component, reference images, guides,
  section planes, dimensions and leader texts. A component loaded from an
  external file (``Group.source``: inserted from a document, or from the
  component library) keeps its size — it only moves with the model — the
  way a chair placed in a plan keeps its real size when the plan is
  rescaled. Georeferenced data (terrain, traced paths, survey points) is
  real-world reference and is left alone too.

Undo restores what was captured before; redo restores what was captured
after, so nothing drifts however many times the two alternate.
"""
from __future__ import annotations

from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import _remap_uvws, carry_axes, group_frame, iter_placements
from core.history import Command, scale_matrix
from core.mesh import _key

#: A factor this close to 1 changes nothing worth an undo step.
_SAME = 1e-9


def resize_factor(measured: float, wanted: float) -> float | None:
    """The uniform factor that turns ``measured`` into ``wanted``, or
    ``None`` when either is not a usable length (zero, negative)."""
    try:
        measured, wanted = float(measured), float(wanted)
    except (TypeError, ValueError):
        return None
    if measured <= 1e-12 or wanted <= 1e-12:
        return None
    return wanted / measured


def resize_anchor(scene) -> QVector3D:
    """The fixed point of a resize in the open context: the world origin
    at the top level, the open group's own origin inside one. A classic
    group that never had axes of its own sits on the world's, whose origin
    can be far away — scaling about it would carry the group off across
    the model — so it takes the lowest corner of its content, the corner
    Make Component puts a new component's origin at."""
    if scene.edit_group is None:
        return QVector3D(0.0, 0.0, 0.0)
    frame = scene.drawing_frame
    if frame is not None:
        return frame.map(QVector3D(0.0, 0.0, 0.0))
    lo = _lowest_corner(scene.edit_group)
    return lo if lo is not None else QVector3D(0.0, 0.0, 0.0)


def _lowest_corner(group) -> QVector3D | None:
    """Min corner of everything ``group`` draws, in world coordinates."""
    lo = None
    for pg, m in iter_placements(group):
        for v in pg.mesh.vertices:
            p = m.map(v.position) if m is not None else v.position
            lo = (QVector3D(p) if lo is None else
                  QVector3D(min(lo.x(), p.x()), min(lo.y(), p.y()),
                            min(lo.z(), p.z())))
    return lo


def keeps_size(group) -> bool:
    """Whether a model resize only MOVES ``group``: a component loaded
    from an external file."""
    return bool(getattr(group, "source", None))


def _handle(group) -> QVector3D:
    """The point that says where ``group`` stands — what a model resize
    carries along when the group keeps its size: an instance's origin,
    a classic group's own axes origin, else the centre of its base."""
    frame = group_frame(group)
    if frame is not None:
        return frame.map(QVector3D(0.0, 0.0, 0.0))
    lo = hi = None
    for pg, m in iter_placements(group):
        for v in pg.mesh.vertices:
            p = m.map(v.position) if m is not None else v.position
            if lo is None:
                lo, hi = QVector3D(p), QVector3D(p)
                continue
            lo = QVector3D(min(lo.x(), p.x()), min(lo.y(), p.y()),
                           min(lo.z(), p.z()))
            hi = QVector3D(max(hi.x(), p.x()), max(hi.y(), p.y()),
                           max(hi.z(), p.z()))
    if lo is None:
        return QVector3D(0.0, 0.0, 0.0)
    return QVector3D((lo.x() + hi.x()) * 0.5, (lo.y() + hi.y()) * 0.5, lo.z())


def transform_mesh(mesh, m: QMatrix4x4) -> None:
    """Map every vertex of ``mesh`` through ``m`` at once, textures along.

    Moving the vertices one at a time is not safe for a scale: a vertex
    can land on the very spot a neighbour has not left yet, and the
    position registry then loses one of the two (``Mesh.move_vertex``
    does not merge). Here the new positions are written together and the
    registry is rebuilt from them, through the identity-preserving
    snapshot every command already relies on."""
    snap = mesh.capture_state()
    vpos = {v: m.map(p) for v, p in snap["vpos"].items()}
    registry: dict = {}
    for v in snap["vertices"]:
        registry.setdefault(_key(vpos[v]), v)
    snap["vpos"] = vpos
    snap["registry"] = registry
    mesh.restore_state(snap)
    _remap_uvws(mesh, m)


def _translation(delta: QVector3D) -> QMatrix4x4:
    t = QMatrix4x4()
    t.translate(delta)
    return t


class ResizeCommand(Command):
    """Scale the open context uniformly by ``factor`` about its
    :func:`resize_anchor` — the whole model at the top level, the content
    of the open group or component inside one. One undo step."""

    def __init__(self, scene, factor: float,
                 anchor: QVector3D | None = None) -> None:
        self.factor = float(factor)
        self.anchor = (QVector3D(anchor) if anchor is not None
                       else resize_anchor(scene))
        self.model = scene.edit_group is None
        # Read now: the context is the one the user measured in.
        self._mesh = scene.mesh
        self._groups = (list(scene.groups) if self.model else
                        list(getattr(scene.edit_group, "children", None) or ()))
        self._before: dict | None = None
        self._after: dict | None = None

    @property
    def matrix(self) -> QMatrix4x4:
        return scale_matrix(self.anchor, self.factor)

    # ---- Command ------------------------------------------------------------
    def do(self, scene) -> None:
        if self._after is not None:            # redo
            self._restore(self._after)
            scene.version += 1
            return
        self._before = self._capture(scene)
        self._apply(scene)
        self._after = self._capture(scene)
        scene.version += 1

    def undo(self, scene) -> None:
        if self._before is not None:
            self._restore(self._before)
            scene.version += 1

    # ---- The resize ---------------------------------------------------------
    def _apply(self, scene) -> None:
        m = self.matrix
        transform_mesh(self._mesh, m)
        for g in self._groups:
            if self.model and keeps_size(g):
                here = _handle(g)
                self._transform_group(g, _translation(m.map(here) - here))
            else:
                self._transform_group(g, m)
        if not self.model:
            return
        for im in scene.image_planes:
            im.origin = m.map(im.origin)
            im.u = m.mapVector(im.u)
            im.v = m.mapVector(im.v)
        for gd in scene.guides:
            gd.point = m.map(gd.point)
            if gd.origin is not None:
                gd.origin = m.map(gd.origin)
        for sp in scene.section_planes:
            sp.point = m.map(sp.point)
        for d in scene.dimensions:
            # An end held by a vertex follows it; a free end is moved here.
            # Reading ``a``/``b`` returns the live position either way.
            a, b = d.a, d.b
            if d.anchor_a is None:
                d.a = m.map(a)
            if d.anchor_b is None:
                d.b = m.map(b)
            d.offset = m.mapVector(d.offset)
        for t in scene.text_labels:
            t.anchor = m.map(t.anchor)
            t.offset = m.mapVector(t.offset)

    @staticmethod
    def _transform_group(group, m: QMatrix4x4) -> None:
        if group.xform is not None:
            group.xform = m * group.xform
            return
        transform_mesh(group.mesh, m)
        carry_axes(group, m)                    # the origin moves with it (#44)

    # ---- Snapshots ----------------------------------------------------------
    def _capture(self, scene) -> dict:
        state = {
            "mesh": self._mesh.capture_state(),
            "groups": [
                (g,
                 QMatrix4x4(g.xform) if g.xform is not None else None,
                 g.mesh.capture_state() if g.xform is None else None,
                 QMatrix4x4(g.axes) if g.axes is not None else None)
                for g in self._groups],
        }
        if self.model:
            state["images"] = [(im, QVector3D(im.origin), QVector3D(im.u),
                                QVector3D(im.v)) for im in scene.image_planes]
            state["guides"] = [
                (gd, QVector3D(gd.point),
                 QVector3D(gd.origin) if gd.origin is not None else None)
                for gd in scene.guides]
            state["sections"] = [(sp, QVector3D(sp.point))
                                 for sp in scene.section_planes]
            state["dimensions"] = [(d, QVector3D(d.a), QVector3D(d.b),
                                    QVector3D(d.offset))
                                   for d in scene.dimensions]
            state["labels"] = [(t, QVector3D(t.anchor), QVector3D(t.offset))
                               for t in scene.text_labels]
        return state

    def _restore(self, state: dict) -> None:
        self._mesh.restore_state(state["mesh"])
        for g, xform, mesh_state, axes in state["groups"]:
            if xform is not None:
                g.xform = QMatrix4x4(xform)
            elif mesh_state is not None:
                g.mesh.restore_state(mesh_state)
            g.axes = QMatrix4x4(axes) if axes is not None else None
        for im, o, u, v in state.get("images", ()):
            im.origin, im.u, im.v = QVector3D(o), QVector3D(u), QVector3D(v)
        for gd, p, o in state.get("guides", ()):
            gd.point = QVector3D(p)
            gd.origin = QVector3D(o) if o is not None else None
        for sp, p in state.get("sections", ()):
            sp.point = QVector3D(p)
        # Dimensions last: a held end reads its vertex, which the mesh
        # restore above has already put back.
        for d, a, b, off in state.get("dimensions", ()):
            d.a, d.b, d.offset = QVector3D(a), QVector3D(b), QVector3D(off)
        for t, a, off in state.get("labels", ()):
            t.anchor, t.offset = QVector3D(a), QVector3D(off)
