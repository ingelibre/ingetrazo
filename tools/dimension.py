"""Dimension tool (D): place a static linear dimension.

Three clicks, SketchUp-style:
1. first endpoint (snapped to geometry),
2. second endpoint (snapped),
3. move to slide the dimension line off the measured segment, click to place.

While placing, the rubber band previews the extension + dimension lines and the
value label shows the live measurement. The committed dimension lives in
``Scene.dimensions`` and is drawn as a persistent overlay by the viewport.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.dimension import Dimension
from core.history import AddDimensionCommand
from tools.base import Tool, ToolContext


class DimensionTool(Tool):
    name = "Dimension"
    shortcut = "D"

    def __init__(self) -> None:
        self.a: QVector3D | None = None
        self.b: QVector3D | None = None
        self.hover_point: QVector3D | None = None
        # Read by the viewport for the work plane / snap engine (mirrors ``a``).
        self.start_point: QVector3D | None = None
        self.work_plane: tuple[QVector3D, QVector3D] | None = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    # ---- Spatial input ------------------------------------------------------
    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world

    def on_click(self, ctx: ToolContext) -> None:
        p = ctx.world
        if self.a is None:
            self.a = QVector3D(p)
            self.start_point = self.a
            return
        if self.b is None:
            if (p - self.a).length() < 1e-6:
                return  # need two distinct endpoints
            self.b = QVector3D(p)
            return
        # Third click: place the dimension at the current offset.
        offset = Dimension.offset_for_cursor(self.a, self.b, p)
        ctx.viewport.history.execute(AddDimensionCommand(
            Dimension(QVector3D(self.a), QVector3D(self.b), offset)))
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
            offset = Dimension.offset_for_cursor(self.a, self.b, self.hover_point)
            ap, bp = self.a + offset, self.b + offset
            return [(self.a, ap), (self.b, bp), (ap, bp)]  # extension + dim line
        return []

    def value_label(self):
        if self.hover_point is None or self.a is None:
            return None
        if self.b is None:
            mid = (self.a + self.hover_point) * 0.5
            return (f"{(self.hover_point - self.a).length():.2f} m", mid)
        offset = Dimension.offset_for_cursor(self.a, self.b, self.hover_point)
        mid = (self.a + self.b) * 0.5 + offset
        return (f"{(self.b - self.a).length():.2f} m", mid)

    def _reset(self) -> None:
        self.a = None
        self.b = None
        self.start_point = None
        self.work_plane = None
