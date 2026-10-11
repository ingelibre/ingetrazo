# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Camera ▸ Field of View — how wide the perspective sees.

Drag DOWN and the angle opens (a wide angle: more of the room, stronger
convergence); drag UP and it closes (a telephoto: less, flatter). The eye
stays where it is, so the picture changes the way a zoom lens does, not
the way walking does. The Measurements box shows the angle to a hundredth
of a degree and takes a typed one (``35`` → 35°).

The angle is the camera's own ``fov_deg`` — the one a saved view, a scene
and a sheet frame already remember — kept within ``MIN_FOV_DEG`` …
``MAX_FOV_DEG``. It only means something in perspective: in a parallel
projection the tool says so and leaves the camera alone.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtGui import QVector3D

from core.i18n import tr
from tools.base import Tool, ToolContext


class FieldOfViewTool(Tool):
    name = "Field of View"
    description = (
        "Drag down to widen the perspective's field of view, up to narrow "
        "it; or type an angle.")
    #: The Zoom's magnifier: it is the lens of the same camera.
    icon = "zoom"
    uses_snap = False
    vcb_label = "Field of View"
    #: A drag over the whole height of the view multiplies (or divides)
    #: the angle by this. Proportional rather than linear, so a telephoto
    #: of a few degrees is as easy to set to the hundredth as a wide angle.
    FACTOR_PER_HEIGHT = 4.0

    def __init__(self) -> None:
        self._viewport = None
        self._press_px: QPointF | None = None
        self._press_fov: float | None = None

    def on_activate(self, viewport) -> None:
        self._viewport = viewport
        self._press_px = None
        self._press_fov = None
        if not viewport.camera.perspective:
            self._refuse(viewport)

    def on_deactivate(self, viewport) -> None:
        self._viewport = None
        self._press_px = None
        self._press_fov = None

    def value_is_unitless(self) -> bool:
        return True                     # degrees, not a length

    def value_label(self):
        vp = self._viewport
        if vp is None or not vp.camera.perspective:
            return None
        return (f"{vp.camera.fov_deg:.2f}°", None)

    def drag_plane(self, viewport):
        """The drag is read in pixels; a plane facing the camera through
        its target answers every ray (see ``Tool.drag_plane``)."""
        cam = viewport.camera
        return QVector3D(cam.target), -cam.forward()

    @staticmethod
    def _refuse(viewport) -> None:
        flash = getattr(viewport, "flash_status", None)
        if flash is not None:
            flash(tr("The field of view only applies in perspective — "
                     "Camera ▸ Toggle Perspective / Parallel (Shift+P)"),
                  4000)

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if not vp.camera.perspective:
            self._refuse(vp)
            return
        self._press_px = QPointF(ctx.screen)
        self._press_fov = vp.camera.fov_deg

    def on_hover(self, ctx: ToolContext) -> None:
        if self._press_px is None:
            return
        vp = ctx.viewport
        if not vp.camera.perspective:   # Shift+P in the middle of a drag
            self.on_cancel(vp)
            return
        h = max(1, vp.height())
        # Measured from the press, not step by step: rounding each small
        # step to 0.01° would leave a slow drag at 1° stuck where it is.
        dy = ctx.screen.y() - self._press_px.y()     # screen y runs down
        vp.camera.set_fov(self._press_fov
                          * self.FACTOR_PER_HEIGHT ** (dy / h))
        vp.update()

    def on_release(self, viewport) -> None:
        self._press_px = None
        self._press_fov = None

    def on_cancel(self, viewport) -> None:
        """Esc mid-drag puts the angle back where the drag found it."""
        if self._press_fov is not None:
            viewport.camera.set_fov(self._press_fov)
            viewport.update()
        self._press_px = None
        self._press_fov = None

    def on_value(self, viewport, value) -> bool:
        """A typed angle, in degrees."""
        if isinstance(value, tuple) or not isinstance(value, (int, float)):
            return False
        if not viewport.camera.perspective:
            self._refuse(viewport)
            return False
        if value <= 0.0:
            return False
        viewport.camera.set_fov(value)
        viewport.update()
        return True
