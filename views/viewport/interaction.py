# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Input: tools, cursors, navigation, mouse, wheel, keys and focus."""
from __future__ import annotations

import math
import time as _time_mod
from typing import Optional
from PySide6.QtCore import QEvent, Qt, QPointF, QTimer
from PySide6.QtGui import QVector3D
from core.i18n import tr
from tools.base import Tool
from tools.select import selection_mode
from views.viewport._support import _PERF, _plog, _HoverEvent, _ray_aabb_span, _is_chord


class InteractionMixin:
    """Input: tools, cursors, navigation, mouse, wheel, keys and focus."""

    def _zoom_to_box(self, start: QPointF, end: QPointF) -> None:
        """Zoom the camera so the dragged screen rectangle fills the view
        (Zoom Window). Re-centres on the box's centre and scales the distance
        by the fraction of the viewport the box covers."""
        bw, bh = abs(end.x() - start.x()), abs(end.y() - start.y())
        if bw < 6 or bh < 6:          # a click, not a real box → ignore
            return
        cx, cy = (start.x() + end.x()) / 2.0, (start.y() + end.y()) / 2.0
        focus = self._world_under_cursor(cx, cy)
        if focus is not None:
            self.camera.target = focus
        frac = max(bw / max(self.width(), 1), bh / max(self.height(), 1))
        frac = max(frac, 0.04)        # don't zoom past a sane limit in one go
        from core.camera import MAX_DISTANCE
        self.camera.distance = max(
            self.camera.min_distance(),
            min(self.camera.distance * frac, MAX_DISTANCE))
        self.update()

    @classmethod
    def _tool_busy_for_delete(cls, tool) -> bool:
        """``_tool_busy`` plus the per-tool state that means "an operation
        holds geometry": Offset's / Push-Pull's base face, Follow Me's
        profile, Fillet's picked edges or live sizing. Delete waits then."""
        if cls._tool_busy(tool):
            return True
        return any(getattr(tool, attr, None)
                   for attr in ("base_face", "_profile", "sizing", "edges"))

    @staticmethod
    def _tool_busy(tool) -> bool:
        """Whether the active tool has an operation in progress that Esc should
        cancel before falling through to clearing the selection: an unfinished
        chain (start_point / nodes), a drag (dragging / grab / node edit), or
        an eraser stroke.

        The POINTS are tested against None, not for truth: ``QVector3D(0, 0,
        0)`` is falsy in PySide6 (the house gotcha), so a line or a move
        started exactly ON THE ORIGIN read as "nothing in progress" — Esc
        would skip straight to clearing the selection instead of cancelling
        it. Found on 2026-09-17 writing the Alt gate, which asks this same
        question."""
        for attr in ("start_point", "grab"):
            if getattr(tool, attr, None) is not None:
                return True
        for attr in ("dragging", "_drag", "_stroke"):
            if getattr(tool, attr, None):
                return True
        if getattr(tool, "nodes", None):
            return True
        return False

    # ---- Tool management ----------------------------------------------------
    def set_active_tool(self, tool: Optional[Tool]) -> None:
        if self.active_tool is tool and self.nav_mode is None:
            # Picking the tool you already hold starts it over, the classic
            # behaviour: the first point is released, the locks let go. Issue
            # #34 (@pacaeiro): «If I'm drawing a line and have the first
            # point defined… if I press (L) again, the command should
            # reset». It used to be a no-op.
            if tool is not None:
                tool.on_cancel(self)
            self.inference.clear_references()
            self.axis_lock = None
            self._shift_lock = None
            self.reference_edge = None
            self.reference_mode = None
            self.linear_inference_mode = "all"
            self._refresh_snap()
            return
        # Picking a drawing tool always leaves camera-navigation mode — and
        # any camera drag it was in the middle of.
        self.nav_mode = None
        self._last_pos = None
        self._orbit_pivot = None
        self._pan_mode = False
        self._look_drag = None
        self.unsetCursor()
        if self.active_tool is not None:
            self.active_tool.on_deactivate(self)
        self.active_tool = tool
        self.linear_inference_mode = "all"   # the toggle lasts one operation
        # …and so does the arrow-key axis lock (issue #30). It was the one
        # sticky state this reset forgot, so a lock taken while drawing a
        # line was still on — label and all — after switching to Rectangle,
        # quietly constraining a tool that never asked for it.
        self.axis_lock = None
        self._hover_entity = None  # stale highlight from the previous tool
        self.inference.clear_references()
        if tool is not None:
            tool.on_activate(self)
        self._apply_tool_cursor()
        self.measurementChanged.emit(self._measurement_text())
        self.update()

    def _apply_tool_cursor(self) -> None:
        """The pointer becomes the active tool's icon; Select and
        unknown tools keep the standard arrow.

        A tool that does something else under a modifier says so with the
        pointer: Paint holds Alt to SAMPLE a face's material instead of
        painting it, and the cursor swaps the bucket for an eyedropper while
        it is down."""
        from PySide6.QtWidgets import QApplication
        from views.icons import tool_cursor
        icon = getattr(self.active_tool, "icon", None)
        if icon == "paint":
            from tools.paint import PaintTool
            # ``keyboardModifiers()`` is the state as of the LAST event
            # delivered: on the Alt press it did not include Alt yet and on
            # the release it still did, so the pointer flipped once per
            # tap instead of following the key (issue #47, @pacaeiro: «the
            # cursor is acting as a toggle button»). The key handlers say
            # explicitly whether Alt is down.
            if PaintTool.sample_armed or getattr(self, "_alt_down", False):
                icon = "eyedropper"
        # The guide-mode plus: the Tape and the Protractor say with
        # it whether this measurement will leave a guide behind (issue #29).
        plus = bool(getattr(self.active_tool, "cursor_plus", False))
        cur = (tool_cursor(icon, plus)
               if self.active_tool is not None else None)
        if cur is None and self.active_tool is not None:
            # A tool without a drawn icon can still ask for a stock Qt
            # cursor (Position Texture shows a hand).
            shape = getattr(self.active_tool, "qt_cursor", None)
            if shape is not None:
                from PySide6.QtGui import QCursor
                cur = QCursor(shape)
        if cur is not None:
            self.setCursor(cur)
        else:
            self.unsetCursor()

    def _apply_nav_cursor(self) -> None:
        """The pointer for a camera nav mode: orbit / pan / the magnifier
        (each navigation tool shows its own icon)."""
        from views.icons import tool_cursor
        if self.nav_mode in ("orbit", "pan", "zoom", "zoom_window"):
            cur = tool_cursor(self.nav_mode)
            if cur is not None:
                self.setCursor(cur)
                return
            self.setCursor(Qt.CrossCursor
                           if self.nav_mode in ("zoom", "zoom_window")
                           else Qt.OpenHandCursor)

    def _orbit_pivot_at(self, x: float, y: float):
        """Where an orbit gesture that starts at pixel ``(x, y)`` turns (#164).

        1. The model point under the cursor -- the nearest face the pick
           ray hits (loose geometry and groups alike);
        2. else, with the cursor on sky or ground, the middle of the
           stretch of the view's central ray that crosses the model's
           bounding box -- the middle of what is on screen;
        3. else the camera target (an empty scene, a model off screen).
        Worked out once per gesture: the pivot stays put while dragging.
        """
        origin, direction = self._pixel_to_ray(x, y)
        seen = self._depth_world_at(x, y) if hasattr(self, "_depth_world_at") \
            else None
        if seen is not None and seen[0] == "hit":
            return seen[1]
        if origin is not None and direction is not None and seen is None:
            try:
                idx = self._pick_index(near=("px", x, y))
                if idx.entities:
                    import numpy as np
                    face_t = self._hover_face_t(idx, origin, direction)
                    if face_t is not None and len(face_t):
                        t = float(np.min(face_t))
                        if math.isfinite(t) and t > 0.0:
                            return origin + direction * t
            except Exception:                  # noqa: BLE001 - fall back
                pass
        lo, hi = self.scene.bounds()
        if lo is not None:
            o, d = self._pixel_to_ray(self.width() / 2.0, self.height() / 2.0)
            if o is not None and d is not None:
                span = _ray_aabb_span(
                    (o.x(), o.y(), o.z()), (d.x(), d.y(), d.z()),
                    (lo.x(), lo.y(), lo.z()), (hi.x(), hi.y(), hi.z()))
                if span is not None:
                    return o + d * ((span[0] + span[1]) * 0.5)
        return QVector3D(self.camera.target)

    def _end_camera_drag(self) -> None:
        """Forget a camera drag in progress (orbit, pan or zoom by drag)."""
        self._last_pos = None
        self._orbit_pivot = None
        self._pan_mode = False
        self._middle_drag_active = False
        if self.nav_mode is not None:
            self._apply_nav_cursor()
        else:
            self._apply_tool_cursor()

    def _set_middle_drag_pan_mode(self, pan: bool) -> None:
        """Switch an active MMB drag between orbit and pan."""
        if not self._middle_drag_active or self.nav_mode is not None:
            return
        pan = bool(pan)
        if self._pan_mode == pan:
            return
        self._pan_mode = pan
        from views.icons import tool_cursor
        cur = tool_cursor("pan" if pan else "orbit")
        if cur is not None:
            self.setCursor(cur)

    def set_nav_mode(self, mode: Optional[str]) -> None:
        """Enter a camera navigation mode ("orbit" / "pan").

        For trackpad users with no middle mouse button: while a nav mode is
        active the left-drag drives the camera (orbit or pan). The active
        drawing tool is suspended; return to drawing by picking any tool or
        pressing Space (Select). ``None`` clears the nav mode.
        """
        if self.active_tool is not None:
            self.active_tool.on_deactivate(self)
            self.active_tool = None
        self._hover_entity = None
        self.last_snap = None
        self.nav_mode = mode
        self._last_pos = None             # a drag in progress ends here
        self._orbit_pivot = None
        self._pan_mode = False
        self._middle_drag_active = False
        if mode is not None:
            self._apply_nav_cursor()      # orbit / pan / magnifier icons
        else:
            self.unsetCursor()
        self.update()

    def leaveEvent(self, ev) -> None:
        if self._hover_entity is not None:
            self._hover_entity = None
            self.update()
        super().leaveEvent(ev)

    # ---- Input --------------------------------------------------------------
    def _context_pick(self, x: float, y: float):
        """Right-click at ``(x, y)``: select the thing under the cursor
        before the menu opens — unless it is already selected, which keeps
        the selection as it is. Returns that thing (or ``None``).

        «Under the cursor» is what the cursor SHOWS: a group behind a
        selected loose face used to take the right-click and drop the
        selection, and «Make Group» with it (#378).

        Something already selected under the cursor wins outright: loose
        geometry flush on a group (a block standing on it, a face drawn on
        its surface) is coplanar with the group there, and the group took
        the click (#744)."""
        mine = self.pick_edge(x, y) or self.pick_face(x, y)
        if mine is not None and mine in self.scene.selection:
            return mine
        picked = (self.pick_text_label(x, y, rect_only=True)
                  or self.pick_group(x, y) or self.pick_edge(x, y)
                  or self.pick_geopath(x, y) or self.pick_dimension(x, y)
                  or self.pick_text_label(x, y)
                  or self.pick_section_plane(x, y)
                  or self.pick_guide(x, y)
                  or self._face_or_image_in_front(x, y)
                  or self.pick_image_plane(x, y)
                  or self.pick_locked_image_plane(x, y))
        if picked is not None and picked not in self.scene.selection:
            self.scene.select([picked])
            self.update()
        return picked

    def _face_or_image_in_front(self, x: float, y: float):
        face = self.pick_face(x, y)
        return self.image_in_front_of(face, x, y) or face

    # ---- A side-tray tab dropped here: the window moves it to that side ----
    def _dock_drag(self, ev) -> bool:
        win = self.window()
        mime = getattr(win, "DOCK_MIME", None)
        return bool(mime) and ev.mimeData().hasFormat(mime)

    def dragEnterEvent(self, ev) -> None:
        if self._dock_drag(ev):
            ev.acceptProposedAction()
            return
        super().dragEnterEvent(ev)

    def dragMoveEvent(self, ev) -> None:
        if self._dock_drag(ev):
            ev.acceptProposedAction()
            return
        super().dragMoveEvent(ev)

    def dropEvent(self, ev) -> None:
        if self._dock_drag(ev):
            self.window().drop_dock_on_viewport(ev)
            return
        super().dropEvent(ev)

    def contextMenuEvent(self, ev) -> None:
        """Right-click: select what's under the cursor and open
        a context menu of actions relevant to the current selection."""
        win = self.window()
        # A tool with its own right-click menu (Position Texture: Done /
        # Reset / Flip / Rotate) takes the click instead.
        hook = getattr(self.active_tool, "context_menu", None)
        if callable(hook) and hook(self, ev.globalPos()):
            return
        if not hasattr(win, "show_viewport_context_menu"):
            return
        x, y = ev.pos().x(), ev.pos().y()
        # Where the menu was opened, for entries that act at the cursor
        # (Texture ▸ Position puts its pins on the tile under it).
        self._context_pixel = (x, y)
        picked = self._context_pick(x, y)
        # A locked image under the cursor is offered even when the click
        # landed on geometry drawn over it (the plaza on its orthomosaic):
        # the menu is the only way back to Unlock / Delete for it.
        under = self.pick_locked_image_plane(x, y)
        win.show_viewport_context_menu(
            ev.globalPos(), locked_image=under if under is not picked else None)

    def mousePressEvent(self, ev) -> None:
        # A new gesture starts with the inferences back on: the Alt
        # toggle lasts ONE operation. Mid-operation (the
        # second click of a line) the tool is still busy and nothing moves.
        self._release_linear_mode()
        self._input_t = _time_mod.monotonic()   # P0: input→paint latency
        if (ev.button() in (Qt.LeftButton, Qt.RightButton)
                and self.nav_mode is None and self._look_drag is None
                and callable(getattr(self.active_tool, "on_look", None))):
            self._begin_look(ev)
            return
        if ev.button() == Qt.MiddleButton:
            self._last_pos = ev.position().toPoint()
            self._pan_mode = bool(ev.modifiers() & Qt.ShiftModifier)
            self._middle_drag_active = True
            self._orbit_pivot = self._orbit_pivot_at(
                ev.position().x(), ev.position().y())
            self._pan_depth = self._depth_of(self._orbit_pivot)
            # While the wheel-drag lasts, the pointer becomes the
            # orbit (or pan) icon; the tool cursor comes back on release.
            from views.icons import tool_cursor
            cur = tool_cursor("pan" if self._pan_mode else "orbit")
            if cur is not None:
                self.setCursor(cur)
            return
        # Nav buttons: left-drag orbits/pans the camera.
        # Hold Shift while orbiting to pan temporarily (matches MMB+Shift).
        if ev.button() == Qt.LeftButton and self.nav_mode is not None:
            if self.nav_mode == "zoom_window":
                # Drag a rectangle; the camera zooms to it on release.
                self._zoom_box_active = True
                self._zoom_box_start = ev.position()
                self._zoom_box_cur = ev.position()
                return
            self._last_pos = ev.position().toPoint()
            self._pan_mode = (
                self.nav_mode == "pan"
                or bool(ev.modifiers() & Qt.ShiftModifier)
            )
            self._orbit_pivot = (
                self._orbit_pivot_at(ev.position().x(), ev.position().y())
                if self.nav_mode == "orbit" else None)
            self._pan_depth = (
                self._depth_of(self._orbit_pivot_at(
                    ev.position().x(), ev.position().y()))
                if self._pan_mode else None)
            # The orbit/pan icon stays through the drag.
            self._apply_nav_cursor()
            return
        if ev.button() == Qt.LeftButton and self.active_tool is not None:
            # Triple click: a press landing right after a double-click at the
            # same spot (Qt has no native triple event): select all
            # connected.
            if self._is_triple_click(ev):
                self._last_double = None
                ctx = self._build_ctx(ev)
                if ctx is not None:
                    self.active_tool.on_triple_click(ctx)
                    self.update()
                return
            # Box-select tools defer the decision to release: a tiny drag is a
            # click, a real drag is a rubber-band box.
            if self.active_tool.box_select:
                self._box_active = True
                self._box_start = ev.position()
                self._box_cur = ev.position()
                return
            self._dispatch_tool_click(ev)

    def _is_triple_click(self, ev) -> bool:
        from PySide6.QtWidgets import QApplication
        last = self._last_double
        if last is None:
            return False
        t, pos = last
        return (ev.timestamp() - t
                <= QApplication.doubleClickInterval()
                and (ev.position() - pos).manhattanLength() < 8)

    def _dispatch_tool_click(self, ev, double: bool = False) -> None:
        """Forward a (double-)click to the active tool, then run the shared
        follow-ups: lock the chain to a clicked face's plane, clear the VCB."""
        had_start = getattr(self.active_tool, "start_point", None) is not None
        had_plane = getattr(self.active_tool, "work_plane", None) is not None
        face_at_click = None
        group_at_click = None
        if not had_start and not had_plane:
            face_at_click, group_at_click = self.pick_face_placement(
                ev.position().x(), ev.position().y())
        ctx = self._build_ctx(ev)
        if ctx is not None:
            # The tool hears the cursor's snap KIND before it is called, as on
            # every hover (``_note_snap``): a click that never had its own
            # hover would otherwise leave a stale — or absent — kind in the
            # tool, and ``PlaneLock.snapped_plane`` decides with it whether
            # the shape re-plans onto the clicked point (#37) or stays on the
            # face under the cursor (#545).
            self._note_snap(ctx.snap)
            _before = len(self.history.undo_stack)
            if double:
                self.active_tool.on_double_click(ctx)
            else:
                self.active_tool.on_click(ctx)
            # Did this click actually MAKE something? That, not «the tool
            # went idle», is when the arrow lock should go — @pacaeiro on
            # 0.4.4: «I draw a line with hard lock (arrows) and, after the
            # line is created the lock is still active». The Line tool
            # chains, so it is still busy the instant a segment exists, and
            # the first fix waited for the whole polyline to end.
            _drew = len(self.history.undo_stack) > _before
            # If the click established a new start point on top of an
            # existing face, lock the rest of the chain to that face's
            # plane so subsequent clicks stay coplanar.
            now_start = getattr(self.active_tool, "start_point", None)
            if (
                not had_start
                and now_start is not None
                and face_at_click is not None
                and hasattr(self.active_tool, "work_plane")
                and self.active_tool.work_plane is None   # a plane lock wins
            ):
                # In WORLD space: a component's face keeps its own
                # coordinates, and the plane it captured for a rectangle
                # on the pergola's post was the untransformed one — the
                # second corner landed on a plane nowhere near the post
                # («la inferencia se atasca», Marco, 2026-09-14).
                from core.snap import face_plane_world
                self.active_tool.work_plane = face_plane_world(
                    face_at_click, getattr(group_at_click, "xform", None))
            # Any pending typed value is invalidated once the user
            # commits a point with the mouse.
            self._set_value_buffer("")
            # A command that failed was rolled back (History is
            # transactional) — surface it instead of failing silently.
            if self.history.last_error:
                self.flash_status(
                    tr("Operation failed and was undone: {err}",
                       err=self.history.last_error), 8000)
            self._release_axis_lock_after_operation(committed=_drew)
            if _drew:
                self._reassert_tool_cursor()
            self.update()

    def _reassert_tool_cursor(self) -> None:
        """Put the active tool's pointer back after an operation (#191,
        fafecm on Windows: «after the push/pull cursor is used once, the
        cursor symbol disappears» — the Line did the same). On Windows the
        viewport is a native OpenGL window and the system brought the arrow
        back when an operation ended, while Qt still believed its cursor
        set, so setting the same one again changed nothing: unset first,
        then set. Nothing to do while a camera mode or a look drag owns
        the pointer."""
        if (self.active_tool is None or self.nav_mode is not None
                or self._look_drag is not None):
            return
        self.unsetCursor()
        self._apply_tool_cursor()

    def enterEvent(self, ev) -> None:
        # Coming back from a panel or a dialog is the other moment Windows
        # shows the arrow over the viewport (#191).
        self._reassert_tool_cursor()
        super().enterEvent(ev)

    def mouseDoubleClickEvent(self, ev) -> None:
        """Qt replaces the second press of a double-click with this event, so
        route it to ``tool.on_double_click`` — whose default re-runs
        ``on_click``, keeping fast click-click rhythms working for drawing
        tools while Push/Pull overrides it to repeat its last distance.

        Box-select tools (Select) get the double-click DIRECTLY (no drag box
        starts on a double), and the event is remembered so the next press in
        place counts as a triple click."""
        if ev.button() != Qt.LeftButton or self.active_tool is None \
                or self.nav_mode is not None:
            self.mousePressEvent(ev)
            return
        self._last_double = (ev.timestamp(), ev.position())
        if self.active_tool.box_select:
            ctx = self._build_ctx(ev)
            if ctx is not None:
                self.active_tool.on_double_click(ctx)
                self.update()
            return
        self._dispatch_tool_click(ev, double=True)

    # ---- Mouse look (a tool with ``on_look``: First Person) -----------------
    @staticmethod
    def _can_warp_pointer() -> bool:
        """Whether the pointer can be put back after each look move. Wayland
        does not let a client move it; there the look is a plain drag."""
        from PySide6.QtGui import QGuiApplication
        name = QGuiApplication.platformName().lower()
        return not (name.startswith("wayland") or name in ("offscreen",
                                                            "minimal"))

    def _begin_look(self, ev) -> None:
        self._look_drag = (ev.button(), ev.position().toPoint())
        self.setCursor(Qt.BlankCursor)

    def _look_move(self, ev) -> None:
        button, last = self._look_drag
        p = ev.position().toPoint()
        dx, dy = p.x() - last.x(), p.y() - last.y()
        if dx or dy:
            self.active_tool.on_look(self, dx, dy)
        if (dx or dy) and self._can_warp_pointer():
            from PySide6.QtGui import QCursor
            QCursor.setPos(self.mapToGlobal(last))
            p = last
        self._look_drag = (button, p)

    def _end_look(self) -> None:
        self._look_drag = None
        self._apply_tool_cursor()

    def mouseMoveEvent(self, ev) -> None:
        self._input_t = _time_mod.monotonic()   # P0: input→paint latency
        # An Alt released while another window had the keyboard never
        # reaches any filter here; the pointer re-reads it on the move.
        alt = bool(ev.modifiers() & Qt.AltModifier)
        if alt != self._alt_down:
            self._apply_alt_cursor(alt)
        if self._look_drag is not None and ev.buttons() == Qt.NoButton:
            # The look drag's release was lost (the same hole as the orbit
            # below): with the pointer hidden and put back on every move it
            # would be trapped in the window. No button held ends it.
            self._end_look()
        if self._look_drag is not None:
            if callable(getattr(self.active_tool, "on_look", None)):
                self._look_move(ev)
                return
            self._end_look()                    # the tool changed mid-drag
        if self._last_pos is not None and ev.buttons() == Qt.NoButton:
            # A camera drag with no button held: its release never reached
            # us (a Windows mouse or touchpad driver, a click on another
            # window, a tool switched by keyboard mid-drag). Left alone,
            # EVERY mouse move orbited the view whatever tool was picked —
            # «el orbital se mantiene activo… no se desactiva con nada»
            # (Andrés Rodríguez, Windows 11 + NVIDIA, 0.5.0).
            self._end_camera_drag()
        if self._middle_drag_active:
            self._set_middle_drag_pan_mode(
                bool(ev.modifiers() & Qt.ShiftModifier))
        if self._last_pos is not None:
            p = ev.position().toPoint()
            dx = p.x() - self._last_pos.x()
            dy = p.y() - self._last_pos.y()
            self._last_pos = p
            if self.nav_mode == "zoom":
                self.camera.zoom(-dy * 0.035)        # drag up = zoom in
            elif self._pan_mode:
                self.camera.pan(dx, dy, self.height(),
                                depth=getattr(self, "_pan_depth", None))
            else:
                pivot = getattr(self, "_orbit_pivot", None)
                ody = -dy if self._invert_orbit_y else dy
                if pivot is not None:
                    self.camera.orbit_about(pivot, dx, ody, self.height())
                else:
                    self.camera.orbit(dx, ody, self.height())
            self.update()
            return

        if self._box_active:
            self._box_cur = ev.position()
            self.update()
            return

        if self._zoom_box_active:
            self._zoom_box_cur = ev.position()
            self.update()
            return

        # Adaptive hover coalescing: against a big imported model one hover
        # costs ~25-30 ms (picks + snap) while the mouse delivers 60-125
        # events/s — processing every event backlogs the queue and the whole
        # app reads as frozen. Gate by the measured cost of the LAST hover
        # (a small model gates at ~0 → immediate), and let a trailing-edge
        # timer process the final position so the highlight never sticks.
        self._pending_hover = (ev.position(), ev.modifiers())
        now = _time_mod.monotonic()
        gate = min(0.06, getattr(self, "_hover_cost", 0.0) * 1.5)
        elapsed = now - getattr(self, "_hover_last_t", 0.0)
        if elapsed < gate:
            timer = getattr(self, "_hover_timer", None)
            if timer is None:
                from PySide6.QtCore import QTimer
                timer = self._hover_timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(self._run_pending_hover)
            if not timer.isActive():
                timer.start(max(1, int((gate - elapsed) * 1000) + 1))
            return
        self._run_pending_hover()

    def _run_pending_hover(self) -> None:
        pending = getattr(self, "_pending_hover", None)
        if pending is None:
            return
        self._pending_hover = None
        pos, modifiers = pending
        t0 = _time_mod.monotonic()
        self._process_hover(pos, modifiers)
        self._hover_last_t = _time_mod.monotonic()
        self._hover_cost = self._hover_last_t - t0
        if _PERF:
            # A per-move cost near ~100 ms starves paints during a tool drag
            # (the push "sticks"): name it in the log instead of hiding
            # under the frame telemetry's floor.
            _plog("hover.move", self._hover_cost * 1000.0, floor=80.0)

    def _process_hover(self, pos, modifiers) -> None:
        if self._last_pos is not None or self._box_active:
            return          # a camera drag / box select started meanwhile
        self._tick = getattr(self, "_tick", 0) + 1     # a new epoch memo
        ev = _HoverEvent(pos, modifiers)
        _hp0 = _time_mod.perf_counter() if _PERF else 0.0

        def _hmark(name):
            nonlocal _hp0
            if _PERF:
                now = _time_mod.perf_counter()
                _plog(f"hover.{name}", (now - _hp0) * 1000.0, floor=200.0)
                _hp0 = now

        # Track cursor + hover edge so Down can capture a reference edge.
        self._last_mouse_pos = ev.position()
        self._emit_coordinate(ev)
        _hmark("coord")
        # Plan↔profile link (Track G): let an open profile mark the station of
        # the route point under the cursor.
        win = self.window()
        if hasattr(win, "on_viewport_hover"):
            win.on_viewport_hover(ev.position().x(), ev.position().y())
        self.inference.acquire(ev.position().x(), ev.position().y())

        if self.active_tool is None:
            return
        _hmark("acquire")
        ctx = self._build_ctx(ev)
        _hmark("ctx")
        if ctx is None:
            return
        self._note_snap(ctx.snap)
        if self.active_tool.uses_snap:
            # Encouraging: the point the snap already found — no extra pick
            # per hover. A circle's rim encourages its CENTRE (found by the
            # centre reference while the cursor is on the rim); on a face
            # with arcs a real corner under the cursor still wins.
            center = getattr(self, "_hover_center", None)
            point = None
            if ctx.snap.kind in self._ENCOURAGING_KINDS:
                point = ctx.snap.point
            if center is not None and (point is None or center[2][0] == "edge"):
                point = QVector3D(center[0])
            self._dwell_on(point)
        self.active_tool.on_hover(ctx)
        _hmark("tool")
        self.measurementChanged.emit(self._measurement_text())
        _hmark("measure")
        self.update()

    # Below this many pixels of drag, a left press/release is a click, not a box.
    BOX_DRAG_THRESHOLD_PX = 4.0

    def mouseReleaseEvent(self, ev) -> None:
        if self._look_drag is not None and ev.button() == self._look_drag[0]:
            self._end_look()
            return
        if ev.button() == Qt.MiddleButton:
            self._last_pos = None
            self._orbit_pivot = None
            self._pan_mode = False
            self._middle_drag_active = False
            if self.nav_mode is not None:
                self._apply_nav_cursor()
            else:
                self._apply_tool_cursor()
            return

        if ev.button() == Qt.LeftButton and self._zoom_box_active:
            self._zoom_box_active = False
            start, end = self._zoom_box_start, self._zoom_box_cur
            self._zoom_box_start = None
            self._zoom_box_cur = None
            if start is not None and end is not None:
                self._zoom_to_box(start, end)
            self.update()
            return

        if ev.button() == Qt.LeftButton and self.nav_mode is not None:
            self._last_pos = None
            self._orbit_pivot = None
            self._pan_mode = False
            self._apply_nav_cursor()
            return

        # Stroke tools (the Eraser): notify the release so a press-drag-release
        # stroke can commit as one step. No-op default on other tools.
        if (ev.button() == Qt.LeftButton and self.active_tool is not None
                and not self._box_active and self.nav_mode is None):
            _before = len(self.history.undo_stack)
            self.active_tool.on_release(self)
            self._release_axis_lock_after_operation()
            if len(self.history.undo_stack) > _before:
                self._reassert_tool_cursor()     # a drag committed (#191)

        if ev.button() == Qt.LeftButton and self._box_active:
            self._box_active = False
            start = self._box_start
            end = ev.position()
            self._box_start = None
            self._box_cur = None
            tool = self.active_tool
            if tool is None or start is None:
                self.update()
                return
            dx = end.x() - start.x()
            dy = end.y() - start.y()
            # The box reads the same modifiers as a click: Shift
            # toggles what it catches — the way you rub a wall out of a big
            # catch — Ctrl adds and Shift+Ctrl removes.
            mode = selection_mode(ev.modifiers())
            additive = mode != "replace"
            if math.hypot(dx, dy) < self.BOX_DRAG_THRESHOLD_PX:
                # A click: pick the single entity under the cursor.
                ctx = self._build_ctx(ev)
                if ctx is not None:
                    tool.on_click(ctx)
            else:
                rect = (
                    min(start.x(), end.x()), min(start.y(), end.y()),
                    max(start.x(), end.x()), max(start.y(), end.y()),
                )
                crossing = dx < 0  # right-to-left drag = crossing selection
                tool.on_box_select(self, rect, crossing, additive, mode=mode)
            self.update()

    def wheelEvent(self, ev) -> None:
        # While a 3D mouse moves the view, wheel notches are its driver's
        # imitation of the same push (3Dconnexion does that for programs it
        # does not know): zooming on them too made the view jump a step
        # about eight times a second over the smooth move.
        from views.ndof_input import cap_in_use
        if cap_in_use():
            ev.accept()
            return
        self._input_t = _time_mod.monotonic()   # P0: input→paint latency
        # Zoom toward the cursor: keep the point under the
        # pointer fixed on screen, not the origin. During a wheel burst the
        # focus is CACHED: zoom_to pins that world point, so re-picking every
        # tick both wasted ~25 ms/tick against a big model (the zoom felt
        # heavy) and let float error drift the pinned point.
        import time as _time
        steps = ev.angleDelta().y() / 120.0
        if self._invert_wheel:          # Preferences ▸ General (the usual
            steps = -steps              # Compatibility ▸ invert wheel)
        pos = ev.position()
        now = _time.monotonic()

        def pose():
            c = self.camera
            t = c.target
            return (round(c.yaw, 9), round(c.pitch, 9),
                    round(c.distance, 6),
                    round(t.x(), 6), round(t.y(), 6), round(t.z(), 6))

        # The pin is anchored to the CAMERA POSE, not a time window:
        # zoom_to keeps the focus fixed on screen by construction, so slow
        # one-notch-per-second zooming reuses it indefinitely (a 1 s window
        # expired between deliberate notches and re-picked 280k triangles
        # per notch — the zoom jank). Orbit/pan or an edit changes the pose
        # or the version and honestly invalidates it.
        cached = getattr(self, "_zoom_focus", None)
        reused = (cached is not None and cached[0] == pose()
                  and abs(pos.x() - cached[1]) < 24.0
                  and abs(pos.y() - cached[2]) < 24.0
                  and self.scene.version == cached[3])
        reproj = False
        if reused:
            focus = cached[4]
        else:
            focus = None
            if (cached is not None and cached[4] is not None
                    and self.scene.version == cached[3]):
                # Orbit/pan changed the pose, but the cursor usually still
                # rests on the SAME world point (zoom → orbit a touch → zoom
                # again, the modeling rhythm). Re-validate the pin by
                # projecting it with the current camera: one matrix map
                # instead of a ~25 ms re-pick of the whole model per notch.
                p = self._world_to_pixel(cached[4])
                if (p is not None and abs(p[0] - pos.x()) < 24.0
                        and abs(p[1] - pos.y()) < 24.0):
                    focus = cached[4]
                    reproj = True
            if focus is None:
                focus = self._world_under_cursor(pos.x(), pos.y())
        if focus is not None:
            # A perceptible retreat even from a close-up: ~1 % of the
            # model's size per notch when the frame scaling alone would move
            # the eye less than that (the "zoom is stuck" report).
            self.camera.zoom_to(steps, focus,
                                min_step=self._zoom_out_step())
        else:
            self.camera.zoom(steps)
        self._zoom_focus = (pose(), pos.x(), pos.y(),
                            self.scene.version, focus)
        if _PERF:
            _plog("wheel", (_time_mod.monotonic() - now) * 1000.0,
                  extra=f"reused={'proj' if reproj else reused}", floor=10.0)
        self.update()

    #: The least a notch of the wheel backs out, from a close-up, once the
    #: camera stands 2 cm or more from what it looks at — and always in an
    #: empty scene, which has no size to go by.
    _ZOOM_OUT_STEP = 0.05

    def _zoom_out_step(self) -> float:
        """Zoom-out floor per notch: 1 % of the model, never less than 5 cm
        — as it always was — except closer than 2 cm to a small part, where
        5 cm would throw it out of sight in one notch: there the 5 cm
        shrinks with the distance (1.25 cm at the 5 mm close-up)."""
        diag = self._model_diag()
        if diag <= 0.0:
            return self._ZOOM_OUT_STEP
        from core.camera import MIN_DISTANCE_FAR
        near = min(1.0, float(self.camera.distance) / MIN_DISTANCE_FAR)
        return max(self._ZOOM_OUT_STEP * near, 0.01 * diag)

    _MODIFIER_KEYS = frozenset({Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt,
                                Qt.Key_Meta, Qt.Key_AltGr})

    def ctrl_tapped(self) -> bool:
        """Whether the Ctrl being released was pressed ALONE — no other key
        in between, not even one a menu shortcut took (Ctrl+Z reaches us
        only as a ShortcutOverride). Tools that toggle on a Ctrl tap ask
        this on the release (#183)."""
        return getattr(self, "_ctrl_alone", False)

    def event(self, ev) -> bool:
        if (ev.type() in (QEvent.ShortcutOverride, QEvent.KeyPress)
                and ev.key() not in self._MODIFIER_KEYS):
            self._ctrl_alone = False
        # With a VCB buffer in progress, claim keys that continue it (unit
        # suffixes m/cm/mm, separators, sign) before the window's QAction
        # shortcuts swallow them — otherwise typing "2m" would fire the Move
        # tool instead of finishing the length. Bare letters with no buffer
        # still reach the shortcuts.
        # A tool that plays letters as keys (First Person's W/A/S/D) takes
        # them from the window's tool shortcuts while it is active.
        if ev.type() == QEvent.ShortcutOverride and self._tool_claims_key(ev):
            ev.accept()
            return True
        if (ev.type() == QEvent.ShortcutOverride and self._value_buffer
                and not _is_chord(ev.modifiers())):
            t = ev.text().lower()
            if t and (t.isdigit() or t in (".", ",", ";", " ", "-", ":",
                                           "\"", "'", "/", "m", "c", "r",
                                           "i", "n", "f", "t", "x", "*", "s")):
                ev.accept()
                return True
            # "0.3p", the profile of a bevel — P is Push/Pull otherwise.
            if t == "p" and hasattr(self.active_tool, "on_profile_value"):
                ev.accept()
                return True
        # Right after a copy, "x5" is the array written multiplier first
        # (#542): the bare X must reach the value box, not the Text tool.
        if (ev.type() == QEvent.ShortcutOverride and not self._value_buffer
                and not _is_chord(ev.modifiers())
                and ev.text().lower() == "x"
                and getattr(self.active_tool, "accepts_array", False)
                and self._array_pending()):
            ev.accept()
            return True
        return super().event(ev)

    def _tool_claims_key(self, ev) -> bool:
        claims = getattr(self.active_tool, "claims_key", None)
        return callable(claims) and bool(claims(ev.key(), ev.modifiers()))

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Control and not ev.isAutoRepeat():
            self._ctrl_alone = True       # until another key says otherwise
        # Held keys (First Person): the press and the release are the
        # tool's; auto-repeat says nothing new.
        if self._tool_claims_key(ev):
            if not ev.isAutoRepeat():
                self.active_tool.on_key(self, ev.key(), ev.modifiers())
            return
        # 0. Shift state change → refresh snap immediately so the user sees
        #the contextual lock take effect without moving the mouse.
        if ev.key() == Qt.Key_Down and not ev.isAutoRepeat():
            # A Down press takes the plane over from a held Shift (see
            # _mark_plane_for_shift): what the user locks with it now
            # outlives the key, so the Shift release must not undo it.
            self._shift_plane_mark = None
        if ev.key() == Qt.Key_Shift and not ev.isAutoRepeat():
            self._set_middle_drag_pan_mode(True)
            self._capture_shift_lock()
            self._refresh_snap()
            # Do not return — Shift is a modifier; let the rest fall through.
        # 0b. Alt turns Paint into the eyedropper: show it on the pointer the
        #     moment the key goes down, not after the next mouse move.
        if ev.key() == Qt.Key_Alt and not ev.isAutoRepeat():
            self._apply_alt_cursor(True)
        elif self._alt_tap and not ev.isAutoRepeat():
            # Alt+something is a shortcut: we are not taking its release.
            self._alt_tap = False

        # 1. Numeric value buffer (VCB-style length input).
        if self._handle_value_key(ev):
            return

        # 2. Active tool gets first shot at the key.
        if self.active_tool is not None:
            if self.active_tool.on_key(self, ev.key(), ev.modifiers()):
                return

        # 2b. Delete in any other tool (Paint, Push/Pull, Offset…): with the
        #     tool idle, erase the selection or — nothing selected — the edge
        #     or face highlighted under the cursor. Mid-operation it would
        #     pull the geometry out from under the tool, so it waits.
        if ev.key() == Qt.Key_Delete and not ev.isAutoRepeat():
            tool = self.active_tool
            if tool is None or not self._tool_busy_for_delete(tool):
                from tools.select import delete_selection_or_hover
                delete_selection_or_hover(self)
                return

        # 3. Esc, escalating (standard CAD): first clear the typed value buffer,
        #    then cancel the tool's in-progress action (an unfinished chain, a
        #    drag), and finally — nothing in progress — clear the selection.
        if ev.key() == Qt.Key_Escape:
            self.escape()
            return

        # 3. Projection toggle.
        if ev.key() == Qt.Key_P:
            self.toggle_projection()
            return

        # 3b. Alt: cycle linear inferences — ONLY while an operation is in
        #     progress, the classic behaviour. Its status bar offers
        #     «Alt = Activar/desactivar "Inferencias lineales"» after the
        #     first click of a line and not before, and the three states are
        #     ours exactly: all → off → parallel/perp.
        #
        #     We had it global, at any moment, and that is the whole of
        #     issue #26: Pedro Caeiro switches windows with Alt+Tab all day
        #     and every switch moved a mode he was not using. Idle, there is
        #     now nothing to steal. Cycling on the PRESS (not the release) is
        #     deliberate: the release is what makes Qt's menu bar take focus,
        #     so it lands on the QMenuBar, not here — measured on Marco's
        #     desktop, one tap in six reached us.
        if ev.key() == Qt.Key_Alt and not ev.isAutoRepeat():
            if self.active_tool is not None and self._tool_busy(
                    self.active_tool):
                self._alt_tap = True        # the release is ours too
                self._cycle_linear_inference_mode()
            return

        # 4. Axis lock (arrow keys). Pressing the same arrow toggles it off.
        if ev.key() == Qt.Key_Right:
            self.axis_lock = None if self.axis_lock == "x" else "x"
            self._refresh_snap()
            return
        if ev.key() == Qt.Key_Left:
            self.axis_lock = None if self.axis_lock == "y" else "y"
            self._refresh_snap()
            return
        if ev.key() == Qt.Key_Up:
            self.axis_lock = None if self.axis_lock == "z" else "z"
            self._refresh_snap()
            return

        # 5. Reference edge — Down cycles None → parallel → perpendicular → None.
        if ev.key() == Qt.Key_Down:
            self._cycle_reference_mode()
            self._refresh_snap()
            return

        super().keyPressEvent(ev)

    def escape(self) -> None:
        """The Esc cascade (standard CAD), ONE step per press: a typed value
        buffer, then a sticky constraint (axis lock / reference), then the
        array window a copy just opened, then the tool's in-progress action, then the selection, then — nothing in
        progress — step out ONE level of the open group, and
        finally the tool's own cancel. The window's «Cancel current tool»
        action (shortcut Esc, which fires BEFORE this widget's key event)
        calls this too: it used to carry its own copy of the cascade,
        without the group step, so Esc never left a group (Marco,
        2026-09-14: «he hecho Esc varias veces y no salgo»)."""
        if self._value_buffer:
            self._set_value_buffer("")
            return
        if self.release_constraints():
            return
        tool = self.active_tool
        close = getattr(tool, "close_array_window", None)
        if callable(close) and self._array_pending():
            # Right after a copy the array window is what is open: Esc
            # closes it before touching the selection, so a bare X is the
            # Text shortcut again (#542).
            close()
            return
        if tool is not None and type(tool).__name__ == "PasteTool":
            win = self.window()
            activate = getattr(win, "_activate_tool", None)
            if activate is not None:
                activate("select")
                return
        if tool is not None and self._tool_busy(tool):
            tool.on_cancel(self)
            self._release_linear_mode()
            return
        if self.scene.selection or self.extension_pick is not None:
            self.scene.clear_selection()
            self.clear_extension_pick()
            self.update()
            return
        if self.scene.edit_group is not None:
            self.end_one_group_edit()       # step out ONE level
            return
        if tool is not None:
            tool.on_cancel(self)

    def _alt_tapped(self) -> bool:
        """A clean Alt tap (press and release, nothing in between) toggles
        Paint's eyedropper and it STAYS until one sample is taken or Alt is
        tapped again — the usual behaviour (Marco, 2026-09-23: «se alterna
        con Alt, no es que se mantenga presionado»). Holding Alt and
        clicking still samples, as before."""
        if self.nav_mode is not None or getattr(
                self.active_tool, "icon", None) != "paint":
            return False
        from tools.paint import PaintTool
        win = self.window()
        act = getattr(win, "_act_eyedropper", None)
        if act is not None:
            act.setChecked(not act.isChecked())   # the button shows it too
        else:
            PaintTool.sample_armed = not PaintTool.sample_armed
        self._apply_tool_cursor()
        return True

    def _apply_alt_cursor(self, down: bool) -> None:
        """Refresh the pointer for an Alt state change (Paint <-> eyedropper);
        no-op while a camera nav mode owns the cursor. ``down`` is the key's
        state after this event — see ``_apply_tool_cursor``."""
        self._alt_down = bool(down)
        if self.nav_mode is None and getattr(
                self.active_tool, "icon", None) == "paint":
            self._apply_tool_cursor()

    def keyReleaseEvent(self, ev) -> None:
        release = getattr(self.active_tool, "on_key_release", None)
        if callable(release):
            if ev.isAutoRepeat() and self._tool_claims_key(ev):
                return
            if not ev.isAutoRepeat() and release(self, ev.key()):
                return
        if ev.key() == Qt.Key_Alt and not ev.isAutoRepeat():
            self._apply_alt_cursor(False)
            if self._alt_tap:
                # We acted on the press, so the release is ours: swallowing
                # it keeps Qt's menu bar from taking focus on it. Otherwise
                # the focus ping-pongs viewport → menu bar → viewport and
                # every other Alt lands on the menu bar instead of here
                # (issue #26; measured: one tap in six got through).
                self._alt_tap = False
                ev.accept()
                return
        if ev.key() == Qt.Key_Shift and not ev.isAutoRepeat():
            self._set_middle_drag_pan_mode(False)
            self._shift_lock = None
            self._release_shift_plane_mark()
            self._refresh_snap()
        super().keyReleaseEvent(ev)

    def focusOutEvent(self, ev) -> None:
        """Focus gone means the Alt release will land somewhere else, so the
        claim on it lapses (issue #26)."""
        self._alt_tap = False
        self._alt_down = False        # its release will not reach us either
        self._ctrl_alone = False      # nor will Ctrl's
        self._release_shift_plane_mark()   # nor Shift's: unmark the plane
        # Nor will the release of a held walking key (First Person).
        lost = getattr(self.active_tool, "on_focus_out", None)
        if callable(lost):
            lost(self)
        super().focusOutEvent(ev)
