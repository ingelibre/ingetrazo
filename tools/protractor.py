# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Protractor tool (H) and the shared SketchUp protractor mechanics.

:class:`ProtractorBase` holds everything SketchUp's protractor cursor does —
Rotate (Q) shows the same instrument, so both tools share it:

- Before the first click the disc follows the cursor, aligned to the face
  underneath (empty ground measures in plan) and coloured by the axis it
  rotates about — red/green/blue on an axis plane, dark otherwise. Arrow keys
  lock the plane to an axis (Right=red, Left=green, Up=blue; same arrow again
  releases); holding Shift freezes the current plane. The plane fixes once
  the vertex/centre is placed.
- The disc keeps a fixed SCREEN size, with tick marks every 15° (long at
  90°), zero aligned to the base arm once set.
- SketchUp's distance rule: near the disc the cursor snaps to the 15° ticks;
  farther out the angle is free at 0.1° precision.
- The Measurements box accepts degrees (``34.1``) or a slope as rise:run
  (``3:12``, ``1:6``) — ``accepts_angle_ratio`` delivers it as degrees.

:class:`ProtractorTool` (this file) creates ANGLED guide lines with it
(help.sketchup.com "Measuring Angles" / "Using Guides"): vertex → base arm →
sweep & click = an infinite dashed guide through the vertex. The tool then
resets, but the angle stays "hot": typing a value re-aims the guide just
created until the next click or tool change.

Guides are scaffolding, not geometry: they feed the snap engine so Line /
Rectangle can lock onto the angled direction, and are deleted with Select /
Eraser / Edit ▸ Delete Guides.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.guide import Guide
from core.history import AddGuideCommand, ChangeGuideCommand
from core.snap import COLOR_AXIS_X, COLOR_AXIS_Y, COLOR_AXIS_Z
from core.triangulate import plane_axes
from tools.base import Tool, ToolContext

# The disc keeps a fixed SCREEN size (SketchUp); ticks every 15 degrees.
DISC_PX = 60.0
TICK_DEG = 15.0
_AXES = {"x": QVector3D(1, 0, 0), "y": QVector3D(0, 1, 0),
         "z": QVector3D(0, 0, 1)}
_AXIS_RGBA = {"x": (*COLOR_AXIS_X, 1.0), "y": (*COLOR_AXIS_Y, 1.0),
              "z": (*COLOR_AXIS_Z, 1.0)}
_OFF_AXIS_RGBA = (0.24, 0.27, 0.32, 1.0)


class ProtractorBase(Tool):
    """Shared protractor state + behaviour (see module docstring)."""

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None   # the protractor centre
        self.ref_point: QVector3D | None = None     # base (0°) direction
        self.hover_point: QVector3D | None = None
        self.work_plane: tuple[QVector3D, QVector3D] | None = None
        self._axis_pick: str | None = None          # arrow-key plane lock
        self._shift_normal: QVector3D | None = None  # Shift-frozen plane
        self._custom_axis: QVector3D | None = None  # drag-defined axis (Rotate)
        self._disc_r = 1.0                          # world radius of the disc
        self._snap_ticks = False                    # cursor near the disc?

    # ---- Keyboard -----------------------------------------------------------
    def on_key(self, viewport, key: int, modifiers) -> bool:
        # Arrow keys lock the protractor plane to an axis (SketchUp): Right =
        # red, Left = green, Up = blue; the same arrow again releases it.
        picks = {Qt.Key_Right: "x", Qt.Key_Left: "y", Qt.Key_Up: "z"}
        axis = picks.get(key)
        if axis is None:
            return False
        self._axis_pick = None if self._axis_pick == axis else axis
        if self._axis_pick is not None and self.start_point is None:
            anchor = (self.hover_point if self.hover_point is not None
                      else QVector3D(0, 0, 0))
            self.work_plane = (anchor, QVector3D(_AXES[self._axis_pick]))
        viewport.update()
        return True

    # ---- Plane / colour -----------------------------------------------------
    @property
    def wireframe_color(self):  # type: ignore[override]
        # The disc is coloured by its rotation axis (SketchUp): red/green/blue
        # on an axis plane, dark on an arbitrary face plane.
        n = self._axis()
        for axis, v in _AXES.items():
            if abs(QVector3D.dotProduct(n, v)) > 0.999:
                return _AXIS_RGBA[axis]
        return _OFF_AXIS_RGBA

    def _axis(self) -> QVector3D:
        if self._custom_axis is not None:
            return self._custom_axis
        if self._shift_normal is not None:
            return self._shift_normal
        if self._axis_pick is not None:
            return QVector3D(_AXES[self._axis_pick])
        if self.work_plane is not None:
            return self.work_plane[1].normalized()
        return QVector3D(0.0, 0.0, 1.0)

    def _infer_plane(self, ctx: ToolContext) -> None:
        """SketchUp plane inference, active until the vertex is placed: the
        disc aligns to the face under the cursor (Shift freezes it, arrows
        override it); empty ground measures in plan."""
        shift = bool(ctx.modifiers & Qt.ShiftModifier)
        if not shift:
            self._shift_normal = None
        if self.start_point is not None:   # vertex placed: plane is fixed
            return
        if shift:
            if self._shift_normal is None:
                self._shift_normal = QVector3D(self._axis())
            return
        if self._axis_pick is not None:
            self.work_plane = (ctx.world, QVector3D(_AXES[self._axis_pick]))
            return
        pick = getattr(ctx.viewport, "pick_face_any", None)
        face = None
        if pick is not None:
            face, _group = pick(ctx.screen.x(), ctx.screen.y())
        if face is not None:
            self.work_plane = (QVector3D(ctx.world), face.normal().normalized())
        else:
            self.work_plane = None         # ground: measure in plan

    # ---- Screen metrics / snapping ------------------------------------------
    def _update_screen_metrics(self, ctx: ToolContext) -> None:
        """Fixed screen-size disc + SketchUp's distance rule: near the disc
        the cursor snaps to the 15° ticks, farther out it measures free at
        0.1° precision."""
        w2p = getattr(ctx.viewport, "_world_to_pixel", None)
        # NOT ``start or hover``: a zero QVector3D (the origin!) is falsy.
        centre = (self.start_point if self.start_point is not None
                  else self.hover_point)
        if w2p is None or centre is None:
            return
        u, _v = plane_axes(self._axis())
        p0 = w2p(centre)
        p1 = w2p(centre + u)
        if p0 is None or p1 is None:
            return
        px_per_unit = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if px_per_unit > 1e-6:
            self._disc_r = DISC_PX / px_per_unit
        if self.start_point is not None:
            dist = math.hypot(ctx.screen.x() - p0[0], ctx.screen.y() - p0[1])
            self._snap_ticks = dist <= DISC_PX * 1.25
        else:
            self._snap_ticks = False

    # ---- Angles -------------------------------------------------------------
    def _angle_to(self, point: QVector3D) -> float | None:
        u, v = plane_axes(self._axis())
        a = self.ref_point - self.start_point
        b = point - self.start_point
        a2 = (QVector3D.dotProduct(a, u), QVector3D.dotProduct(a, v))
        b2 = (QVector3D.dotProduct(b, u), QVector3D.dotProduct(b, v))
        if math.hypot(*a2) < 1e-9 or math.hypot(*b2) < 1e-9:
            return None
        deg = math.degrees(math.atan2(b2[1], b2[0]) - math.atan2(a2[1], a2[0]))
        while deg <= -180.0:
            deg += 360.0
        while deg > 180.0:
            deg -= 360.0
        return deg

    def _display_deg(self, point: QVector3D) -> float | None:
        """The angle as SketchUp reports and commits it: snapped to the 15°
        ticks near the disc, 0.1° precision farther out."""
        deg = self._angle_to(point)
        if deg is None:
            return None
        if self._snap_ticks:
            deg = round(deg / TICK_DEG) * TICK_DEG
            if deg <= -180.0:
                deg += 360.0
        return round(deg, 1)

    def _direction_at(self, deg: float) -> QVector3D:
        """Unit direction of the base arm rotated by ``deg`` in the plane."""
        u, v = plane_axes(self._axis())
        a = self.ref_point - self.start_point
        a0 = math.atan2(QVector3D.dotProduct(a, v), QVector3D.dotProduct(a, u))
        t = a0 + math.radians(deg)
        return (u * math.cos(t) + v * math.sin(t)).normalized()

    # ---- Disc rendering -----------------------------------------------------
    def _protractor_disc(self, centre: QVector3D):
        """The fixed-screen-size disc with tick marks every 15° (long at 90°),
        rotated so its zero sits on the base arm once that is set."""
        u, v = plane_axes(self._axis())
        r = self._disc_r
        base = 0.0
        if self.start_point is not None and self.ref_point is not None:
            a = self.ref_point - self.start_point
            base = math.atan2(QVector3D.dotProduct(a, v),
                              QVector3D.dotProduct(a, u))

        def rim(t: float, k: float = 1.0):
            return centre + (u * math.cos(t) + v * math.sin(t)) * (r * k)

        n = 48
        pts = [rim(base + 2 * math.pi * k / n) for k in range(n)]
        segments = [(pts[k], pts[(k + 1) % n]) for k in range(n)]
        for k in range(int(360 / TICK_DEG)):
            t = base + math.radians(k * TICK_DEG)
            inner = 0.75 if k * TICK_DEG % 90 == 0 else 0.86
            segments.append((rim(t, inner), rim(t)))
        return segments

    def _reset_protractor(self) -> None:
        self.start_point = None
        self.ref_point = None
        self.work_plane = None
        self._shift_normal = None
        self._custom_axis = None
        self._snap_ticks = False


class ProtractorTool(ProtractorBase):
    name = "Protractor"
    shortcut = "H"
    vcb_label = "Angle"
    accepts_angle_ratio = True  # VCB "3:12" (rise:run) arrives as degrees

    def __init__(self) -> None:
        super().__init__()
        self._last: dict | None = None              # hot retype of last guide

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()
        self._last = None

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self._last = None
        self._axis_pick = None
        self.hover_point = None

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        self._last = None            # a click ends the retype window
        if self.start_point is None:
            self.start_point = ctx.world
            return
        if self.ref_point is None:
            if (ctx.world - self.start_point).length() < 1e-6:
                return
            self.ref_point = ctx.world
            return
        deg = self._display_deg(ctx.world)
        if deg is not None:
            self._commit(ctx.viewport, deg)

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        self._infer_plane(ctx)
        self._update_screen_metrics(ctx)
        ctx.viewport.update()

    def on_value(self, viewport, value) -> bool:
        if isinstance(value, tuple):
            return False
        if self.ref_point is not None:
            # Mid-flow: the typed angle turns the way the cursor is sweeping.
            sign = 1.0
            if self.hover_point is not None:
                cur = self._angle_to(self.hover_point)
                if cur is not None and cur < 0:
                    sign = -1.0
            self._commit(viewport, sign * abs(value))
            return True
        if self._last is not None:
            # Hot retype (SketchUp): re-aim the guide just created. A typed
            # negative flips to the other side of the base.
            last = self._last
            if last["guide"] not in viewport.scene.guides:
                self._last = None
                return False
            side = last["sign"] * (1.0 if value >= 0 else -1.0)
            t = last["a0"] + math.radians(side * abs(value))
            d = (last["u"] * math.cos(t) + last["v"] * math.sin(t))
            viewport.history.execute(ChangeGuideCommand(last["guide"], d))
            viewport.update()
            return True
        return False

    def on_cancel(self, viewport) -> None:
        self._reset()
        self._last = None
        viewport.update()

    # ---- Preview ------------------------------------------------------------
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
                d = self._direction_at(deg)
                # Preview of the future guide, long enough to read as a line.
                segments.append((self.start_point - d * 50.0,
                                 self.start_point + d * 50.0))
        return segments

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
    def _commit(self, viewport, deg: float) -> None:
        d = self._direction_at(deg)
        guide = Guide(self.start_point, d)
        viewport.history.execute(AddGuideCommand(guide))
        # SketchUp: the tool resets for the next measurement, but the angle
        # stays hot — typing a value + Enter re-aims this guide until the
        # next click or tool change.
        u, v = plane_axes(self._axis())
        a = self.ref_point - self.start_point
        self._last = {
            "guide": guide,
            "u": QVector3D(u), "v": QVector3D(v),
            "a0": math.atan2(QVector3D.dotProduct(a, v),
                             QVector3D.dotProduct(a, u)),
            "sign": -1.0 if deg < 0 else 1.0,
        }
        self._reset()
        viewport.update()

    def _reset(self) -> None:
        self._reset_protractor()
