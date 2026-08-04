# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""GeoPath tool: trace a terrain/road path over the base map (Track G).

Draws with the familiar SketchUp feel — click nodes, rubber-band preview, type a
segment length in the VCB — but the result is a :class:`~georef.geopath.GeoPath`
in ``scene.geo_paths``, **never** mesh geometry. It stays on the Z=0 ground
plane (the flat base map); the modelling topology engine is untouched.

Finish a path with double-click or Enter (open), or by clicking back on the
first node (closed loop, e.g. a boundary). Esc discards the in-progress path.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.history import AddGeoPathCommand, MoveGeoPathNodeCommand
from core.i18n import tr
from georef.geopath import GeoPath
from tools.base import Tool, ToolContext

_CLOSE_PX = 10  # click within this of the first node closes the loop
_NODE_PX = 9    # grab an existing node within this pixel radius


class GeoPathTool(Tool):
    name = "Path"
    shortcut = "Y"   # T went to Tape Measure (SketchUp's key for it)
    vcb_label = "Length"
    uses_snap = False  # a georef trace snaps to nothing in the modelling mesh

    def __init__(self) -> None:
        self.nodes: list[QVector3D] = []
        self.hover_point: QVector3D | None = None
        # Ground elevation under the cursor — the live readout. Cheap enough to
        # take on every hover (the survey index answers in ~20 µs).
        self.hover_elevation: float | None = None
        self._start_elevation: float | None = None
        self._saved_view = None    # camera state to put back on deactivate
        # Fixed Z=0 ground plane — the base map. The viewport reads this so
        # every click lands flat on the imagery regardless of camera tilt.
        self.work_plane = (QVector3D(0.0, 0.0, 0.0), QVector3D(0.0, 0.0, 1.0))
        # Node editing (Google-Earth style): grab an existing node, drag, drop.
        self._drag = None          # (GeoPath, index) while editing a node
        self._orig = None          # its original position, for revert

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()
        self._enter_plan_view(viewport)

    def on_deactivate(self, viewport) -> None:
        if self._drag is not None:
            self._revert_drag(viewport)
        self._reset()
        self.hover_point = None
        self.hover_elevation = None
        viewport._hover_geo_node = None
        self._restore_view(viewport)

    # ---- Plan view ----------------------------------------------------------
    # An alignment is a plan decision, and only top + parallel makes the click
    # land where the cursor is: with relief under the cursor, ANY tilt or
    # perspective puts the visible ground and its Z=0 plan position in
    # different screen places, so you would trace a ridge and get a line
    # metres away from it. Top parallel has zero parallax — the screen IS the
    # plan. Saved and restored, because hijacking the camera for good would be
    # its own kind of rude.

    def _enter_plan_view(self, viewport) -> None:
        if not viewport.has_ground_surface():
            return                      # nothing to trace over: leave the view alone
        camera = viewport.camera
        self._saved_view = (camera.perspective, camera.yaw, camera.pitch)
        camera.perspective = False
        camera.set_view("top")
        viewport.flash_status(tr(
            "Top view, parallel — so the trace lands where you click. "
            "Restored when you leave the tool."))
        viewport.update()

    def _restore_view(self, viewport) -> None:
        if self._saved_view is None:
            return
        perspective, yaw, pitch = self._saved_view
        self._saved_view = None
        camera = viewport.camera
        camera.perspective = perspective
        camera.yaw, camera.pitch = yaw, pitch
        viewport.update()

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        # Dropping a dragged node.
        if self._drag is not None:
            self._commit_node_move(ctx.viewport)
            return
        # Idle (not mid-draw): a click on an existing node grabs it to edit;
        # a click on empty ground starts a new path.
        if not self.nodes:
            hit = self._pick_node(ctx)
            if hit is not None:
                self._drag = hit
                self._orig = QVector3D(hit[0].points[hit[1]])
                return
        pt = QVector3D(ctx.world.x(), ctx.world.y(), 0.0)
        if len(self.nodes) >= 3 and self._near_first(ctx):
            self._finish(ctx.viewport, closed=True)
            return
        self.nodes.append(pt)
        # Remember the ground at the previous node so the live label can show
        # drop and grade to the cursor.
        self._start_elevation = ctx.viewport.ground_elevation(pt.x(), pt.y())
        ctx.viewport.update()

    def on_double_click(self, ctx: ToolContext) -> None:
        # Qt sends a press before the double-click, so the point is already in;
        # just finish the open path (don't add a duplicate node).
        self._finish(ctx.viewport, closed=False)

    def on_hover(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        # Live-drag a grabbed node.
        if self._drag is not None:
            path, i = self._drag
            path.points[i] = QVector3D(ctx.world.x(), ctx.world.y(), 0.0)
            vp.scene.version += 1
            vp.update()
            return
        self.hover_point = QVector3D(ctx.world.x(), ctx.world.y(), 0.0)
        # The REAL altitude, not the local offset — a cota without its datum
        # is a number you cannot defend.
        self.hover_elevation = vp.ground_elevation(ctx.world.x(), ctx.world.y())
        # Highlight a node under the cursor when idle (a grab target).
        vp._hover_geo_node = self._pick_node(ctx) if not self.nodes else None
        vp.update()

    def on_value(self, viewport, value) -> bool:
        if not self.nodes or self.hover_point is None:
            return False
        if isinstance(value, tuple):
            if len(value) != 3:
                return False
            last = self.nodes[-1]
            nxt = QVector3D(last.x() + value[0], last.y() + value[1], 0.0)
        else:
            if value <= 0.0:
                return False
            direction = self.hover_point - self.nodes[-1]
            if direction.length() < 1e-9:
                return False
            nxt = self.nodes[-1] + direction.normalized() * value
            nxt.setZ(0.0)
        self.nodes.append(nxt)
        self._start_elevation = viewport.ground_elevation(nxt.x(), nxt.y())
        self.hover_point = nxt
        viewport.update()
        return True

    def on_key(self, viewport, key, modifiers) -> bool:
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._finish(viewport, closed=False)
            return True
        return False

    def on_cancel(self, viewport) -> None:
        if self._drag is not None:
            self._revert_drag(viewport)
        self._reset()
        viewport.update()

    # ---- Preview ------------------------------------------------------------
    def rubber_band_lines(self):
        segs = list(zip(self.nodes, self.nodes[1:]))
        if self.nodes and self.hover_point is not None:
            segs.append((self.nodes[-1], self.hover_point))
        return segs

    def value_label(self):
        if self.hover_point is None:
            return None
        elevation = self.hover_elevation

        # Idle over the ground: read the spot elevation. This is the cheap
        # "what does the terrain do here" question an engineer asks constantly,
        # and it costs nothing to answer while the cursor is already moving.
        if not self.nodes:
            if elevation is None:
                return None
            return (f"{elevation:.2f} m", self.hover_point)

        d = self.hover_point - self.nodes[-1]
        mid = (self.nodes[-1] + self.hover_point) * 0.5
        run = d.length()
        if elevation is None:
            return (f"{run:.2f} m", mid)

        # Tracing with ground under both ends: length, drop and grade — the
        # three numbers a road or canal alignment is judged on, without
        # leaving the tool to open the profile.
        start_z = self._start_elevation
        if start_z is None or run < 1e-6:
            return (f"{run:.2f} m  ·  {elevation:.2f} m", mid)
        rise = elevation - start_z
        grade = rise / run * 100.0
        return (f"{run:.2f} m  ·  {elevation:.2f} m  ·  {rise:+.2f} m ({grade:+.1f}%)",
                mid)

    # ---- Internals ----------------------------------------------------------
    def _pick_node(self, ctx: ToolContext):
        """The ``(GeoPath, index)`` node nearest the cursor within reach, else None."""
        vp = ctx.viewport
        best, best_d = None, _NODE_PX
        for path in vp.scene.geo_paths:
            for i, p in enumerate(path.points):
                q = vp._world_to_pixel(vp.drape(p))
                if q is None:
                    continue
                d = math.hypot(q[0] - ctx.screen.x(), q[1] - ctx.screen.y())
                if d < best_d:
                    best_d, best = d, (path, i)
        return best

    def _commit_node_move(self, viewport) -> None:
        path, i = self._drag
        new = QVector3D(path.points[i])
        path.points[i] = QVector3D(self._orig)        # revert the live edit…
        viewport.history.execute(                     # …then apply as one command
            MoveGeoPathNodeCommand(path, i, new))
        self._drag = None
        self._orig = None
        viewport.update()

    def _revert_drag(self, viewport) -> None:
        path, i = self._drag
        path.points[i] = QVector3D(self._orig)
        viewport.scene.version += 1
        self._drag = None
        self._orig = None

    def _near_first(self, ctx: ToolContext) -> bool:
        first = ctx.viewport._world_to_pixel(self.nodes[0])
        if first is None:
            return False
        return math.hypot(first[0] - ctx.screen.x(),
                          first[1] - ctx.screen.y()) <= _CLOSE_PX

    def _finish(self, viewport, closed: bool) -> None:
        if len(self.nodes) >= 2:
            path = GeoPath(self.nodes, closed=closed)
            viewport.history.execute(AddGeoPathCommand(path))
        self._reset()
        viewport.update()

    def _reset(self) -> None:
        self.nodes = []
        self._start_elevation = None
