# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Tools ▸ North: aim true north on screen, and the sun with it.

A compass — a circle with an arrow and the letter N — rides the cursor and
shows where north lies now. The first click sets its centre; from there the
arrow follows the cursor in plan, and the second click says "north is
there". Typing an angle (degrees clockwise from the green axis) sets it
straight away, with or without the centre.

Near the circle the arrow snaps to the 15° ticks; farther out it is free at
0.1°, and an inference (an endpoint, an edge, an axis…) is aimed at exactly
— so north can be laid along a street edge drawn on the model.

What it changes is :func:`core.sun.scene_north_deg`, through
:class:`core.history.SetNorthCommand` (one undo step): the datum's north
angle when the model has a location (the map and the terrain turn under the
model), ``scene.north_deg`` when it has none. The model never moves; the
shadows turn.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.sun import north_vector_xy, scene_north_deg, wrap_north_deg
from tools.base import Tool, ToolContext

#: The compass keeps a fixed SCREEN size.
COMPASS_PX = 70.0
TICK_DEG = 15.0
#: Within this many radii of the centre the arrow snaps to the ticks.
SNAP_RADII = 1.25
#: Snap kinds that are not a target the user aimed at.
_FREE_SNAPS = frozenset({"none", "on_face"})
_UP = QVector3D(0.0, 0.0, 1.0)


def north_deg_towards(centre: QVector3D, point: QVector3D) -> float | None:
    """Degrees clockwise from the green (Y) axis of the plan direction
    ``centre → point``; ``None`` when the two coincide in plan."""
    dx, dy = point.x() - centre.x(), point.y() - centre.y()
    if math.hypot(dx, dy) < 1e-9:
        return None
    return wrap_north_deg(math.degrees(math.atan2(dx, dy)))


def compass_segments(centre: QVector3D, radius: float,
                     north_deg: float) -> list[tuple[QVector3D, QVector3D]]:
    """The compass drawn in plan round ``centre``: the circle, ticks every
    15° (long ones at the four cardinal points), an arrow to north that
    runs past the rim, and the letter N beyond its tip, upright along it."""
    r = radius
    ux, uy = north_vector_xy(north_deg)          # to north
    vx, vy = uy, -ux                             # to east (clockwise)
    z = centre.z()

    def at(along: float, across: float) -> QVector3D:
        return QVector3D(centre.x() + ux * along + vx * across,
                         centre.y() + uy * along + vy * across, z)

    segs = []
    n = 64
    rim = [at(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n))
           for k in range(n)]
    segs += [(rim[k], rim[(k + 1) % n]) for k in range(n)]
    for k in range(int(360 / TICK_DEG)):
        t = math.radians(k * TICK_DEG)
        inner = 0.78 if (k * TICK_DEG) % 90 == 0 else 0.9
        c, s = math.cos(t), math.sin(t)
        segs.append((at(r * inner * c, r * inner * s), at(r * c, r * s)))
    # The arrow: a shaft from the centre past the rim, a head at its tip,
    # and a short tail to the south so the axis reads as one line.
    tip = 1.15 * r
    segs.append((at(-0.5 * r, 0.0), at(tip, 0.0)))
    head = 0.18 * r
    segs.append((at(tip, 0.0), at(tip - head, 0.6 * head)))
    segs.append((at(tip, 0.0), at(tip - head, -0.6 * head)))
    # The letter N beyond the tip: two uprights and the diagonal.
    lo, hi, half = tip + 0.12 * r, tip + 0.42 * r, 0.11 * r
    segs.append((at(lo, -half), at(hi, -half)))
    segs.append((at(hi, -half), at(lo, half)))
    segs.append((at(lo, half), at(hi, half)))
    return segs


def refresh_north_display(viewport) -> None:
    """After the north changed on a located model: the map is redrawn from
    the new datum and the terrain rebuilt (``tilesChanged`` → the window's
    terrain build). Without a location only the sun moved: a repaint."""
    scene = getattr(viewport, "scene", None)
    if getattr(scene, "georef", None) is not None:
        reset = getattr(viewport, "reset_tiles", None)
        if callable(reset):
            reset()
        changed = getattr(viewport, "tilesChanged", None)
        if changed is not None:
            changed.emit()
    notify = getattr(viewport, "notify_scene_changed", None)
    if callable(notify):
        notify()


class NorthTool(Tool):
    name = "North"
    icon = "north"
    #: N for north; with Shift, like the Protractor's Shift+H, so the bare
    #: letter stays free.
    shortcut = "Shift+N"
    description = ("Set where north lies: click a centre, then click "
                   "toward north. The sun's shadows turn with it.")
    vcb_label = "Angle"
    #: A red arrow, the colour north always has on a compass.
    wireframe_color = (0.80, 0.16, 0.14, 1.0)

    def value_is_unitless(self) -> bool:
        """The typed value is an angle: no length unit scales it."""
        return True

    def __init__(self) -> None:
        self.centre: QVector3D | None = None
        self.hover_point: QVector3D | None = None
        #: The horizontal plane through the centre, once placed: the
        #: viewport lays the cursor on it, so the arrow sweeps in plan.
        self.work_plane = None
        self._radius = 1.0
        self._snap_ticks = False
        self._exact = False
        #: The scene the compass reads the current north from.
        self._scene = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._scene = getattr(viewport, "scene", None)
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def _reset(self) -> None:
        self.centre = None
        self.work_plane = None
        self._snap_ticks = False
        self._exact = False

    # ---- Input --------------------------------------------------------------
    def on_hover(self, ctx: ToolContext) -> None:
        self._scene = getattr(ctx.viewport, "scene", None)
        self.hover_point = QVector3D(ctx.world)
        snap = getattr(ctx, "snap", None)
        self._exact = (getattr(snap, "kind", "none") or "none") not in _FREE_SNAPS
        self._update_metrics(ctx.viewport, (ctx.screen.x(), ctx.screen.y()))
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        if self.centre is None:
            self.centre = QVector3D(ctx.world)
            self.work_plane = (QVector3D(self.centre), QVector3D(_UP))
            return
        self.hover_point = QVector3D(ctx.world)
        snap = getattr(ctx, "snap", None)
        self._exact = (getattr(snap, "kind", "none") or "none") not in _FREE_SNAPS
        self._update_metrics(ctx.viewport, (ctx.screen.x(), ctx.screen.y()))
        deg = self.pending_deg()
        if deg is not None:
            self.commit(ctx.viewport, deg)

    def on_value(self, viewport, value) -> bool:
        if isinstance(value, tuple):
            return False
        self.commit(viewport, float(value))
        return True

    # ---- The angle ----------------------------------------------------------
    def _update_metrics(self, viewport, cursor) -> None:
        """Fixed screen-size compass, and whether the cursor is close
        enough to the centre for the arrow to snap to the ticks."""
        centre = self.centre if self.centre is not None else self.hover_point
        w2p = getattr(viewport, "_world_to_pixel", None)
        if w2p is None or centre is None:
            return
        p0 = w2p(centre)
        p1 = w2p(centre + QVector3D(1.0, 0.0, 0.0))
        p2 = w2p(centre + QVector3D(0.0, 1.0, 0.0))
        if p0 is None or p1 is None or p2 is None:
            return
        px = max(math.hypot(p1[0] - p0[0], p1[1] - p0[1]),
                 math.hypot(p2[0] - p0[0], p2[1] - p0[1]))
        if px > 1e-9:
            self._radius = COMPASS_PX / px
        self._snap_ticks = (self.centre is not None and math.hypot(
            cursor[0] - p0[0], cursor[1] - p0[1]) <= COMPASS_PX * SNAP_RADII)

    def pending_deg(self) -> float | None:
        """The north the next click sets: exact on an inference, the 15°
        tick near the compass, 0.1° farther out."""
        if self.centre is None or self.hover_point is None:
            return None
        deg = north_deg_towards(self.centre, self.hover_point)
        if deg is None:
            return None
        if self._snap_ticks:
            return wrap_north_deg(round(deg / TICK_DEG) * TICK_DEG)
        if self._exact:
            return deg
        return wrap_north_deg(round(deg, 1))

    def commit(self, viewport, deg: float) -> None:
        from core.history import SetNorthCommand
        from core.i18n import tr
        from core.units import fmt_angle_deg
        deg = wrap_north_deg(deg)
        scene = viewport.scene
        if abs(deg - scene_north_deg(scene)) > 1e-9:
            viewport.history.execute(SetNorthCommand(deg))
            refresh_north_display(viewport)
        flash = getattr(viewport, "flash_status", None)
        if callable(flash):
            flash(tr("North: {a}").format(a=fmt_angle_deg(deg)), 4000)
        self._reset()
        viewport.update()

    # ---- Preview ------------------------------------------------------------
    def rubber_band_lines(self):
        centre = self.centre if self.centre is not None else self.hover_point
        if centre is None:
            return []
        deg = self.pending_deg() if self.centre is not None else None
        if deg is None:
            deg = scene_north_deg(self._scene)
        segs = compass_segments(centre, self._radius, deg)
        if self.centre is not None and self.hover_point is not None:
            flat = QVector3D(self.hover_point.x(), self.hover_point.y(),
                             self.centre.z())
            segs.append((QVector3D(self.centre), flat))
        return segs

    def value_label(self):
        deg = self.pending_deg()
        if deg is None or self.hover_point is None:
            return None
        from core.units import fmt_angle_deg
        return (fmt_angle_deg(deg), self.hover_point)

    def vcb_caption(self) -> str:
        return "Angle"
