# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Dimension tool (D): place a static linear dimension.

Three clicks, the classic way:
1. first endpoint (snapped to geometry),
2. second endpoint (snapped),
3. move to slide the dimension line off the measured segment, click to place.

While placing, the rubber band previews the extension + dimension lines and the
value label shows the live measurement. The committed dimension lives in
``Scene.dimensions`` and is drawn as a persistent overlay by the viewport.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QVector3D

from core.dimension import Dimension, _AXIS_VECTORS, _linear_frame
from core.snap import project_to_view_plane
from core.history import AddDimensionCommand
from tools.base import AxisMagnet, Tool, ToolContext
from core.units import fmt_len


class DimensionTool(AxisMagnet, Tool):
    name = "Dimension"
    shortcut = "D"
    description = (
        "Place a dimension that shows the distance between two "
        "points.")

    def magnet_on(self) -> bool:
        # The second endpoint is a direction from the first (issue #50:
        # «they often stick to a planar face» — the magnet lifts the
        # point onto the axis instead). The placement click is not.
        return self.b is None

    def __init__(self) -> None:
        self.a: QVector3D | None = None
        self.b: QVector3D | None = None
        self.hover_point: QVector3D | None = None
        # Read by the viewport for the work plane / snap engine (mirrors ``a``).
        self.start_point: QVector3D | None = None
        self.work_plane: tuple[QVector3D, QVector3D] | None = None
        self._vp = None
        # Last placement the free cursor asked for, and the one a held Shift
        # froze: ``(unit offset direction, axis)``.
        self._free: tuple[QVector3D, str | None] | None = None
        self._hold: tuple[QVector3D, str | None] | None = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    # ---- Spatial input ------------------------------------------------------
    def _frontal(self, ctx: ToolContext, p: QVector3D) -> QVector3D:
        """In a standard axis-aligned view, pull *p* into the first point's
        view plane so the dimension reads the frontal span, not the 3-D
        diagonal. No-op before the first point, and in oblique views."""
        if self.a is None:
            return p
        cam = getattr(ctx.viewport, "camera", None)
        if cam is None:
            return p
        return project_to_view_plane(p, self.a, cam.target - cam.eye())

    def _locked_dir(self) -> QVector3D | None:
        """The direction a held arrow pins the placement to, as in Line."""
        axis = getattr(self._vp, "axis_lock", None)
        return QVector3D(_AXIS_VECTORS[axis]) if axis in _AXIS_VECTORS else None

    @staticmethod
    def _shift_held() -> bool:
        return bool(QGuiApplication.keyboardModifiers() & Qt.ShiftModifier)

    def owns_shift_lock(self) -> bool:
        """While placing, Shift freezes what the preview already shows
        (see ``_proposed``), not the a→cursor inference the viewport
        would lock."""
        return self.b is not None

    def on_hover(self, ctx: ToolContext) -> None:
        self._vp = ctx.viewport
        self.hover_point = self._frontal(ctx, ctx.world)
        if self.b is not None and not self._shift_held():
            self._free = Dimension.placement_for_cursor(
                self.a, self.b, self.hover_point)

    def on_click(self, ctx: ToolContext) -> None:
        p = ctx.world
        self._vp = ctx.viewport
        if self.a is None:
            self.a = QVector3D(p)
            self.start_point = self.a
            return
        if self.b is None:
            p = self._frontal(ctx, p)
            if (p - self.a).length() < 1e-6:
                return  # need two distinct endpoints
            self.b = QVector3D(p)
            self._free = self._hold = None
            # A Shift held through the endpoint click locked the a–b
            # direction itself; the placement step needs a fresh lock.
            if getattr(ctx.viewport, "_shift_lock", None):
                ctx.viewport._shift_lock = None
            return
        # Third click: place the dimension where the cursor asks — aligned,
        # or linear along an axis when pulled past the ends (issue #50).
        ctx.viewport.history.execute(AddDimensionCommand(self._proposed(p)))
        self._reset()
        ctx.viewport.update()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- Live preview -------------------------------------------------------
    def rubber_band_lines(self):
        if self.hover_point is None:
            return []
        if self.a is not None and self.b is None:
            return [(self.a, self.hover_point)]          # measuring span
        if self.a is not None and self.b is not None:
            ap, bp = self._proposed(self.hover_point).line_points()
            return [(self.a, ap), (self.b, bp), (ap, bp)]  # extension + dim line
        return []

    def value_label(self):
        if self.hover_point is None or self.a is None:
            return None
        if self.b is None:
            mid = (self.a + self.hover_point) * 0.5
            return (fmt_len((self.hover_point - self.a).length()), mid)
        proposed = self._proposed(self.hover_point)
        return (fmt_len(proposed.value()), proposed.midpoint())

    def _proposed(self, cursor: QVector3D) -> Dimension:
        """The dimension the current cursor would place (preview and
        commit share it, so what you see is what you get)."""
        lock = self._locked_dir()
        if lock is not None:
            offset, axis = self._pull_along(lock, cursor)
            if offset is None:
                offset = Dimension.offset_for_cursor(self.a, self.b, cursor)
        elif self._shift_held():
            # Shift keeps the kind and direction the preview showed when it
            # went down; the cursor only slides the line along it.
            if self._hold is None:
                off, ax = self._free or Dimension.placement_for_cursor(
                    self.a, self.b, cursor)
                if off.length() > 1e-9:
                    self._hold = (off.normalized(), ax)
            if self._hold is not None:
                direction, axis = self._hold
                offset = direction * QVector3D.dotProduct(
                    cursor - self.a, direction)
            else:
                offset, axis = Dimension.placement_for_cursor(
                    self.a, self.b, cursor)
        else:
            self._hold = None
            offset, axis = Dimension.placement_for_cursor(self.a, self.b, cursor)
        return Dimension(QVector3D(self.a), QVector3D(self.b), offset, axis=axis)

    def _pull_along(self, lv: QVector3D, cursor: QVector3D):
        """``(offset, axis)`` for a dimension whose line is pulled ALONG the
        locked axis. If the segment lies in a plane with that axis, the
        extension lines run along it and the dimension measures the other
        axis (linear); otherwise (e.g. a flat segment pulled up in Z) it is
        the aligned dimension raised along the axis. ``(None, None)`` when
        the pull would be lost along the segment."""
        ab = self.b - self.a
        d = ab / ab.length()
        t = QVector3D.dotProduct(cursor - self.a, lv)
        lo = math.sin(math.radians(15.0))
        for name in "xyz":
            frame = _linear_frame(self.a, self.b, name)
            if frame is None:
                continue
            u, e = frame
            if abs(QVector3D.dotProduct(d, u)) < lo:
                continue
            if abs(QVector3D.dotProduct(e, lv)) > 0.999:
                return lv * t, name
        along = lv - d * QVector3D.dotProduct(lv, d)
        if along.length() < 0.25:
            return None, None
        return lv * t, None

    def _reset(self) -> None:
        self.a = None
        self.b = None
        self.start_point = None
        self.work_plane = None
        self._free = self._hold = None
