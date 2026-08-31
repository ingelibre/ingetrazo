# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Image tool: place an imported picture as a reference plane to trace over.

SketchUp's rhythm, and for the same reason — you almost never want a scan at
whatever size the pixels imply, you want it at the size the *drawing* needs:

    click a corner → drag → click again          (size it by eye)
    click a corner → type a width + Enter        (size it exactly)

The picture keeps its proportions the whole time: the drag only decides the
width, and the height follows from the file's aspect ratio, so a plan never
comes out stretched. Holding **Shift** releases that lock for the rare case of
a deliberately distorted fit.

The file is chosen before the tool activates (``File ▸ Import ▸ Image``), which
hands over the cached path and aspect via :meth:`ImageTool.load`.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.history import AddImagePlaneCommand
from core.image_plane import ImagePlane
from core.triangulate import plane_axes
from tools.base import Tool, ToolContext


class ImageTool(Tool):
    name = "Image"
    vcb_label = "Width"
    # Below this the drag is treated as "no size yet" and the click is
    # ignored, so a stray double-click can't commit a degenerate image.
    MIN_SIZE = 1e-4

    def __init__(self) -> None:
        self.path: str | None = None
        self.aspect: float = 1.0
        self.label: str = ""
        self.start_point: QVector3D | None = None
        self.hover_point: QVector3D | None = None
        # Aliased like the other two-click tools so the snap engine's
        # close-polygon path doesn't fire on the first corner.
        self.chain_first_point: QVector3D | None = None
        # (point, normal) of the plane the image is being laid on; the
        # viewport keeps the second corner coplanar with it.
        self.work_plane: tuple[QVector3D, QVector3D] | None = None
        self._free_aspect = False

    # ---- Setup --------------------------------------------------------------
    def load(self, path: str, aspect: float, label: str = "") -> None:
        """Arm the tool with the picture to place. ``aspect`` is height/width
        in pixels — what keeps the placement undistorted."""
        self.path = str(path)
        self.aspect = float(aspect) if aspect and aspect > 0 else 1.0
        self.label = label or ""
        self._reset()

    @property
    def armed(self) -> bool:
        return bool(self.path)

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None
        self.path = None

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        if not self.armed:
            return
        self._free_aspect = bool(ctx.modifiers & Qt.ShiftModifier)
        if self.start_point is None:
            self.start_point = ctx.world
            return
        u, v = self._frame(self.start_point, ctx.world)
        if u.length() < self.MIN_SIZE or v.length() < self.MIN_SIZE:
            return
        self._commit(ctx.viewport, self.start_point, u, v)

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        self._free_aspect = bool(ctx.modifiers & Qt.ShiftModifier)
        ctx.viewport.update()

    def on_value(self, viewport, value) -> bool:
        """Type the width in metres and press Enter — the height follows the
        picture's proportions. A ``width;height`` pair sets both explicitly."""
        if not self.armed or self.start_point is None or self.hover_point is None:
            return False
        if isinstance(value, tuple):
            if len(value) != 2:
                return False
            w, h = value
        else:
            w, h = float(value), None
        if w <= 0.0 or (h is not None and h <= 0.0):
            return False
        au, av = self._axes()
        su, sv = self._signs(self.start_point, self.hover_point)
        height = h if h is not None else w * self.aspect
        self._commit(viewport, self.start_point,
                     au * (su * w), av * (sv * height))
        return True

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- Visual preview -----------------------------------------------------
    def rubber_band_lines(self):
        if not self.armed or self.start_point is None or self.hover_point is None:
            return []
        u, v = self._frame(self.start_point, self.hover_point)
        o = self.start_point
        c = [o, o + u, o + u + v, o + v]
        return [(c[i], c[(i + 1) % 4]) for i in range(4)]

    def value_label(self):
        """Floating ``width × height`` readout while dragging, so the scan can
        be matched against a known dimension of the thing it shows."""
        if not self.armed or self.start_point is None or self.hover_point is None:
            return None
        u, v = self._frame(self.start_point, self.hover_point)
        text = f"{u.length():.2f} × {v.length():.2f} m"
        if self._free_aspect:
            text += "  (libre)"
        return (text, self.start_point + (u + v) * 0.5)

    # ---- Internals ----------------------------------------------------------
    def _axes(self) -> tuple[QVector3D, QVector3D]:
        """In-plane horizontal/vertical axes of the work plane; world X/Y on
        the ground, as the other drawing tools do."""
        if self.work_plane is None:
            return QVector3D(1.0, 0.0, 0.0), QVector3D(0.0, 1.0, 0.0)
        _, normal = self.work_plane
        return plane_axes(normal.normalized())

    def _signs(self, a: QVector3D, b: QVector3D) -> tuple[float, float]:
        """Which quadrant the cursor is heading to, so a typed size grows the
        same way the drag was going."""
        au, av = self._axes()
        d = b - a
        du = QVector3D.dotProduct(d, au)
        dv = QVector3D.dotProduct(d, av)
        return (-1.0 if du < 0 else 1.0), (-1.0 if dv < 0 else 1.0)

    def _frame(self, a: QVector3D, b: QVector3D) -> tuple[QVector3D, QVector3D]:
        """The ``(u, v)`` edge vectors for a drag from ``a`` to ``b``.

        The width comes from the drag; the height is derived from it through
        the file's aspect ratio, which is what keeps the picture undistorted no
        matter how the user sweeps the mouse. Shift takes both from the drag.
        """
        au, av = self._axes()
        d = b - a
        du = QVector3D.dotProduct(d, au)
        dv = QVector3D.dotProduct(d, av)
        if self._free_aspect:
            return au * du, av * dv
        width = abs(du)
        if width < self.MIN_SIZE:
            return au * du, av * dv
        sv = -1.0 if dv < 0 else 1.0
        return au * du, av * (sv * width * self.aspect)

    def _commit(self, viewport, origin: QVector3D,
                u: QVector3D, v: QVector3D) -> None:
        image = ImagePlane(self.path, origin, u, v,
                           aspect=self.aspect, name=self.label)
        viewport.history.execute(AddImagePlaneCommand(image))
        self._reset()
        # One picture per import: disarm so the next click doesn't stamp a
        # second copy (SketchUp drops you back on Select).
        self.path = None
        if hasattr(viewport, "finish_image_placement"):
            viewport.finish_image_placement()
        viewport.update()

    def _reset(self) -> None:
        self.start_point = None
        self.chain_first_point = None
        self.work_plane = None
        self._free_aspect = False
