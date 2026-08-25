# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Section Plane tool — SketchUp's Tools ▸ Section Plane.

Official flow (help.sketchup.com "Slicing a Model to Peer Inside"):
- The plane glyph follows the cursor, aligned to the face underneath.
- Hold Shift to LOCK the current orientation; the arrow keys orient the
  plane's normal to an axis — Up = blue (Z), Right = red (X), Left = green
  (Y), Down = back to parallel-to-face inference.
- Click to place. The new plane becomes the ACTIVE cut immediately (one
  active cut per context), and a prompt asks for a name and a symbol.
- Afterwards: Move/Rotate reposition it, right-click offers Reverse /
  Active Cut / Align View, double-click toggles the active cut, Supr
  deletes. View ▸ Section Planes / Section Cuts toggle visibility.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.history import PlaceSectionPlaneCommand
from core.i18n import tr
from core.section import SectionPlane
from core.triangulate import plane_axes
from tools.base import Tool, ToolContext

_AXES = {"x": QVector3D(1, 0, 0), "y": QVector3D(0, 1, 0),
         "z": QVector3D(0, 0, 1)}


class SectionPlaneTool(Tool):
    name = "Section Plane"
    uses_snap = True
    wireframe_color = (0.16, 0.55, 0.45, 1.0)   # SketchUp's greenish glyph

    def __init__(self) -> None:
        self.hover_point: QVector3D | None = None
        self._normal = QVector3D(0, 0, 1)
        self._axis_pick: str | None = None      # arrow-key orientation lock
        self._shift_normal: QVector3D | None = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self.hover_point = None
        self._axis_pick = None
        self._shift_normal = None

    def on_deactivate(self, viewport) -> None:
        self.hover_point = None

    # ---- Input --------------------------------------------------------------
    def on_key(self, viewport, key: int, modifiers) -> bool:
        # SketchUp: Up = blue (Z), Right = red (X), Left = green (Y),
        # Down = parallel to face (back to hover inference).
        picks = {Qt.Key_Up: "z", Qt.Key_Right: "x", Qt.Key_Left: "y"}
        if key == Qt.Key_Down:
            self._axis_pick = None
            viewport.update()
            return True
        axis = picks.get(key)
        if axis is None:
            return False
        self._axis_pick = axis
        viewport.update()
        return True

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        shift = bool(ctx.modifiers & Qt.ShiftModifier)
        if not shift:
            self._shift_normal = None
        if shift:
            if self._shift_normal is None:
                self._shift_normal = QVector3D(self._current_normal())
        elif self._axis_pick is None:
            pick = getattr(ctx.viewport, "pick_face_any", None)
            face = None
            if pick is not None:
                face, _grp = pick(ctx.screen.x(), ctx.screen.y())
            if face is not None:
                self._normal = face.normal().normalized()
            else:
                self._normal = QVector3D(0, 0, 1)   # ground: horizontal cut
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        n = self._current_normal()
        count = len(getattr(viewport.scene, "section_planes", [])) + 1
        plane = SectionPlane(ctx.world, n, name=tr("Section {n}", n=count),
                            symbol=str(count))
        viewport.history.execute(PlaceSectionPlaneCommand(plane))
        # SketchUp prompts for a name and symbol right after placing.
        window = viewport.window() if hasattr(viewport, "window") else None
        prompt = getattr(window, "prompt_section_name", None)
        if prompt is not None:
            prompt(plane)
        viewport.flash_status(tr(
            "Section plane placed — double-click toggles the cut; "
            "Move/Rotate reposition it"), 4000)
        viewport.update()

    def on_cancel(self, viewport) -> None:
        viewport.update()

    # ---- Preview ------------------------------------------------------------
    def rubber_band_lines(self):
        if self.hover_point is None:
            return []
        n = self._current_normal()
        u, v = plane_axes(n)
        c = self.hover_point
        r = 1.2
        quad = [c - u * r - v * r, c + u * r - v * r,
                c + u * r + v * r, c - u * r + v * r]
        segments = [(quad[i], quad[(i + 1) % 4]) for i in range(4)]
        # A short normal whisker shows which side will be CUT AWAY.
        segments.append((c, c + n * (r * 0.5)))
        return segments

    # ---- Internals ----------------------------------------------------------
    def _current_normal(self) -> QVector3D:
        if self._shift_normal is not None:
            return self._shift_normal
        if self._axis_pick is not None:
            return QVector3D(_AXES[self._axis_pick])
        return self._normal
