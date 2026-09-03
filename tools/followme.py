# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Follow Me tool: sweep a profile face along a path (W) — SketchUp's three
ways (help.sketchup.com "Extruding with Follow Me", Quick Reference Card):

1. **Drag along the path.** Click the profile face, then move along the
   path touching its edges: the path highlights in RED and the extrusion
   previews live, mitred corners included. Click (or release a real drag)
   when you reach the end; Esc starts over. Skipping segments of an arc is
   fine — the connected edges in between are followed; moving back along
   the path shrinks it. Hold **Alt** over a face to use its perimeter as
   the path.
2. **Preselect the path**: a chain of edges (one click on a circle
   segment selects the whole contour) — then activate Follow Me and click
   the profile: it sweeps at once.
3. **Preselect a face**: its outer boundary is the (closed) path — a
   moulding around a slab, a lathe around a circle.

The heavy lifting lives headless in :mod:`core.sweep` (the action layer);
this tool is the click shell.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.i18n import tr
from core.history import SnapshotMutation
from core.mesh import Edge, Face
from core.sweep import (manual_path_extend, manual_path_start,
                        order_path_edges, orient_closed_path,
                        sweep_preview_faces, sweep_profile)
from tools.base import Tool, ToolContext

#: Below this many pixels between press and release, a "drag" was a click:
#: the user is in the click / move / click flow and the path keeps growing.
_DRAG_PX = 6.0


class FollowMeTool(Tool):
    name = "Follow Me"
    shortcut = "W"
    uses_snap = False        # picks a profile face; no snap markers
    #: The dragged path reads RED, as SketchUp highlights it.
    wireframe_color = (0.85, 0.16, 0.16, 1.0)

    def __init__(self) -> None:
        self.hovered_face: Face | None = None
        self._path: list[QVector3D] | None = None      # preselected path
        self._closed = False
        # The manual drag: the clicked profile and the path so far.
        self._profile: Face | None = None
        self._chain: list = []
        self._start_pt: QVector3D | None = None
        self._alt_face: Face | None = None
        self._preview: list = []
        self._preview_pts: list = []
        self._preview_closed = False
        self._press_screen = None
        self._last_screen = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self.hovered_face = None
        self._path = None
        self._closed = False
        self._reset_drag()
        sel = list(viewport.scene.selection)
        edges = [e for e in sel if isinstance(e, Edge)]
        faces = [f for f in sel if isinstance(f, Face)]
        if edges:
            chain = order_path_edges(edges)
            if chain is None:
                viewport.flash_status(tr(
                    "Follow Me: the selected edges must form one simple path"))
                return
            self._path, self._closed = chain
        elif len(faces) == 1:
            # A selected face's outer boundary is the (closed) path.
            self._path = [QVector3D(v) for v in faces[0].vertices]
            self._closed = True
        else:
            viewport.flash_status(tr(
                "Follow Me: click the profile and drag along the path (it "
                "highlights red), click to finish — or select the path "
                "first, then click the profile"), 6000)

    def on_deactivate(self, viewport) -> None:
        viewport.set_hover(None)
        self.hovered_face = None
        self._reset_drag()

    # ---- Spatial input ------------------------------------------------------
    def on_hover(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        x, y = ctx.screen.x(), ctx.screen.y()
        if self._profile is None:
            self.hovered_face = viewport.pick_face(x, y)
            viewport.set_hover(self.hovered_face)
            return
        self._last_screen = (x, y)
        changed = False
        if ctx.modifiers & Qt.AltModifier:
            face = viewport.pick_face(x, y)
            if (face is not None and face is not self._profile
                    and face is not self._alt_face):
                self._alt_face = face
                changed = True
        else:
            if self._alt_face is not None:
                self._alt_face = None
                changed = True
            edge = viewport.pick_edge(x, y)
            if edge is not None and not self._in_profile_plane(edge):
                if not self._chain:
                    self._start_pt, self._chain = manual_path_start(
                        self._profile, edge, ctx.world)
                    changed = True
                else:
                    changed = manual_path_extend(
                        self._chain, edge, skip=self._in_profile_plane)
        if changed:
            self._rebuild_preview()
            viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        if self._profile is not None:            # dragging: a click finishes
            self._finish(viewport)
            return
        face = self.hovered_face
        if face is None:
            return
        if self._path is not None:               # preselected path: at once
            path, closed = self._orient_path(face)
            self._commit(viewport, face, path, closed)
            return
        # Manual: from this profile, the path is whatever the cursor touches.
        self._profile = face
        self._chain = []
        self._start_pt = None
        self._alt_face = None
        self._preview = []
        self._preview_pts = []
        self._press_screen = (ctx.screen.x(), ctx.screen.y())
        self._last_screen = self._press_screen
        viewport.set_hover(None)
        viewport.flash_status(tr(
            "Follow Me: drag along the path (it highlights red) — click to "
            "finish, Esc to cancel; hold Alt over a face to follow its "
            "perimeter"), 6000)
        viewport.update()

    def on_release(self, viewport) -> None:
        """A real press-drag-release along the path finishes it; the
        release of the starting click (no motion) keeps the drag open for
        the click / move / click flow."""
        if self._profile is None or not self._preview_pts:
            return
        a, b = self._press_screen, self._last_screen
        if a is None or b is None:
            return
        if ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 >= _DRAG_PX:
            self._finish(viewport)

    def on_cancel(self, viewport) -> None:
        self._reset_drag()
        viewport.set_hover(None)
        viewport.update()

    # ---- Preview ------------------------------------------------------------
    def rubber_band_lines(self):
        pts = self._preview_pts
        if len(pts) < 2:
            return []
        segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        if self._preview_closed:
            segs.append((pts[-1], pts[0]))
        return segs

    def preview_faces(self):
        return self._preview

    # ---- Internals ----------------------------------------------------------
    def path_points(self):
        """The dragged path as points, and whether it closes on itself."""
        if self._alt_face is not None:
            return orient_closed_path(self._alt_face.vertices,
                                      self._profile), True
        pts = [v.position for v in self._chain]
        closed = (len(self._chain) >= 4 and self._chain[-1] is self._chain[0]
                  and self._start_pt is None)
        if closed:
            pts = pts[:-1]
        elif self._start_pt is not None:
            pts = [self._start_pt] + pts
        return pts, closed

    def _rebuild_preview(self) -> None:
        pts, closed = self.path_points()
        self._preview_pts = pts
        self._preview_closed = closed
        if len(pts) >= 2 and self._profile is not None:
            self._preview = sweep_preview_faces(self._profile, pts, closed)
        else:
            self._preview = []

    def _in_profile_plane(self, edge) -> bool:
        """Edges lying in the profile's plane are never path edges (the
        profile stands perpendicular to the path) — the profile's own
        boundary above all."""
        face = self._profile
        if face is None:
            return False
        c = face.centroid()
        n = face.normal().normalized()
        return (abs(QVector3D.dotProduct(edge.a - c, n)) < 1e-6
                and abs(QVector3D.dotProduct(edge.b - c, n)) < 1e-6)

    def _reset_drag(self) -> None:
        self._profile = None
        self._chain = []
        self._start_pt = None
        self._alt_face = None
        self._preview = []
        self._preview_pts = []
        self._preview_closed = False
        self._press_screen = None
        self._last_screen = None

    def _finish(self, viewport) -> None:
        face = self._profile
        pts, closed = self.path_points()
        self._reset_drag()
        if face is None or len(pts) < 2:
            viewport.flash_status(tr(
                "Follow Me: touch the path edges to extrude along them"))
            viewport.update()
            return
        self._commit(viewport, face, pts, closed)

    def _commit(self, viewport, face, path, closed) -> None:
        result = {"ok": False}

        def mutate(scene):
            result["ok"] = sweep_profile(scene.mesh, face, path, closed)

        viewport.set_hover(None)
        self.hovered_face = None
        viewport.history.execute(SnapshotMutation(mutate))
        if not result["ok"]:
            # The sweep declined (degenerate path); drop the no-op entry.
            viewport.history.undo()
            viewport.history.redo_stack.clear()
            viewport.flash_status(tr(
                "Follow Me: could not sweep along that path "
                "(reversal or degenerate segment)"))
        else:
            viewport.scene.selection.clear()
        viewport.update()

    def _orient_path(self, face) -> tuple[list[QVector3D], bool]:
        """Start the sweep at the path point nearest the profile: reverse an
        open chain whose far end is closer, rotate a closed loop so station 0
        sits next to the profile (the first ring projects from there)."""
        path = [QVector3D(p) for p in self._path]
        c = face.centroid()
        if self._closed:
            return orient_closed_path(path, face), True
        if (path[-1] - c).length() < (path[0] - c).length():
            path.reverse()
        return path, False
