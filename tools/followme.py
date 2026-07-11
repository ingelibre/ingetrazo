# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Follow Me tool: sweep a profile face along a pre-selected path (W).

SketchUp's reliable flow:
1. Select the path first — a chain of edges (clicking one segment of a circle
   selects the whole contour, so 'around this circle' is one click), or a
   single FACE whose outer boundary is the path (mouldings around a slab).
2. Activate Follow Me and click the PROFILE face: it sweeps along the path
   with proper mitred corners. Closed paths weld back seamlessly (a lathe /
   torus); curved sweeps soften their seams and read smooth.

The heavy lifting lives headless in :mod:`core.sweep` (the action layer);
this tool is the click shell.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.i18n import tr
from core.history import SnapshotMutation
from core.mesh import Edge, Face
from core.sweep import order_path_edges, sweep_profile
from tools.base import Tool, ToolContext


class FollowMeTool(Tool):
    name = "Follow Me"
    shortcut = "W"
    uses_snap = False        # picks a profile face; no snap markers

    def __init__(self) -> None:
        self.hovered_face: Face | None = None
        self._path: list[QVector3D] | None = None
        self._closed = False

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self.hovered_face = None
        self._path = None
        self._closed = False
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
                "Follow Me: select the path (edges or one face) first, "
                "then click the profile"))

    def on_deactivate(self, viewport) -> None:
        viewport.set_hover(None)
        self.hovered_face = None

    # ---- Spatial input ------------------------------------------------------
    def on_hover(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        self.hovered_face = viewport.pick_face(ctx.screen.x(), ctx.screen.y())
        viewport.set_hover(self.hovered_face)

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        face = self.hovered_face
        if face is None:
            return
        if self._path is None:
            viewport.flash_status(tr(
                "Follow Me: select the path (edges or one face) first, "
                "then click the profile"))
            return
        path, closed = self._orient_path(face)
        result = {"ok": False}

        def mutate(scene):
            result["ok"] = sweep_profile(scene.mesh, face, path, closed)

        viewport.set_hover(None)
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

    def on_cancel(self, viewport) -> None:
        viewport.set_hover(None)

    # ---- Internals ----------------------------------------------------------
    def _orient_path(self, face) -> tuple[list[QVector3D], bool]:
        """Start the sweep at the path point nearest the profile: reverse an
        open chain whose far end is closer, rotate a closed loop so station 0
        sits next to the profile (the first ring projects from there)."""
        path = [QVector3D(p) for p in self._path]
        c = face.centroid()
        if self._closed:
            k = min(range(len(path)), key=lambda i: (path[i] - c).length())
            return path[k:] + path[:k], True
        if (path[-1] - c).length() < (path[0] - c).length():
            path.reverse()
        return path, False
