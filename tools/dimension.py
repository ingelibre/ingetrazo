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

from PySide6.QtGui import QVector3D

from core.dimension import Dimension
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
        self.hover_axis: QVector3D | None = None
        # Read by the viewport for the work plane / snap engine (mirrors ``a``).
        self.start_point: QVector3D | None = None
        self.work_plane: tuple[QVector3D, QVector3D] | None = None

        # 17.10.26 BastelBaus: when snapped to a dimension, this is the 
        #                      vector which should be used for the dimension
        self.ref_axis: QVector3D | None = None

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

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = self._frontal(ctx, ctx.world)
        #self.hover_point = QVector3D(ctx.world)
        self.hover_point = QVector3D(ctx.snap.point)
        # 19.10.26 BastelBaus store the snap information
        print("SNAP-HOOVER:",ctx.snap)
        self.hover_axis = ctx.snap.axis if ctx.snap.kind == "axis" else None

    def on_click(self, ctx: ToolContext) -> None:
        p = ctx.world
        print("SNAP:",ctx.snap)

        if self.a is None:

            # 17.10.26 BastelBaus: clicking on an edge directly creates
            #                      the dimension from both corners of the edge
            if ctx.snap.kind == "on_edge" and ctx.snap.edge is not None and \
               ctx.snap.edge.a is not None and ctx.snap.edge.b is not None:
                self.a = QVector3D( ctx.snap.edge.a )
                self.b = QVector3D( ctx.snap.edge.b )
            else:
                self.a = QVector3D(p)

            self.start_point = self.a
            return
            
        if self.b is None:

            # 17.10.26 BastelBaus: clicking on an point not directly on the
            #                      dimension line, the snap piont should be 
            #                      kept as anchor and the direction must 
            #                      be stored
            if ctx.snap.kind == "from_point" and ctx.snap.guide is not None:
                self.ref_axis = ctx.snap.axis
                p = ctx.snap.guide[0]

            p = self._frontal(ctx, p)
            if (p - self.a).length() < 1e-6:
                return  # need two distinct endpoints
            self.b = QVector3D(p)
            return

        # Third click: place the dimension where the cursor asks — aligned,
        # or linear along an axis when pulled past the ends (issue #50).

        # 19.10.26 BastelBaus store the snap information
        axis = ctx.snap.axis if ctx.snap.kind == "axis" else None
        proposed_dim = self._proposed(p,axis = axis)
        print("ProposedDIM:\n",str(proposed_dim))
        ctx.viewport.history.execute(AddDimensionCommand(proposed_dim))
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
            #ap, bp = new_dim.line_points()
            #return [(self.a, ap), (self.b, bp), (ap, bp)]  # extension + dim line

            # 17.10.26 BastelBaus: draw line from anchors over extension points 
            #                      and line points
            ndim = self._proposed(self.hover_point, self.hover_axis)
            return [ (ndim.a, ndim.extension_a), (ndim.extension_a, ndim.line_point_a),
                     (ndim.line_point_a,ndim.line_point_b),(ndim.line_point_b,ndim.extension_b),
                     (ndim.extension_b,ndim.b)
                   ]                                     
        return []

    def value_label(self):
        if self.hover_point is None or self.a is None:
            return None
        if self.b is None:
            mid = (self.a + self.hover_point) * 0.5
            return (fmt_len((self.hover_point - self.a).length()), mid)
        proposed = self._proposed(self.hover_point)
        return (fmt_len(proposed.value()), proposed.midpoint())

    def _proposed(self, cursor: QVector3D, axis:str|None = None) -> Dimension:
        """The dimension the current cursor would place (preview and
        commit share it, so what you see is what you get)."""
        
        print(f"_proposed:\n {self.a=}\n {self.b=}\n {cursor=}\n {self.hover_point=}\n {self.ref_axis=}, {axis=}\n {self.hover_axis=}\n")

        if self.ref_axis is not None:
            # 17.10.26 BastelBaus: if snapped to an exis, use this axis! 
            offset = cursor - self.a
            print(f" {offset=}")
            return Dimension(QVector3D(self.a), QVector3D(self.b), offset, axis=self.ref_axis, axis_on_extension=True)

        else:
            #offset, axis = Dimension.placement_for_cursor(self.a, self.b, cursor)
            offset, ax = Dimension.placement_for_cursor(self.a, self.b, cursor)
            offset = cursor - (self.a + self.b) * 0.5

                        
            _AXIS_VECTORS = {
                "x": QVector3D(1.0, 0.0, 0.0),
                "y": QVector3D(0.0, 1.0, 0.0),
                "z": QVector3D(0.0, 0.0, 1.0),
            }


            ax = _AXIS_VECTORS.get(self.hover_axis,None)
            if ax:
                offset = ax * QVector3D.dotProduct(offset,ax)
            print(f" {offset=}")
            print(f" {axis=}")
            return Dimension(QVector3D(self.a), QVector3D(self.b), offset, axis=axis)

        

    def _reset(self) -> None:
        self.a = None
        self.b = None
        self.start_point = None
        self.work_plane = None
        self.ref_axis = None
