# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
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

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.i18n import tr
from core.history import AddFaceCommand
from tools.base import face_the_plane, PlaneLock, Tool, ToolContext
from core.units import fmt_pair


def _plane_axes(normal: QVector3D) -> tuple[QVector3D, QVector3D]:
    """Two orthonormal in-plane axes derived from a plane normal.

    The first axis (``u``) is world +X projected onto the plane (or +Y if
    the plane normal is nearly +X, to avoid the degenerate projection).
    The second axis (``v``) is ``normal × u``. The pair lets us lay out a
    rectangle on any plane while staying close to the world axes — so a
    rectangle on the top of a box still feels axis-aligned, and on a
    vertical wall ``u`` runs horizontally and ``v`` runs up/down.
    """
    from core import axes
    if not axes.is_world():
        return axes.plane_axes(normal)    # inside a turned group (#44)
    n = normal.normalized()
    ref = QVector3D(1.0, 0.0, 0.0)
    u = ref - n * QVector3D.dotProduct(ref, n)
    if u.length() < 0.1:
        ref = QVector3D(0.0, 1.0, 0.0)
        u = ref - n * QVector3D.dotProduct(ref, n)
    u = u.normalized()
    v = QVector3D.crossProduct(n, u).normalized()
    return u, v


# No AxisMagnet here, deliberately (issue #52): the second click is the
# OPPOSITE CORNER, and a corner pulled onto the axis through the first is a
# rectangle of zero height. See ``tools.base.AxisMagnet``.
class RectangleTool(PlaneLock, Tool):
    name = "Rectangle"
    shortcut = "R"
    description = "Draw a rectangle from two opposite corners."
    vcb_label = "Dimensions"
    # Only a width AND a height mean something here, so "200,100" is two
    # values (the list comma, #152), not the decimal 200.1.
    vcb_comma_lists = True
    # Within this fraction of the longer side, the two sides count as equal and
    # the rectangle snaps to a perfect square ("Cuadrado").
    SQUARE_TOL = 0.04

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None
        self.hover_point: QVector3D | None = None
        #: Ctrl toggles the other classic way of drawing a rectangle: the
        #: first click is the CENTRE and the second a corner (issue #39,
        #: @pacaeiro). The cursor badge says which way is on.
        self._from_center: bool = False
        # Aliased so the snap engine's close-polygon path doesn't fire on
        # the rectangle's first corner.
        self.chain_first_point: QVector3D | None = None
        # (point, normal) of the face the rectangle was started on, if any.
        # The viewport reads this to keep the opposite corner coplanar.
        self.work_plane: tuple[QVector3D, QVector3D] | None = None
        self._viewport = None
        self._shift_square_lock = False
        self._arrow_square_lock = False

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()
        self._set_from_center(viewport, False)   # a pick-up starts corner-wise

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        self.note_plane(ctx.viewport)
        if self.start_point is None:
            self.start_point = ctx.world
            if self.work_plane is None:
                self.work_plane = self.locked_work_plane(ctx.world)
            return
        # The plane may follow the far corner (``drawing_plane``), so it
        # must be judged on the point being clicked, not the last hover.
        self.hover_point = ctx.world
        anchor, far = self._span(ctx.world)
        du, dv = self._dimensions(anchor, far)
        if abs(du) < 1e-6 or abs(dv) < 1e-6:
            # A side of zero (the second corner on the first's row or
            # column, an edge snap along one axis): nothing is drawn.
            # Committing it raised a degenerate-edge error deep in the
            # history (Marco's log, 2026-09-14) and rolled back noisily.
            flash = getattr(ctx.viewport, "flash_status", None)
            if flash is not None:
                flash(self._degenerate_reason(ctx.world))
            return
        self._commit_rect(ctx.viewport, self._corners(anchor, far))

    def _degenerate_reason(self, world) -> str:
        """Why the rectangle came out flat, in the words that actually help.

        «Pick the opposite corner» is a lie when the user DID pick it: Marco
        put the two base corners of a wall in and got told off (2026-09-18).
        The real cause was the plane. Clicking the first corner while
        hovering the wall's vertical face locks the rectangle to that
        vertical plane, where those two corners share a line — 4.000 x 0.000
        — so a step on the ground cannot be drawn at all. The Rotated
        Rectangle works because it takes its plane from the edge you draw,
        not from the face under the cursor.

        So: if the far corner lies OFF the locked plane, say that, and name
        the arrow that picks the plane where the two points do span a
        rectangle (the axis the span barely uses).
        """
        from tools.base import PLANE_LOCK_AXES, PLANE_LOCK_NAMES
        if self.work_plane is None or self.start_point is None:
            return tr("Rectangle needs two sides — pick the opposite corner")
        origin, normal = self.work_plane
        n = QVector3D(normal).normalized()
        off = abs(QVector3D.dotProduct(world - origin, n))
        if off < 1e-3:
            return tr("Rectangle needs two sides — pick the opposite corner")
        span = world - self.start_point
        axis = min(("x", "y", "z"),
                   key=lambda a: abs(QVector3D.dotProduct(
                       span, PLANE_LOCK_AXES[a])))
        arrow = {"x": "\u2192", "y": "\u2190", "z": "\u2191"}[axis]
        return tr(
            "That corner is off the drawing plane, so the rectangle has no "
            "width. Press {arrow} for the {plane} plane.",
            arrow=arrow, plane=PLANE_LOCK_NAMES[axis])

    def on_hover(self, ctx: ToolContext) -> None:
        self.note_plane(ctx.viewport)
        self._viewport = ctx.viewport
        # First: the plane follows a snapped far corner (``plane_points``),
        # so the square test below must see this point, not the last one.
        self.hover_point = ctx.world
        square_inference = (self.start_point is not None
                            and self._square_corner(
                                self.start_point, ctx.world)[1])
        if not (ctx.modifiers & Qt.ShiftModifier):
            self._shift_square_lock = False
        elif square_inference:
            self._shift_square_lock = True
        self.wireframe_color = self.lock_color()
        ctx.viewport.update()

    def on_value(self, viewport, value) -> bool:
        """Type exact dimensions: ``"3;2"`` (or ``"3 2"``) + Enter lays a
        3 m × 2 m rectangle, in the quadrant the cursor is currently dragging
        toward. The first number runs along the work plane's horizontal axis,
        the second along its vertical axis."""
        if self.start_point is None or self.hover_point is None:
            return False
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not self._square_locked():
                return False
            w = h = value
        elif isinstance(value, tuple) and len(value) == 2:
            w, h = value
        else:
            return False
        if w <= 0.0 or h <= 0.0:
            return False
        u, v = self._axes()
        du, dv = self._dimensions(self.start_point, self.hover_point)
        su = -1.0 if du < 0 else 1.0  # keep the side the cursor is heading to
        sv = -1.0 if dv < 0 else 1.0
        if self._from_center:
            # Typed sizes are the WHOLE width and height, centred here.
            half = u * (su * w * 0.5) + v * (sv * h * 0.5)
            anchor, far = self.start_point - half, self.start_point + half
        else:
            anchor, far = self.start_point, self.start_point + u * (su * w) + v * (sv * h)
        self._commit_rect(viewport, self._corners(anchor, far))
        return True

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- Visual preview -----------------------------------------------------
    def rubber_band_lines(self):
        if self.hover_point is None:
            return []
        if self.start_point is None:
            return self._cursor_preview()
        anchor, far = self._span(self.hover_point)
        is_square = self._square_corner(anchor, far)[1]
        c = self._corners(anchor, far)
        lines = [
            (c[0], c[1]),
            (c[1], c[2]),
            (c[2], c[3]),
            (c[3], c[0]),
        ]
        # A diagonal across the square is the "Square" cue (preview only).
        if is_square:
            lines.append((c[0], c[2]))
        return lines

    def value_label(self):
        """Floating ``width × height`` readout while dragging (the VCB
        dimensions). The viewport draws it near the rectangle's centre. When the
        sides are equal it reads "Cuadrado"."""
        if self.start_point is None or self.hover_point is None:
            return None
        anchor, far = self._span(self.hover_point)
        is_square = self._square_corner(anchor, far)[1]
        du, dv = self._dimensions(anchor, far)
        text = fmt_pair(abs(du), abs(dv))
        if is_square:
            text += "  (Cuadrado)"
        mid = (anchor + far) * 0.5
        return (text, mid)

    def _span(self, cursor: QVector3D) -> tuple[QVector3D, QVector3D]:
        """The two opposite corners the cursor asks for: from the first
        click to the cursor, or — from the centre — the cursor and its
        mirror through the first click.

        The square nudge is applied to the CURSOR relative to the anchor
        (the first click) first, and only then mirrored. Anchoring on the
        centre is what keeps a centred square a true square: nudging the
        mirror instead (holding it fixed while the cursor moved) grew the
        wrong side, so a 4.00 x 4.10 m rectangle came out labelled
        "Cuadrado"."""
        far, _sq = self._square_corner(
            self.start_point, cursor, force=self._square_locked())
        if self._from_center:
            return self.start_point * 2.0 - far, far
        return self.start_point, far

    def _set_from_center(self, viewport, on: bool) -> None:
        self._from_center = bool(on)
        # The badge on the pencil says which way is on (two icons, as
        # @pacaeiro proposed: one per method).
        self.icon = "rectangle_center" if self._from_center else "rectangle"
        apply = getattr(viewport, "_apply_tool_cursor", None)
        if callable(apply):
            apply()

    # ---- Internals ----------------------------------------------------------
    def _cursor_preview(self):
        """The little square on the cursor before the first corner,
        lying on the plane the rectangle would take (an arrow-key lock in
        its axis colour, a face under the cursor, or the view's plane)."""
        vp = self._viewport
        if vp is None:
            return []
        point, normal = self.preview_plane(vp, self.hover_point)
        u, v = _plane_axes(normal)
        scale = self.world_per_pixel(vp, self.hover_point, u)
        if scale is None:
            return []
        h = 0.5 * self.PREVIEW_PX * scale
        c = self.hover_point
        pts = [c + u * h + v * h, c - u * h + v * h, c - u * h - v * h, c + u * h - v * h]
        return [(pts[i], pts[(i + 1) % 4]) for i in range(4)]

    def plane_points(self):
        """First corner and far corner: a far corner snapped off the plane
        picks the axis plane that holds both (``PlaneLock.snapped_plane``)
        — how a window opening gets filled from jamb to jamb."""
        if self.start_point is None:
            return []
        return [self.start_point, self.hover_point]

    def _axes(self) -> tuple[QVector3D, QVector3D]:
        """In-plane horizontal/vertical axes for the drawing plane: the
        captured / locked one, else the plane of the last hit (which follows
        the camera), else world +X / +Y."""
        _, normal = self.drawing_plane()
        return _plane_axes(normal)

    def _dimensions(self, a: QVector3D, b: QVector3D) -> tuple[float, float]:
        """Signed (width, height) of the rectangle spanning ``a``–``b``, measured
        along the work plane's two axes."""
        u, v = self._axes()
        delta = b - a
        return QVector3D.dotProduct(delta, u), QVector3D.dotProduct(delta, v)

    def _square_corner(self, a: QVector3D, b: QVector3D,
                       force: bool = False) -> tuple[QVector3D, bool]:
        """If the rectangle spanning ``a``–``b`` is within ``SQUARE_TOL`` of being
        square, return the opposite corner nudged to a perfect square plus
        ``True``; otherwise return ``b`` unchanged plus ``False``. The square
        side is the longer of the two, so the shape grows to square (never
        collapses), keeping the quadrant the cursor is dragging toward."""
        u, v = self._axes()
        du, dv = self._dimensions(a, b)
        adu, adv = abs(du), abs(dv)
        if adu < 1e-6 or adv < 1e-6:
            return b, False
        if force or abs(adu - adv) <= self.SQUARE_TOL * max(adu, adv):
            side = max(adu, adv)
            far = a + u * math.copysign(side, du) + v * math.copysign(side, dv)
            return far, True
        return b, False

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
        u, v = self._axes()
        corners = face_the_plane(corners, QVector3D.crossProduct(u, v))
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


    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Control:
            # Ctrl = corner ⇄ centre, like Move's Ctrl = copy (issue #39).
            self._set_from_center(viewport, not self._from_center)
            flash = getattr(viewport, "flash_status", None)
            if callable(flash):
                flash(tr("Rectangle from the centre") if self._from_center
                      else tr("Rectangle from a corner"))
            hint = getattr(viewport, "refresh_status_hint", None)
            if callable(hint):
                hint()
            return True
        if key == Qt.Key_Down and self.start_point is not None:
            if self._arrow_square_lock:
                self._arrow_square_lock = False
                viewport.update()
                return True
            if (self.hover_point is not None
                    and self._square_corner(self.start_point,
                                            self.hover_point)[1]):
                self._arrow_square_lock = True
                viewport.update()
                return True
        return self.plane_lock_key(viewport, key)

    def _reset(self) -> None:
        self.start_point = None
        self.chain_first_point = None
        self.work_plane = None
        self.hover_plane = None
        self.wireframe_color = None
        self._shift_square_lock = False
        self._arrow_square_lock = False
        self.clear_plane_lock()

    def _square_locked(self) -> bool:
        return self._shift_square_lock or self._arrow_square_lock
