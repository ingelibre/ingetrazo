# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Rotate tool (Q): turn geometry with SketchUp's protractor.

The instrument is the shared :class:`~tools.protractor.ProtractorBase` —
Rotate shows the same protractor as the Protractor tool (SketchUp,
help.sketchup.com "Flipping, Mirroring, Rotating and Arrays"):

- Before the centre click the disc follows the cursor, aligned to the face
  underneath and coloured by the rotation axis (red/green/blue on axis
  planes); arrow keys lock the plane, Shift freezes it.
- CLICK-DRAG from the centre sets a custom rotation axis along the drag
  (SketchUp's fold-along-a-line gesture); a plain click keeps the inferred
  plane.
- Second click sets the reference arm; the geometry swings live with the
  cursor, snapping to the 15° ticks near the disc and free at 0.1° farther
  out. A third click commits; typing degrees or a rise:run slope commits
  exactly (sign follows the current drag direction).
- Tapping Ctrl toggles COPY mode: the original stays put and a rotated copy
  is created (a component instance copies as a sibling instance). The copy's
  wireframe previews at the cursor angle.
- After the commit the angle stays hot: typing a value + Enter redoes the
  rotation at the new angle, until the next click or tool change.
- Esc cancels and puts the geometry back.

Rotation is rigid on the rotated set, but rotating a subset of a connected
model can warp attached faces — the command autofolds them, same as Move.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.group import Group, copy_group, transformed_attrs
from core.history import (
    AddEdgeCommand,
    AddFaceCommand,
    CompoundCommand,
    InsertGroupCommand,
    RotateGroupCommand,
    RotateVerticesCommand,
    rotation_matrix,
)
from core.i18n import tr
from core.mesh import Edge, Face, Mesh
from core.triangulate import plane_axes
from tools.base import ToolContext
from tools.move import gather_targets
from tools.protractor import ProtractorBase


class RotateTool(ProtractorBase):
    name = "Rotate"
    shortcut = "Q"
    vcb_label = "Angle"
    accepts_angle_ratio = True  # VCB "3:12" (rise:run) arrives as degrees

    def __init__(self) -> None:
        super().__init__()
        self._groups: list[Group] = []
        self._splanes: list = []               # section planes being rotated
        self._positions: list[QVector3D] = []
        self._verts: list = []
        self._sel_faces: list = []          # for copy mode (loose geometry)
        self._sel_edges: list = []
        self._base_segments: list = []      # wireframe for the copy preview
        self._preview_deg = 0.0
        self._copy = False                  # Ctrl: rotate a COPY
        self._axis_drag_armed = False       # centre press → release watches
        self._last: dict | None = None      # hot retype of the last rotation

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()
        self._copy = False
        self._last = None

    def on_deactivate(self, viewport) -> None:
        self._revert_preview(viewport)
        self._reset()
        self._copy = False
        self._last = None
        self._axis_pick = None
        self.hover_point = None

    # ---- Keyboard -----------------------------------------------------------
    def on_key(self, viewport, key: int, modifiers) -> bool:
        # Ctrl toggles copy mode (SketchUp: rotate a copy, original stays).
        if key == Qt.Key_Control:
            self._copy = not self._copy
            if self._copy:
                self._revert_preview(viewport)  # the original stops swinging
                viewport.flash_status(tr("Rotate a copy: on"))
            else:
                viewport.flash_status(tr("Rotate a copy: off"))
            viewport.update()
            return True
        return super().on_key(viewport, key, modifiers)

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        self._last = None            # a click ends the retype window
        if self.start_point is None:
            groups, positions = gather_targets(ctx)
            from core.section import SectionPlane
            splanes = [p for p in viewport.scene.selection
                       if isinstance(p, SectionPlane)]
            if not splanes and not viewport.scene.selection:
                # SketchUp: Rotate grabs a section plane directly by its
                # frame, no pre-selection needed.
                pick = getattr(viewport, "pick_section_plane", None)
                sp = (pick(ctx.screen.x(), ctx.screen.y())
                      if pick is not None else None)
                if sp is not None:
                    splanes = [sp]
                    groups, positions = [], []
            if not groups and not positions and not splanes:
                viewport.flash_status(
                    tr("Select (or click) the geometry to rotate first"))
                return
            self._groups = groups
            self._splanes = splanes
            self._positions = positions
            mesh = viewport.scene.mesh
            self._verts = [v for v in (mesh.vertex_at(p) for p in positions)
                           if v is not None]
            self._gather_copy_entities(ctx)
            self.start_point = ctx.world
            self._axis_drag_armed = True   # a DRAG from here sets the axis
            return
        if self.ref_point is None:
            if (ctx.world - self.start_point).length() < 1e-6:
                return
            self.ref_point = ctx.world
            return
        deg = self._display_deg(ctx.world)
        if deg is not None:
            self._commit(viewport, deg)

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        self._infer_plane(ctx)
        self._update_screen_metrics(ctx)
        if self.ref_point is not None and not self._copy:
            deg = self._display_deg(ctx.world)
            if deg is not None:
                self._apply_preview(ctx.viewport, deg)
        ctx.viewport.update()

    def on_release(self, viewport) -> None:
        """A real DRAG from the centre fixes the rotation axis along it
        (SketchUp's fold gesture); a plain click keeps the inferred plane."""
        if not self._axis_drag_armed:
            return
        self._axis_drag_armed = False
        if self.hover_point is None or self.start_point is None:
            return
        w2p = getattr(viewport, "_world_to_pixel", None)
        dragged = False
        if w2p is not None:
            p0 = w2p(self.start_point)
            p1 = w2p(self.hover_point)
            if p0 is not None and p1 is not None:
                dragged = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) > 8.0
        if not dragged:
            return
        d = self.hover_point - self.start_point
        if d.length() < 1e-9:
            return
        self._custom_axis = d.normalized()
        viewport.flash_status(tr("Rotation axis set along the drag"))
        viewport.update()

    def on_value(self, viewport, value) -> bool:
        if isinstance(value, tuple):
            return False
        if self.ref_point is not None:
            # The typed angle turns the way the user is currently dragging.
            sign = -1.0 if self._preview_deg < 0 else 1.0
            if self._copy and self.hover_point is not None:
                cur = self._angle_to(self.hover_point)
                sign = -1.0 if (cur is not None and cur < 0) else 1.0
            self._commit(viewport, sign * abs(value))
            return True
        if self._last is not None:
            # Hot retype (SketchUp): redo the rotation just made at the new
            # angle. A typed negative flips the side.
            last = self._last
            stack = getattr(viewport.history, "undo_stack", None)
            if not stack or stack[-1] is not last["cmd"]:
                self._last = None
                return False
            side = last["sign"] * (1.0 if value >= 0 else -1.0)
            deg = side * abs(value)
            viewport.history.undo()
            cmd = last["build"](deg)
            if cmd is None:
                self._last = None
                return False
            viewport.history.execute(cmd)
            last["cmd"] = cmd
            viewport.update()
            return True
        return False

    def on_cancel(self, viewport) -> None:
        self._revert_preview(viewport)
        self._reset()
        self._last = None
        viewport.update()

    # ---- Visual preview -----------------------------------------------------
    def rubber_band_lines(self):
        centre = (self.start_point if self.start_point is not None
                  else self.hover_point)
        if centre is None:
            return []
        segments = list(self._protractor_disc(centre))
        if self.start_point is None or self.hover_point is None:
            return segments
        segments.append((self.start_point, self.hover_point))
        if self.ref_point is not None:
            segments.append((self.start_point, self.ref_point))
            deg = self._display_deg(self.hover_point)
            if deg is not None:
                segments.extend(self._arc_segments(deg))
                if self._copy and self._base_segments:
                    # Copy mode: the original stays put — preview the rotated
                    # COPY as a wireframe at the cursor angle.
                    m = rotation_matrix(self.start_point, self._axis(), deg)
                    segments.extend(
                        (m.map(a), m.map(b)) for a, b in self._base_segments)
        return segments

    def _arc_segments(self, deg: float):
        """Protractor arc between the two arms, at the reference radius."""
        u, v = plane_axes(self._axis())
        a = self.ref_point - self.start_point
        r = a.length() * 0.75
        a0 = math.atan2(QVector3D.dotProduct(a, v), QVector3D.dotProduct(a, u))
        steps = max(2, int(abs(deg) // 10) + 1)
        pts = []
        for k in range(steps + 1):
            t = a0 + math.radians(deg) * k / steps
            pts.append(self.start_point + (u * math.cos(t) + v * math.sin(t)) * r)
        return list(zip(pts, pts[1:]))

    def value_label(self):
        if self.ref_point is None or self.hover_point is None:
            return None
        deg = self._display_deg(self.hover_point)
        if deg is None:
            return None
        return (f"{deg:+.1f}°", self.hover_point)

    def vcb_caption(self) -> str:
        return "Angle"

    # ---- Internals ----------------------------------------------------------
    def _gather_copy_entities(self, ctx: ToolContext) -> None:
        """The faces/edges copy mode duplicates, and the wireframe segments
        the copy preview swings (group wireframe, or the loose selection)."""
        viewport = ctx.viewport
        self._sel_faces, self._sel_edges, self._base_segments = [], [], []
        for group in self._groups:
            xf = getattr(group, "xform", None)
            for e in group.mesh.edges:
                a, b = QVector3D(e.a), QVector3D(e.b)
                if xf is not None:
                    a, b = xf.map(a), xf.map(b)
                self._base_segments.append((a, b))
        sel = list(viewport.scene.selection)
        if not sel and not self._groups:
            # Nothing selected and no group hover-picked: the click grabbed
            # the loose entity under the cursor (mirror of gather_targets).
            edge = viewport.pick_edge(ctx.screen.x(), ctx.screen.y())
            if edge is not None:
                sel = [edge]
            else:
                face = viewport.pick_face(ctx.screen.x(), ctx.screen.y())
                if face is not None:
                    sel = [face]
        self._sel_faces = [f for f in sel if isinstance(f, Face)]
        self._sel_edges = [e for e in sel if isinstance(e, Edge)]
        for f in self._sel_faces:
            for lp in (list(f.vertices), *[list(h) for h in f.holes]):
                n = len(lp)
                for i in range(n):
                    self._base_segments.append(
                        (QVector3D(lp[i]), QVector3D(lp[(i + 1) % n])))
        for e in self._sel_edges:
            self._base_segments.append((QVector3D(e.a), QVector3D(e.b)))

    def _rotate_live(self, viewport, step_deg: float) -> None:
        if abs(step_deg) < 1e-12:
            return
        m = rotation_matrix(self.start_point, self._axis(), step_deg)
        for group in self._groups:
            if getattr(group, "xform", None) is not None:
                group.xform = m * group.xform   # instance: O(1)
            else:
                gmesh = group.mesh
                for vx in list(gmesh.vertices):
                    gmesh.move_vertex(vx, m.map(vx.position) - vx.position)
        for vx in self._verts:
            viewport.scene.mesh.move_vertex(
                vx, m.map(vx.position) - vx.position)
        for sp in self._splanes:
            sp.point = m.map(sp.point)
            n2 = m.mapVector(sp.normal)
            if n2.length() > 1e-12:
                sp.normal = n2.normalized()
        viewport.scene.version += 1

    def _apply_preview(self, viewport, target_deg: float) -> None:
        self._rotate_live(viewport, target_deg - self._preview_deg)
        self._preview_deg = target_deg

    def _revert_preview(self, viewport) -> None:
        if abs(self._preview_deg) > 1e-12:
            self._rotate_live(viewport, -self._preview_deg)
            self._preview_deg = 0.0

    def _make_builder(self):
        """A closure that builds the commit command for a given angle — kept
        by the hot-retype window so the rotation can be redone at a new angle
        after the tool has reset."""
        start = QVector3D(self.start_point)
        axis = QVector3D(self._axis())
        copy = self._copy
        groups = list(self._groups)
        splanes = list(self._splanes)
        positions = list(self._positions)
        faces = list(self._sel_faces)
        edges = list(self._sel_edges)

        def build(deg: float):
            cmds: list = []
            if copy:
                m = rotation_matrix(start, axis, deg)
                for group in groups:
                    g = copy_group(group)   # instance → sibling instance
                    cmds.append(InsertGroupCommand(g))
                    cmds.append(RotateGroupCommand(g, start, axis, deg))
                for f in faces:
                    cmds.append(AddFaceCommand(
                        [m.map(v) for v in f.vertices],
                        holes=[[m.map(v) for v in h] for h in f.holes] or None,
                        auto=False,
                        attrs=transformed_attrs(f.attrs, m),
                    ))
                id_map: dict[int, int] = {}
                for e in edges:
                    curve = getattr(e, "curve", None)
                    if curve is not None and curve not in id_map:
                        id_map[curve] = Mesh.next_curve_id()
                    cmds.append(AddEdgeCommand(
                        m.map(e.a), m.map(e.b),
                        soft=getattr(e, "soft", False) or None,
                        curve=id_map.get(curve)))
            else:
                cmds.extend(RotateGroupCommand(g, start, axis, deg)
                            for g in groups)
                if positions:
                    cmds.append(RotateVerticesCommand(
                        positions, start, axis, deg))
                if splanes:
                    from core.history import RotateSectionPlanesCommand
                    cmds.append(RotateSectionPlanesCommand(
                        splanes, start, axis, deg))
            if not cmds:
                return None
            return cmds[0] if len(cmds) == 1 else CompoundCommand(cmds)

        return build

    def _commit(self, viewport, deg: float) -> None:
        self._revert_preview(viewport)
        if abs(deg) > 1e-9:
            build = self._make_builder()
            cmd = build(deg)
            if cmd is not None:
                viewport.history.execute(cmd)
                # SketchUp: the angle stays hot — typing a value + Enter
                # redoes this rotation until the next click or tool change.
                self._last = {"cmd": cmd, "build": build,
                              "sign": -1.0 if deg < 0 else 1.0}
        self._reset()
        viewport.update()

    def _reset(self) -> None:
        self._reset_protractor()
        self._groups = []
        self._splanes = []
        self._positions = []
        self._verts = []
        self._sel_faces = []
        self._sel_edges = []
        self._base_segments = []
        self._preview_deg = 0.0
        self._axis_drag_armed = False
        self._copy = False      # the Ctrl modifier arms ONE operation
