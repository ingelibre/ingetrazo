"""Rectangle tool: two clicks define opposite corners on the work plane.

Output is a closed loop of four edges, axis-aligned to the world X / Y
axes (Z=0 work plane). All four edges are committed as a single
:class:`CompoundCommand` so Undo treats the rectangle as one atomic step.

Notes:
- Axis lock and reference lock are accepted by the snap engine but rarely
  useful for a rectangle (they degenerate it). The second corner does
  benefit from endpoint / origin snaps to align with existing geometry.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import AddFaceCommand
from tools.base import Tool, ToolContext


def _plane_axes(normal: QVector3D) -> tuple[QVector3D, QVector3D]:
    """Two orthonormal in-plane axes derived from a plane normal.

    The first axis (``u``) is world +X projected onto the plane (or +Y if
    the plane normal is nearly +X, to avoid the degenerate projection).
    The second axis (``v``) is ``normal × u``. The pair lets us lay out a
    rectangle on any plane while staying close to the world axes — so a
    rectangle on the top of a box still feels axis-aligned, and on a
    vertical wall ``u`` runs horizontally and ``v`` runs up/down.
    """
    n = normal.normalized()
    ref = QVector3D(1.0, 0.0, 0.0)
    u = ref - n * QVector3D.dotProduct(ref, n)
    if u.length() < 0.1:
        ref = QVector3D(0.0, 1.0, 0.0)
        u = ref - n * QVector3D.dotProduct(ref, n)
    u = u.normalized()
    v = QVector3D.crossProduct(n, u).normalized()
    return u, v


class RectangleTool(Tool):
    name = "Rectangle"
    shortcut = "R"

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None
        self.hover_point: QVector3D | None = None
        # Aliased so the snap engine's close-polygon path doesn't fire on
        # the rectangle's first corner.
        self.chain_first_point: QVector3D | None = None
        # (point, normal) of the face the rectangle was started on, if any.
        # The viewport reads this to keep the opposite corner coplanar.
        self.work_plane: tuple[QVector3D, QVector3D] | None = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        if self.start_point is None:
            self.start_point = ctx.world
            return
        corners = self._corners(self.start_point, ctx.world)
        segments = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
        # The rectangle owns its face explicitly (the loop spans corner to
        # corner regardless of how its edges get subdivided by crossings), so
        # let the edge builder handle splitting/welding but not auto-facing.
        cmd = build_add_edges(
            ctx.viewport.scene,
            segments,
            detect_faces=False,
            extra=[AddFaceCommand(list(corners))],
        )
        ctx.viewport.history.execute(cmd)
        self._reset()
        ctx.viewport.update()

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        ctx.viewport.update()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- Visual preview -----------------------------------------------------
    def rubber_band_lines(self):
        if self.start_point is None or self.hover_point is None:
            return []
        c = self._corners(self.start_point, self.hover_point)
        return [
            (c[0], c[1]),
            (c[1], c[2]),
            (c[2], c[3]),
            (c[3], c[0]),
        ]

    # ---- Internals ----------------------------------------------------------
    def _corners(self, a: QVector3D, b: QVector3D) -> list[QVector3D]:
        """Four corners of the rectangle spanning ``a``–``b`` on the current
        work plane.

        Without a captured plane we fall back to the legacy XY layout (corners
        share ``a.z()``). When the rectangle was started on a face, we derive
        two orthonormal in-plane axes from the face's normal and use them to
        place the two intermediate corners — so a rectangle on a vertical or
        slanted face lies on that face instead of collapsing onto the XY
        plane.
        """
        if self.work_plane is None:
            z = a.z()
            return [
                QVector3D(a.x(), a.y(), z),
                QVector3D(b.x(), a.y(), z),
                QVector3D(b.x(), b.y(), z),
                QVector3D(a.x(), b.y(), z),
            ]
        _, normal = self.work_plane
        u, v = _plane_axes(normal)
        delta = b - a
        du = QVector3D.dotProduct(delta, u)
        dv = QVector3D.dotProduct(delta, v)
        return [
            a,
            a + u * du,
            a + u * du + v * dv,
            a + v * dv,
        ]

    def _reset(self) -> None:
        self.start_point = None
        self.chain_first_point = None
        self.work_plane = None
