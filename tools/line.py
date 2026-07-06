# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Line tool: click points to draw edges; auto-close polygons.

Behavior mirrors SketchUp:
- First click sets the start point of a fresh chain.
- Each next click finalises a segment and chains into the next one.
- Snapping to the chain's first point (snap kind ``"close"``) finishes the
  polygon and resets the chain.
- Esc cancels the chain without committing the pending segment.

The tool exposes ``start_point``, ``hover_point`` and ``chain_first_point``
so the viewport can:
  * draw the rubber-band preview during ``paintGL``,
  * feed those into the snap engine for close-polygon detection.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edge
from core.history import Command
from tools.base import Tool, ToolContext


class LineTool(Tool):
    name = "Line"
    shortcut = "L"
    vcb_label = "Length"

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None
        self.hover_point: QVector3D | None = None
        self.chain_first_point: QVector3D | None = None
        # Ordered list of vertices in the current chain. Populated as the
        # user clicks; consumed to build a Face when the chain auto-closes.
        self.chain_vertices: list[QVector3D] = []
        # (point, normal) of the face the chain was started on, if any.
        # The viewport reads this to keep subsequent points coplanar.
        self.work_plane: tuple[QVector3D, QVector3D] | None = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        clicked = ctx.world
        if self.start_point is None:
            self.start_point = clicked
            self.chain_first_point = clicked
            self.chain_vertices = [clicked]
            return

        cmd = self._commit_edge(ctx.viewport, self.start_point, clicked)
        ctx.viewport.history.execute(cmd)
        if ctx.snap.kind == "close":
            self._reset()
        else:
            self.chain_vertices.append(clicked)
            self.start_point = clicked
        ctx.viewport.update()

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        ctx.viewport.update()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def rubber_band_lines(self):
        if self.start_point is None or self.hover_point is None:
            return []
        return [(self.start_point, self.hover_point)]

    def on_value(self, viewport, value) -> bool:
        """Commit a segment from the VCB input.

        ``value`` is either:
        - ``float``  → length along the current rubber-band direction.
        - 3-tuple    → ``(dx, dy, dz)`` delta added to the start point,
                        which makes inclined / elevated lines trivial to
                        construct numerically (start, then type "3;4;5"
                        for a +3 X, +4 Y, +5 Z delta).
        """
        if self.start_point is None:
            return False

        if isinstance(value, tuple):
            if len(value) != 3:
                return False  # 2-tuple is a rectangle's W×H, not a line delta
            dx, dy, dz = value
            new_endpoint = QVector3D(
                self.start_point.x() + dx,
                self.start_point.y() + dy,
                self.start_point.z() + dz,
            )
        else:
            if self.hover_point is None or value <= 0.0:
                return False
            delta = self.hover_point - self.start_point
            if delta.length() < 1e-9:
                return False
            direction = delta.normalized()
            new_endpoint = self.start_point + direction * value

        viewport.history.execute(self._commit_edge(viewport, self.start_point, new_endpoint))
        self.chain_vertices.append(new_endpoint)
        self.start_point = new_endpoint
        self.hover_point = new_endpoint
        viewport.update()
        return True

    # ---- Internals ----------------------------------------------------------
    def _commit_edge(self, viewport, start: QVector3D, end: QVector3D) -> Command:
        """Build the command for a new edge. ``build_add_edge`` welds
        coincident edges, splits any existing edge the new one crosses
        (introducing a shared vertex), and attaches a face when the new edge
        closes a planar cycle — the SketchUp-style "any planar loop becomes a
        face" behaviour, now correct even when the loop relies on a crossing."""
        return build_add_edge(viewport.scene, start, end, detect_faces=True)

    def _reset(self) -> None:
        self.start_point = None
        self.chain_first_point = None
        self.chain_vertices = []
        self.work_plane = None
