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
    vcb_label = "Dimensions"

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
        self._commit_rect(ctx.viewport, self._corners(self.start_point, ctx.world))

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        ctx.viewport.update()

    def on_value(self, viewport, value) -> bool:
        """Type exact dimensions: ``"3;2"`` (or ``"3 2"``) + Enter lays a
        3 m × 2 m rectangle, in the quadrant the cursor is currently dragging
        toward. The first number runs along the work plane's horizontal axis,
        the second along its vertical axis."""
        if self.start_point is None or self.hover_point is None:
            return False
        if not (isinstance(value, tuple) and len(value) == 2):
            return False
        w, h = value
        if w <= 0.0 or h <= 0.0:
            return False
        u, v = self._axes()
        du, dv = self._dimensions(self.start_point, self.hover_point)
        su = -1.0 if du < 0 else 1.0  # keep the side the cursor is heading to
        sv = -1.0 if dv < 0 else 1.0
        far = self.start_point + u * (su * w) + v * (sv * h)
        self._commit_rect(viewport, self._corners(self.start_point, far))
        return True

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

    def value_label(self):
        """Floating ``width × height`` readout while dragging (SketchUp's VCB
        dimensions). The viewport draws it near the rectangle's centre."""
        if self.start_point is None or self.hover_point is None:
            return None
        du, dv = self._dimensions(self.start_point, self.hover_point)
        text = f"{abs(du):.2f} × {abs(dv):.2f} m"
        mid = (self.start_point + self.hover_point) * 0.5
        return (text, mid)

    # ---- Internals ----------------------------------------------------------
    def _axes(self) -> tuple[QVector3D, QVector3D]:
        """In-plane horizontal/vertical axes for the current work plane. Without
        a captured plane this is world +X / +Y (the legacy Z=0 layout)."""
        if self.work_plane is None:
            return QVector3D(1.0, 0.0, 0.0), QVector3D(0.0, 1.0, 0.0)
        _, normal = self.work_plane
        return _plane_axes(normal)

    def _dimensions(self, a: QVector3D, b: QVector3D) -> tuple[float, float]:
        """Signed (width, height) of the rectangle spanning ``a``–``b``, measured
        along the work plane's two axes."""
        u, v = self._axes()
        delta = b - a
        return QVector3D.dotProduct(delta, u), QVector3D.dotProduct(delta, v)

    def _corners(self, a: QVector3D, b: QVector3D) -> list[QVector3D]:
        """Four corners of the rectangle spanning ``a``–``b`` on the current
        work plane. Derives two in-plane axes from the face the rectangle was
        started on (so it lies on a vertical or slanted face instead of
        collapsing onto XY); falls back to world X/Y on the Z=0 plane."""
        u, v = self._axes()
        delta = b - a
        du = QVector3D.dotProduct(delta, u)
        dv = QVector3D.dotProduct(delta, v)
        return [a, a + u * du, a + u * du + v * dv, a + v * dv]

    def _commit_rect(self, viewport, corners: list[QVector3D]) -> None:
        segments = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
        # The rectangle owns its face explicitly (the loop spans corner to
        # corner regardless of how its edges get subdivided by crossings), so
        # let the edge builder handle splitting/welding but not auto-facing.
        cmd = build_add_edges(
            viewport.scene,
            segments,
            detect_faces=False,
            extra=[AddFaceCommand(list(corners))],
        )
        viewport.history.execute(cmd)
        self._reset()
        viewport.update()

    def _reset(self) -> None:
        self.start_point = None
        self.chain_first_point = None
        self.work_plane = None
