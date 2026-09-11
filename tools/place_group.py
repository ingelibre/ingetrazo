# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Place-component tool: a freshly built Group follows the cursor and a click
drops it — SketchUp's component-placement feel.

The group is anchored at the CENTRE OF ITS BASE (bbox bottom), so by default
it *tries* to sit on the ground plane: hovering empty ground lands the base
at z=0 (the viewport's work plane), hovering a slab lands it on the slab —
guidance, not a constraint (any snap target wins). Esc discards the pending
component without inserting anything.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import InsertGroupCommand
from tools.base import Tool, ToolContext

#: Preview segments are plenty for the bundled starters; a hard cap keeps a
#: huge future component from turning the hover into a slideshow.
_MAX_PREVIEW_EDGES = 2000


class PlaceGroupTool(Tool):
    name = "Place component"
    uses_snap = True
    wireframe_color = (0.13, 0.17, 0.23, 1.0)
    wireframe_depth_tested = False      # the pending component floats on top

    def __init__(self, group, align_to_face: bool = False,
                 anchor: QVector3D | None = None) -> None:
        self._group = group
        # A component INSTANCE (a matrix, children or both — an imported
        # document arrives as one) is placed by composing its matrix; its
        # prototype mesh, shared with every copy, never moves. A classic
        # group is placed by moving its vertices, as always.
        self._instance = getattr(group, "xform", None) is not None
        # What the cursor holds: the centre of the base by default (a
        # starter settles on the ground), or a point the caller names — an
        # imported document hangs from its own origin, like SketchUp's
        # component axes, so the footings its author drew below grade stay
        # below grade instead of being lifted onto the ground.
        self._anchor = (QVector3D(anchor) if anchor is not None
                        else self._base_center(group))
        self._offset = QVector3D(0.0, 0.0, 0.0)
        # SketchUp's 3D-text glue: when enabled, hovering a FACE re-orients
        # the group so its front (-Y) points along the face normal — a sign
        # on a wall, text lying on a slab. No face → upright on the ground.
        self._align = align_to_face
        self._face_normal: QVector3D | None = None
        # Local preview segments, relative to the anchor (computed once).
        # A container's own mesh is usually empty and its children can be
        # anything: the box of the whole placement is the honest preview.
        self._segments = ([] if getattr(group, "children", None) else [
            (QVector3D(e.a) - self._anchor, QVector3D(e.b) - self._anchor)
            for e in group.mesh.edges[:_MAX_PREVIEW_EDGES]
        ])
        if not self._segments:
            self._segments = self._bbox_segments(group)

    @staticmethod
    def _world_points(group):
        """Every vertex of the group AND its nested placements, in world
        space — what a container's extent is made of."""
        from core.group import placement_points
        return placement_points(group)

    def _bbox_segments(self, group):
        """Wireframe box fallback: meshes without edges (billboards) and
        containers (their geometry lives in the children)."""
        pts = self._world_points(group)
        if not len(pts):
            return []
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        a = QVector3D(float(lo[0]), float(lo[1]), float(lo[2])) - self._anchor
        b = QVector3D(float(hi[0]), float(hi[1]), float(hi[2])) - self._anchor
        c = [QVector3D(x, y, z)
             for z in (a.z(), b.z()) for y in (a.y(), b.y())
             for x in (a.x(), b.x())]
        idx = [(0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6),
               (6, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
        return [(c[i], c[j]) for i, j in idx]

    @classmethod
    def _base_center(cls, group) -> QVector3D:
        pts = cls._world_points(group)
        if not len(pts):
            return QVector3D(0.0, 0.0, 0.0)
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        return QVector3D(float(lo[0] + hi[0]) / 2.0,
                         float(lo[1] + hi[1]) / 2.0,
                         float(lo[2]))

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        pass

    def on_deactivate(self, viewport) -> None:
        self._group = None

    # ---- Face alignment (3D text) --------------------------------------------
    @staticmethod
    def _face_frame(normal: QVector3D):
        """Orthonormal frame turning the group's local axes onto a face:
        local -Y (its front) → the face normal, keeping the text's up
        world-up on walls and world-north when lying on a horizontal face.
        Returns ``(right, y_axis, up)`` = images of local +X, +Y, +Z."""
        n = QVector3D(normal).normalized()
        hint = (QVector3D(0.0, 1.0, 0.0) if abs(n.z()) > 0.99
                else QVector3D(0.0, 0.0, 1.0))
        right = QVector3D.crossProduct(hint, n)
        if right.length() < 1e-9:
            right = QVector3D(1.0, 0.0, 0.0)
        right = right.normalized()
        up = QVector3D.crossProduct(n, right).normalized()
        return right, -n, up

    def _rotate(self, p: QVector3D) -> QVector3D:
        if self._face_normal is None:
            return QVector3D(p)
        right, y_axis, up = self._face_frame(self._face_normal)
        return right * p.x() + y_axis * p.y() + up * p.z()

    def _pose_matrix(self, shift: QVector3D):
        """The move just applied, as one matrix: the alignment turn followed
        by ``shift`` — what :func:`core.group._remap_uvws` needs."""
        from PySide6.QtGui import QMatrix4x4
        m = QMatrix4x4()
        m.translate(shift)
        if self._face_normal is not None:
            r, y, u = self._face_frame(self._face_normal)
            m = m * QMatrix4x4(r.x(), y.x(), u.x(), 0.0,
                               r.y(), y.y(), u.y(), 0.0,
                               r.z(), y.z(), u.z(), 0.0,
                               0.0, 0.0, 0.0, 1.0)
        return m

    def _update_alignment(self, ctx: ToolContext) -> None:
        if not self._align:
            return
        try:
            hit = ctx.viewport.pick_face_any(ctx.screen.x(), ctx.screen.y())
        except Exception:
            hit = None
        face = hit[0] if isinstance(hit, tuple) else hit
        self._face_normal = face.normal() if face is not None else None

    # ---- Spatial input ------------------------------------------------------
    def on_hover(self, ctx: ToolContext) -> None:
        if self._group is None:
            return
        self._update_alignment(ctx)
        self._offset = ctx.world - self._rotate(self._anchor)
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        if self._group is None:
            return
        self._update_alignment(ctx)
        shift = ctx.world - self._rotate(self._anchor)
        if self._instance:
            # The pose composes into the matrix: the prototype (and every
            # nested placement under it) stays put in its own frame.
            self._group.xform = self._pose_matrix(shift) * self._group.xform
        else:
            # Re-pose the group's isolated mesh BEFORE it enters the scene
            # (registry-safe per-vertex move; undo of the insert removes
            # the whole group, so no separate move step lands in history).
            for v in list(self._group.mesh.vertices):
                target = self._rotate(v.position) + shift
                delta = target - v.position
                if delta.length() > 1e-9:
                    self._group.mesh.move_vertex(v, delta)
            # A texture that came with its own coordinates is anchored to
            # world position, so the map has to travel with the geometry —
            # otherwise the image stays where the component was built and
            # the piece arrives wearing whatever happens to fall on it.
            from core.group import _remap_uvws
            _remap_uvws(self._group.mesh, self._pose_matrix(shift))
        group = self._group
        self._group = None
        ctx.viewport.history.execute(InsertGroupCommand(group))
        ctx.viewport.flash_status(self._placed_message())
        window = ctx.viewport.window()
        if hasattr(window, "_activate_tool"):
            window._activate_tool("select")
        ctx.viewport.update()

    @staticmethod
    def _placed_message() -> str:
        from core.i18n import tr
        return tr("Component placed — Move (M) adjusts it")

    def on_cancel(self, viewport) -> None:
        self._group = None
        viewport.update()

    # ---- Visual preview -----------------------------------------------------
    def rubber_band_lines(self):
        if self._group is None:
            return []
        off = self._offset
        if self._face_normal is not None:
            return [(self._rotate(a + self._anchor) + off,
                     self._rotate(b + self._anchor) + off)
                    for a, b in self._segments]
        return [(a + self._anchor + off, b + self._anchor + off)
                for a, b in self._segments]
