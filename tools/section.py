# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Section Plane tool — Tools ▸ Section Plane.

Flow:
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
from core.section import SectionPlane, next_symbol
from core.axes import plane_axes  # drawing axes (#44)
from tools.base import Tool, ToolContext

# The drawing axes (core.axes): the open group's own inside it (#44).
from core.axes import AXES as _AXES  # noqa: E402


class SectionPlaneTool(Tool):
    name = "Section Plane"
    description = "Place a plane that cuts the model open to show its inside."
    uses_snap = True

    @property
    def wireframe_color(self):  # type: ignore[override]
        """The floating plane wears the inference colours (@pacaeiro, #62):
        red/green/blue square to an axis, magenta on any other plane."""
        from tools.base import PlaneLock
        axis = PlaneLock.plane_color(self._current_normal())
        if axis is not None:
            return axis
        from core.snap import COLOR_REFERENCE
        return (*COLOR_REFERENCE, 1.0)

    def __init__(self) -> None:
        self.hover_point: QVector3D | None = None
        self._normal = QVector3D(0, 0, 1)
        self._axis_pick: str | None = None      # arrow-key orientation lock
        self._shift_normal: QVector3D | None = None
        self._viewport = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._viewport = viewport
        self.hover_point = None
        self._axis_pick = None
        self._shift_normal = None

    def on_deactivate(self, viewport) -> None:
        self.hover_point = None

    # ---- Input --------------------------------------------------------------
    def on_key(self, viewport, key: int, modifiers) -> bool:
        # Arrow keys: Up = blue (Z), Right = red (X), Left = green (Y),
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
        self._viewport = ctx.viewport
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
            else:                                   # ground: horizontal cut
                self._normal = self._toward_camera(QVector3D(0, 0, 1))
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        n = self._current_normal()
        planes = getattr(viewport.scene, "section_planes", []) or []
        count = len(planes) + 1
        plane = SectionPlane(ctx.world, n, name=tr("Section {n}", n=count),
                             symbol=next_symbol(planes))
        window = viewport.window() if hasattr(viewport, "window") else None
        # A new plane is placed to be SEEN: cuts and planes switched off
        # come back on (@pacaeiro, #62: «user sees immediately the result»).
        sc = viewport.scene
        if not (getattr(sc, "show_section_cuts", True)
                and getattr(sc, "show_section_planes", True)):
            sc.show_section_cuts = True
            sc.show_section_planes = True
            sync = getattr(window, "_sync_section_menu", None)
            if callable(sync):
                sync()
        viewport.history.execute(PlaceSectionPlaneCommand(plane))
        # Prompt for a name and symbol right after placing.
        prompt = getattr(window, "prompt_section_name", None)
        if prompt is not None:
            prompt(plane)
        viewport.flash_status(tr(
            "Section plane placed — double-click toggles the cut; "
            "Move/Rotate reposition it"), 4000)
        viewport.update()
        # One plane per pick-up, then back to Select — the tool ends
        # after placing (issue #62, @pacaeiro: «There's no need to create
        # several section planes continually»).
        back = getattr(window, "_activate_tool", None)
        if callable(back):
            back("select")

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
            return self._toward_camera(QVector3D(_AXES[self._axis_pick]))
        return self._normal

    def _toward_camera(self, n: QVector3D) -> QVector3D:
        """The cut hides the normal's side, and a freshly placed plane hides
        the side the CAMERA is on (the plane faces you; what lies
        beyond stays until you move the plane into it). A face normal
        already points at the viewer; an axis lock or the ground default
        must be turned the same way — a fixed +Y with the camera south of
        the model hid the whole model in one click."""
        cam = getattr(self._viewport, "camera", None)
        eye_fn = getattr(cam, "eye", None)
        if eye_fn is None or self.hover_point is None:
            return n
        eye = eye_fn()
        if QVector3D.dotProduct(n, eye - self.hover_point) < 0:
            return -n
        return n
