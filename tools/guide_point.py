# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Guide Point tool (issue #616): one click leaves a guide POINT.

A guide point is the reference mark the Tape already leaves in its
«guide points» mode: a :class:`core.guide.Guide` with no direction, drawn
as a small dashed cross. Here it takes a single click instead of a
measured pull, wherever the snap lands — a corner, a midpoint, a centre,
a spot on a face, the crossing of two guides.

Because it is the very same object, it behaves like every other guide
and nothing new had to be taught to the rest of the program: it snaps,
is selected, moved, rotated and erased, undone, saved in the ``.igz``,
hidden with View ▸ Guides and with its layer, and swept by
Edit ▸ Delete Guides.

Typing ``x;y;z`` in the Measurements box places it at those coordinates,
read on the drawing axes (inside an open group, the group's own).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen, QVector3D

from core.guide import Guide
from core.history import AddGuideCommand
from tools.base import Tool, ToolContext


class GuidePointTool(Tool):
    name = "Guide Point"
    icon = "guide_point"
    description = ("Leave a guide point with one click, on any point you "
                   "snap to; or type x;y;z for exact coordinates.")
    vcb_label = "Position"
    #: The cursor's little +: this tool leaves something behind, as the
    #: Tape and the Protractor say in guide mode.
    cursor_plus = True

    def __init__(self) -> None:
        self.hover_point: QVector3D | None = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self.hover_point = None

    def on_deactivate(self, viewport) -> None:
        self.hover_point = None

    def on_cancel(self, viewport) -> None:
        viewport.update()

    # ---- Input --------------------------------------------------------------
    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = QVector3D(ctx.world)
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        self.place(ctx.viewport, ctx.world)

    def on_value(self, viewport, value) -> bool:
        """``x;y;z`` puts the point at those coordinates on the drawing
        axes. A lone number names no point, so it is left alone."""
        if not isinstance(value, tuple) or len(value) != 3:
            return False
        try:
            x, y, z = (float(c) for c in value)
        except (TypeError, ValueError):
            return False
        from core import axes
        where = axes.origin() + axes.to_world(QVector3D(x, y, z))
        return self.place(viewport, where)

    def place(self, viewport, where: QVector3D) -> bool:
        """Leave a guide point at ``where``; False when it is no point at
        all (NaN from a degenerate pick, #723)."""
        guide = Guide(QVector3D(where))
        if not guide.is_finite():
            return False
        viewport.history.execute(AddGuideCommand(guide))
        flash = getattr(viewport, "flash_status", None)
        if callable(flash):
            from core.i18n import tr
            from core.units import fmt_len_fine
            from core import axes
            local = axes.to_local(guide.point - axes.origin())
            flash(tr("Guide point at ({x}; {y}; {z})").format(
                x=fmt_len_fine(local.x()), y=fmt_len_fine(local.y()),
                z=fmt_len_fine(local.z())), 3000)
        viewport.update()
        return True

    # ---- Preview ------------------------------------------------------------
    def draw_overlay(self, viewport, painter) -> None:
        """The cross the click will leave, under the cursor — the same
        dashed cross a guide point is drawn with."""
        if self.hover_point is None:
            return
        pixel = viewport._world_to_pixel(self.hover_point)
        if pixel is None:
            return
        painter.save()
        try:
            pen = QPen(QColor(70, 90, 120), 1, Qt.DashLine)
            pen.setDashPattern([3.0, 2.0])
            painter.setPen(pen)
            x, y = pixel
            painter.drawLine(QPointF(x - 5, y), QPointF(x + 5, y))
            painter.drawLine(QPointF(x, y - 5), QPointF(x, y + 5))
        finally:
            painter.restore()
