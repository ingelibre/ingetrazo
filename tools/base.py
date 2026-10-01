# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Base class for IngeTrazo tools and the per-event ``ToolContext`` they receive.

A tool is anything the user activates from the toolbar to interact with the
viewport: draw, modify, select. Both built-in tools and third-party plugins
inherit from :class:`Tool` so they can be registered uniformly.

Spatial tools (line, rectangle, push/pull, select, ...) override
:meth:`on_click`, :meth:`on_hover` and :meth:`on_cancel`. The viewport
raycasts the mouse pixel against the working plane and produces a
:class:`ToolContext` that combines the snapped world point, the raw screen
position, keyboard modifiers and the snap metadata.
"""
from __future__ import annotations

import math

from abc import ABC, abstractmethod
from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.snap import SnapResult


#: Arrow keys → the axis a locked drawing plane is NORMAL to (Right =
#: red, Left = green, Up = blue), and the plane's everyday name.
PLANE_LOCK_KEYS = {int(Qt.Key_Right): "x", int(Qt.Key_Left): "y",
                   int(Qt.Key_Up): "z"}
# The drawing axes (core.axes): the world's at the top level, the open
# group's own inside it (issue #44). The same dict object, kept current.
from core.axes import AXES as PLANE_LOCK_AXES  # noqa: E402
PLANE_LOCK_NAMES = {"x": "YZ", "y": "XZ", "z": "XY"}


class AxisMagnet:
    """The Line tool's axis magnet, for the other drawing tools.

    @pacaeiro, issue #52: «The Draw commands in the group of ARCS and
    SHAPES should also use the magnetic Snaps, like LINE. Except
    Freehand» — and #51 for Text, #50 for Dimension. Same two numbers as
    Line (issue #31): within 3° of an axis from ``start_point`` the point
    lands ON the axis instead of merely lighting the cue, and the axis the
    work plane cannot hold is found in pixels. Alt still switches it off.

    Only a click that is a *direction from the start point* wants this:
    an arc's bulge, a rotated rectangle's height or a dimension's placement
    are measured from somewhere else, and a magnet aimed at the first point
    would bend them. Those tools say when by overriding :meth:`magnet_on`;
    the viewport reads the two properties afresh on every hover.

    Rectangle stays out on purpose: its second click is the opposite
    corner, and a corner pulled onto the axis through the first is a
    rectangle of zero height — every thin rectangle near an axis would
    collapse. Its plane lock and the Shift/arrow locks are its magnets.
    """

    _MAGNET_DEG = 3.0
    _MAGNET_PX = 9.0

    def magnet_on(self) -> bool:
        return True

    @property
    def magnetic_axis_deg(self):
        return self._MAGNET_DEG if self.magnet_on() else None

    @property
    def screen_axis_px(self):
        return self._MAGNET_PX if self.magnet_on() else None


class PlaneLock:
    """Arrow keys BEFORE the first click lock a planar tool (circle,
    polygon, rectangle, the arcs) to a drawing plane: Right = the plane
    normal to X (YZ), Left = normal to Y (XZ), Up = normal to Z (XY); the
    same key again frees it. The classic plane lock (Marco, 2026-09-08:
    «quiero dibujar un círculo en el plano ZX… apretando las teclas de
    desplazamiento»).
    Once the first point is down the arrows are the viewport's linear
    axis lock again, as always. The lock is spent by the shape (or Esc),
    the classic way.

    The DOWN arrow is the classic magenta reference lock: over an
    edge the plane goes PERPENDICULAR to that edge, over a face PARALLEL
    to it; Down again frees it. It is the native way to start a pipe's
    circle on an inclined axis line, then Follow Me it (issue #10,
    @pacaeiro: «I draw lines to represent the axis of the tubes … then
    have to rotate [the circle] to align the normal of the circle's plane
    to the line»)."""

    plane_lock: str | None = None
    #: Down-arrow reference lock: ``(normal, kind)``, kind ``"edge"`` (the
    #: plane perpendicular to the hovered edge) or ``"face"`` (parallel to
    #: the hovered face). Exclusive with ``plane_lock``: the last key wins.
    plane_ref: tuple[QVector3D, str] | None = None
    #: The plane the viewport used for the last cursor hit (`_last_work_plane`).
    #: A shape started on a free point (no face, no lock) has no captured
    #: ``work_plane``; its geometry is laid out on THIS plane instead, which
    #: the viewport picks from the camera — horizontal at working tilts,
    #: vertical facing the camera near the horizon — so the shape follows
    #: the view the classic way (Rafael's review, 2026-09-10: a rectangle
    #: at eye level read «5.74 × 0.00 m», its second point on a vertical
    #: plane while the sides were measured along X/Y).
    hover_plane: tuple | None = None

    def note_plane(self, viewport) -> None:
        """Remember the plane the viewport just hit — call on every hover
        and click before using the point."""
        plane = getattr(viewport, "_last_work_plane", None)
        if plane is not None:
            self.hover_plane = plane

    def drawing_plane(self):
        """``(point, normal)`` the shape is laid out on: the captured or
        locked plane — unless a snapped point says otherwise (see
        ``snapped_plane``) — else the plane of the last hit, else the
        ground."""
        plane = self._own_plane()
        snapped = self.snapped_plane(plane)
        return snapped if snapped is not None else plane

    def _own_plane(self):
        if self.work_plane is not None:
            return self.work_plane
        if self.hover_plane is not None:
            return self.hover_plane
        from core import axes
        return axes.origin(), axes.axis("z")      # the context's ground

    #: How far off the drawing plane a point must be to count as pointing
    #: ELSEWHERE. The free cursor lies on the plane by construction, so
    #: only a snap (endpoint, midpoint…) gets this far.
    OFF_PLANE_TOL = 1e-3

    def plane_points(self) -> list:
        """The points the shape must pass through, first click first — the
        clicked ones and the one under the cursor. A tool opts in to
        ``snapped_plane`` by listing them; the default opts out."""
        return []

    def snapped_plane(self, plane):
        """The plane the shape's points ask for when a SNAPPED one lies off
        ``plane``, or ``None`` to keep ``plane``.

        Filling a window opening (2026-09-29): first point on the midpoint
        of one jamb's depth edge, the next on the midpoint of the other.
        The first click captured the jamb face, where those two points
        share a vertical line: a rectangle «0.00 × 2.41 m», a circle whose
        rim missed the point, arcs that ended on the wrong jamb. Both lie on
        the wall's middle plane, and that is the plane they get:

        - two points: the axis plane that holds both, when exactly one
          does (the span has no component along its normal);
        - three points not in a line: the plane through them.

        An arrow-key lock was asked for explicitly and never yields."""
        if self.plane_lock is not None or self.plane_ref is not None:
            return None
        pts = [p for p in self.plane_points() if p is not None]
        if len(pts) < 2:
            return None
        origin, normal = plane
        n = QVector3D(normal).normalized()
        tol = self.OFF_PLANE_TOL
        if all(abs(QVector3D.dotProduct(p - origin, n)) < tol for p in pts):
            return None
        a = QVector3D(pts[0])
        if len(pts) >= 3:
            through = QVector3D.crossProduct(pts[1] - a, pts[2] - a)
            if through.length() > tol * tol:
                return a, through.normalized()
        from core import axes
        span = pts[-1] - a
        flat = [axes.axis(k) for k in ("x", "y", "z")
                if abs(QVector3D.dotProduct(span, axes.axis(k))) < tol]
        if len(flat) != 1:
            return None     # a true 3D diagonal, or a line along an axis
        return a, flat[0]

    def adopt_snapped_plane(self) -> None:
        """Make the snapped plane the captured one — call when a point that
        is NOT the last is clicked, so the cursor rays for the next point
        land on the new plane instead of the old one."""
        snapped = self.snapped_plane(self._own_plane())
        if snapped is not None:
            self.work_plane = snapped

    #: Radius (circle) / half-side (rectangle) of the cursor preview, px.
    PREVIEW_PX = 22

    def preview_plane(self, viewport, point: QVector3D):
        """The plane the shape WOULD take at ``point`` before the first
        click: the arrow-key lock, else the face under the cursor, else
        the view's — vertical facing the camera near the horizon, flat
        otherwise. The classic tool shows this plane on the cursor (a coloured
        square / ring) so a lock is visible before you commit to it."""
        locked = self.locked_work_plane(point)
        if locked is not None:
            return locked
        plane = getattr(viewport, "_last_work_plane", None)
        from core import axes
        if plane is not None and abs(QVector3D.dotProduct(
                plane[1].normalized(), axes.AXES["z"])) > 0.99:
            near = getattr(viewport, "_near_horizon_vertical", None)
            vertical = near(point) if near is not None else None
            if vertical is not None:
                return vertical
        if plane is not None:
            return QVector3D(point), plane[1]
        return QVector3D(point), axes.axis("z")

    @staticmethod
    def plane_color(normal: QVector3D):
        """RGBA of the axis the plane is normal to (red = YZ, green = XZ,
        blue = XY), or ``None`` for a plane off the axes."""
        from core.snap import AXIS_COLORS
        from core import axes
        n = normal.normalized()
        if not axes.is_world():
            n = axes.to_local(n)             # the context's own colours
        for axis, comp in (("x", n.x()), ("y", n.y()), ("z", n.z())):
            if abs(comp) > 0.99:
                r, g, b = AXIS_COLORS[axis][:3]
                return (r, g, b, 1.0)
        return None

    def lock_color(self):
        """The rubber band's colour while an arrow-key lock is on: the axis
        colour, or the magenta for the Down-arrow reference."""
        if self.plane_ref is not None:
            from core.snap import COLOR_REFERENCE
            return (*COLOR_REFERENCE, 1.0)
        if self.plane_lock is None:
            return None
        from tools.base import PLANE_LOCK_AXES
        return self.plane_color(PLANE_LOCK_AXES[self.plane_lock])

    @staticmethod
    def world_per_pixel(viewport, point: QVector3D, along: QVector3D):
        """Metres per screen pixel at ``point`` along ``along``, or ``None``
        when the viewport cannot project (headless stand-ins)."""
        project = getattr(viewport, "_world_to_pixel", None)
        if project is None:
            return None
        try:
            a = project(point)
            b = project(point + along.normalized() * 0.25)
        except Exception:  # noqa: BLE001 — no projection, no preview
            return None
        if a is None or b is None:
            return None
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        return 0.25 / d if d > 1e-6 else None

    def plane_lock_key(self, viewport, key: int) -> bool:
        if getattr(self, "start_point", None) is not None:
            return False
        if int(key) == int(Qt.Key_Down):
            return self._reference_lock_key(viewport)
        axis = PLANE_LOCK_KEYS.get(int(key))
        if axis is None:
            return False
        self.plane_ref = None
        self.plane_lock = None if self.plane_lock == axis else axis
        flash = getattr(viewport, "flash_status", None)
        if flash is not None:
            from core.i18n import tr
            flash(tr("Drawing plane locked: {plane}",
                     plane=PLANE_LOCK_NAMES[self.plane_lock])
                  if self.plane_lock else tr("Drawing plane free"))
        update = getattr(viewport, "update", None)
        if update is not None:
            update()
        return True

    def _reference_lock_key(self, viewport) -> bool:
        """Down before the first click: lock the plane perpendicular to the
        edge under the cursor (or parallel to the face under it); Down
        again frees it. With nothing under the cursor the classic
        lock does nothing, and neither do we — but the key stays ours, so the
        viewport's linear reference (which is for the SECOND point) does
        not swallow it."""
        from core.i18n import tr
        flash = getattr(viewport, "flash_status", None)
        update = getattr(viewport, "update", None)
        if self.plane_ref is not None:
            self.plane_ref = None
            if flash is not None:
                flash(tr("Drawing plane free"))
        else:
            ref = self.hovered_reference(viewport)
            if ref is None:
                return True
            self.plane_ref = ref
            self.plane_lock = None
            if flash is not None:
                flash(tr("Drawing plane locked: perpendicular to the edge")
                      if ref[1] == "edge" else
                      tr("Drawing plane locked: parallel to the face"))
        if update is not None:
            update()
        return True

    @staticmethod
    def hovered_reference(viewport):
        """``(normal, kind)`` of the reference under the cursor: the edge
        (loose or a group's, as the viewport's hover pick returns it in
        world space) beats the face, the usual convention; ``None`` over
        nothing."""
        edge = getattr(viewport, "_hover_edge", None)
        if edge is not None:
            d = QVector3D(edge.b) - QVector3D(edge.a)
            if d.length() > 1e-9:
                return d.normalized(), "edge"
        pos = getattr(viewport, "_last_mouse_pos", None)
        pick = getattr(viewport, "pick_face_placement", None)
        if pos is not None and pick is not None:
            face, grp = pick(pos.x(), pos.y())
            if face is not None:
                from core.snap import face_plane_world
                _p, n = face_plane_world(face, getattr(grp, "xform", None))
                if n.length() > 1e-9:
                    return n.normalized(), "face"
        return None

    def clear_plane_lock(self) -> None:
        """Both locks off — the shape spent them, or Esc / deactivation."""
        self.plane_lock = None
        self.plane_ref = None

    def locked_work_plane(self, point: QVector3D):
        """``(point, normal)`` of the locked plane through *point* — the
        arrow-key axis plane or the Down-arrow reference — or ``None``
        without a lock."""
        if self.plane_lock is not None:
            return QVector3D(point), PLANE_LOCK_AXES[self.plane_lock]
        if self.plane_ref is not None:
            return QVector3D(point), QVector3D(self.plane_ref[0])
        return None


def loop_normal(corners) -> QVector3D:
    """Newell normal of a closed loop of points."""
    n = QVector3D(0.0, 0.0, 0.0)
    for i in range(len(corners)):
        n += QVector3D.crossProduct(corners[i], corners[(i + 1) % len(corners)])
    return n


def face_the_plane(corners, plane_normal):
    """Wind ``corners`` so the face looks the way its plane does.

    A shape built by walking «along u, then along v» inherits the SIGN of
    that walk: drag the other diagonal and the face comes out backwards.
    Marco saw it as a rectangle landing blue instead of white and read it
    as random, which is what it looks like when it depends on a diagonal
    nobody thinks about (2026-09-18). Measured across the four drags, two
    gave −Z and two +Z; the Rotated Rectangle did the same going
    anticlockwise. Circle and Polygon are safe — they sweep an angle, so
    their winding never changes sign.

    Not cosmetic: the back side travels into the .skp and into the BIM
    tagging, so a wall can arrive inside-out somewhere else.

    A loop lying square to the plane (a rotated rectangle stood upright on
    its base edge) has no side facing it, and is left exactly as it came.
    """
    if plane_normal is None or len(corners) < 3:
        return list(corners)
    dot = QVector3D.dotProduct(loop_normal(corners), plane_normal)
    if dot < -1e-12:
        return [corners[0]] + list(corners)[:0:-1]
    return list(corners)


@dataclass
class ToolContext:
    """Bundle of data a tool needs to react to a viewport event."""

    viewport: object  # forward reference to views.viewport.Viewport
    world: QVector3D
    screen: QPointF
    modifiers: Qt.KeyboardModifiers
    snap: SnapResult


class Tool(ABC):
    name: str = "Unnamed"
    icon: str | None = None
    shortcut: str | None = None
    #: A second key for the same tool, when a key changes hands and the old
    #: one is worth keeping. Push/Pull answers to the usual P and to the U
    #: it had here for a year. It is the SAME action with two shortcuts —
    #: never a second action, which is what Qt kills (tests/test_shortcuts.py).
    shortcut_alt: str | None = None
    #: What the tool does, in a sentence — without its name or its key,
    #: which the tooltip and F3 already show beside it (Blender's
    #: descriptions). English; it goes through ``tr`` where it is shown.
    description: str | None = None
    # Drawing tools snap to geometry and show the snap markers/tooltips
    # (Endpoint, On Edge, On Face, ...). Tools that only pick existing
    # geometry (Select, Push/Pull) set this False: no snap engine, no markers.
    uses_snap: bool = True
    # Tools that support a click-drag rubber-band box (Select). For these the
    # viewport defers the click to release: a tiny drag is a click (on_click),
    # a real drag is a box (on_box_select).
    box_select: bool = False
    # RGBA the viewport uses for this tool's preview lines, overriding the
    # snap-based rubber-band colour. ``None`` keeps the default behaviour;
    # Push/Pull sets the normal edge colour so its box reads as real geometry.
    wireframe_color: tuple[float, float, float, float] | None = None
    # When True the preview lines are depth-tested (hidden-line removal) instead
    # of floating on top. Push/Pull uses this so its forming box hides its own
    # back edges behind its faces, like real geometry; loose drawing tools keep
    # the default (preview always visible on top).
    wireframe_depth_tested: bool = False
    # Caption for the Measurements box (VCB) while this tool is
    # active — "Length", "Dimensions", "Distance". ``None`` hides the box.
    vcb_label: str | None = None

    @abstractmethod
    def on_activate(self, viewport) -> None:
        """Called when the user selects this tool."""

    @abstractmethod
    def on_deactivate(self, viewport) -> None:
        """Called when the user switches to another tool."""

    # ---- High-level spatial input (overridden by drawing tools) -------------
    def on_click(self, ctx: ToolContext) -> None:
        """Left click at ``ctx.world`` (already snapped)."""

    def on_hover(self, ctx: ToolContext) -> None:
        """Mouse moved to ``ctx.world`` without a button pressed."""

    def on_double_click(self, ctx: ToolContext) -> None:
        """Left double-click. Qt swallows the second press, so tools that act
        on it (Push/Pull repeating its last distance) override this; the
        default is to treat it as a plain click so other tools keep their
        click-click rhythm even when the user clicks fast."""
        self.on_click(ctx)

    def on_triple_click(self, ctx: "ToolContext") -> None:
        """Third click in place (select all connected). Defaults to
        a plain click so unaware tools keep their rhythm."""
        self.on_click(ctx)

    def on_box_select(self, viewport, rect, crossing: bool,
                      additive: bool = False, mode: str | None = None) -> None:
        """Rubber-band box released. ``rect`` is ``(x0, y0, x1, y1)`` in screen
        pixels (normalized so x0<=x1, y0<=y1). ``crossing`` is True for a
        right-to-left drag (select anything the box touches) and False for a
        left-to-right drag (select only what's fully enclosed). ``mode`` is how
        the catch joins the selection — "replace" / "add" / "toggle" /
        "remove", from the keyboard modifiers (see
        ``tools.select.selection_mode``); ``additive`` is the older two-state
        spelling, kept for tools that only know it. Only tools with
        ``box_select = True`` receive this."""

    def drag_plane(self, viewport):
        """``(point, normal)`` of the plane the cursor should be read on
        while this tool is mid-operation, or ``None`` to leave the choice
        to the viewport (captured face, start point, ground).

        The viewport turns every pixel into a world point by hitting a
        plane, and hands the tool NOTHING — no hover, no click — when the
        ray misses it. A tool whose operation runs along a LINE (Push/Pull
        along its normal) only ever needs the pixel, and the ground stops
        answering the moment the cursor crosses the horizon: Rafael pulled
        a box up with the camera at ground level, the box froze at the
        horizon, and the click on its top never arrived (2026-09-16). Such a
        tool answers with a plane that contains its line and faces the
        camera, which the ray always hits."""
        return None

    def on_cancel(self, viewport) -> None:
        """Esc pressed — abandon any in-progress operation."""

    def on_release(self, viewport) -> None:
        """Left button released. Tools that act on press-drag-release strokes
        (the Eraser) override this; the default is a no-op, so click-driven
        tools are unaffected."""

    # ---- Key dispatch -------------------------------------------------------
    def on_key(self, viewport, key: int, modifiers: Qt.KeyboardModifiers) -> bool:
        """Tool gets first shot at the key. Return True to consume it."""
        return False

    def on_value(self, viewport, value: float) -> bool:
        """User typed a numeric length and pressed Enter (VCB style).

        Tools that accept a numeric value (line length, rectangle dimensions,
        circle radius, ...) override this and return True on success. The
        viewport handles digit buffering and dispatch; tools only need to
        consume the value.
        """
        return False

    def status_clause(self) -> str:
        """A short clause this tool adds to the status bar, or "".

        The classic tool keeps modifiers ON SCREEN the whole time the tool is
        active — «Ctrl = Líneas guía del ciclo/Puntos guía/Medida» sits
        there next to the instruction — instead of flashing them once when
        you press the key. A flash tells you what just happened; this tells
        you what you can do, and which way it is set right now (Marco,
        2026-09-17)."""
        return ""

    # ---- Visual feedback hooks ---------------------------------------------
    def rubber_band_lines(self):
        """Return ``[(a, b), ...]`` line segments to draw as the live preview.

        ``LineTool`` returns a single segment; ``RectangleTool`` returns four.
        The viewport renders whatever the active tool returns; tools that
        don't preview anything default to an empty list.
        """
        return []


    def guide_preview_lines(self):
        """``[(a, b), ...]`` — the guide LINES this tool is about to leave,
        drawn dashed like a real guide while the cursor moves (#89,
        @pacaeiro). Long segments are fine: the viewport clips them."""
        return []
    def preview_faces(self):
        """Return ``Face`` objects to render shaded as a live solid preview.

        Push/Pull uses this so the extruded box appears filled while you drag,
        the way users expect the solid forming — not just its wireframe. The
        viewport triangulates and draws them depth-tested every frame; tools
        that have no solid preview default to an empty list.
        """
        return []
