# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Camera ▸ Camera from Photo: lay the lines over the photo.

The photo shows behind the model, in the camera's frame. Over it lie two
red lines (edges along the red axis), two green ones (along the green
axis), the origin and the blue handle. Each end, a whole line (dragged by
its middle), the origin and the blue handle drag on the screen; the camera
follows at once (``core.photo_match``), so the model's axes and whatever is
already drawn settle onto the photo while you drag.

Each line runs on, dashed, to its vanishing point; the horizon goes
through both. The blue handle slides up the blue axis and stands for the
length typed in the Measurements box (3 m until said otherwise): that is
the scale. F keeps the photo's own focal length (from its EXIF) instead of
reading it from the lines. Enter, or any other tool, keeps the lines; Esc
puts them back as they were; orbiting leaves the photo, as in any photo
scene. The lines become one undo step.

Everything the keys do is also on the right-click menu and in the panel
that opens with the tool (views/photo_match_panel.py): Done, Cancel,
Reset lines (for a corner seen from outside, a room seen from inside, or a
block seen from above), Swap red and green, the photo's focal length,
showing the other side of the photo when the solver's camera is the mirror
image, the photo in front of the model or the model hidden, and a grid on
the axis planes to judge the fit.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPen

from core import photo_match as PM
from core.i18n import tr
from tools.base import Tool

#: A handle is caught this close to the cursor, in pixels.
HANDLE_PX = 10.0
#: A line is caught by its middle this close.
LINE_PX = 6.0

RED = QColor(225, 45, 45)
GREEN = QColor(30, 165, 60)
BLUE = QColor(40, 95, 230)
HORIZON = QColor(245, 200, 40)
GRID = QColor(255, 255, 255, 150)

#: The kinds of photo the lines can start from (``PhotoMatch.reset_lines``),
#: in menu order, with their English names.
STARTS = (("outside", "Corner seen from outside"),
          ("inside", "Room seen from inside"),
          ("above", "Seen from above"))
#: Grid planes, with their English names.
GRID_PLANES = (("xy", "Red–green (ground)"), ("xz", "Red–blue"),
               ("yz", "Green–blue"))


class PhotoMatchTool(Tool):
    name = "Camera from Photo"
    icon = "photo_match"
    description = ("Lay the red and green lines on edges of the photo that "
                   "run along the red and green axes; the camera that took "
                   "it follows.")
    uses_snap = False
    allow_inferences = False
    vcb_label = "Length"

    #: The grid over the photo, for every photo of the session: the planes
    #: shown and the spacing, metres.
    grid_planes: set = set()
    grid_spacing: float = 1.0

    def __init__(self, view, on_done=None) -> None:
        #: The photo scene being calibrated (``core.saved_views.SavedView``).
        self.view = view
        self.on_done = on_done
        self.drag = None             # handle name, or ("line", key, last uv)
        self.hover = None
        self.result = None           # Solution or CalibrationError
        self.done = False
        self._before_photo = None
        self._before_camera = None
        #: Called after every change (the panel refreshes); and once when
        #: the tool ends, however it ends (the panel closes).
        self.on_change = None
        self.on_finish = None

    # ---- Life ----------------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self.done = False
        self._before_photo = self.view.photo.to_dict()
        self._before_camera = self.view.camera_state()
        viewport.enter_photo(self.view)
        self._solve(viewport)

    def on_deactivate(self, viewport) -> None:
        # Another tool picked: the lines stay as they are, the photo too —
        # tracing over it is what they are for.
        if not self.done:
            self._finish(viewport, True, switch=False)

    def on_photo_left(self, viewport) -> None:
        """The camera moved off the photo (an orbit…): the lines are kept."""
        if not self.done:
            self._finish(viewport, True)

    def on_cancel(self, viewport) -> None:
        self._finish(viewport, False)

    def on_key(self, viewport, key, modifiers) -> bool:
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._finish(viewport, True)
            return True
        if key == Qt.Key_F and not modifiers & (Qt.ControlModifier
                                                 | Qt.AltModifier):
            self.set_exif_focal(viewport,
                                not self.view.photo.use_exif_focal)
            return True
        return False

    def on_value(self, viewport, value) -> bool:
        """A length typed: what the blue handle stands for, metres."""
        if isinstance(value, tuple):
            return False
        return self.set_length(viewport, value)

    # ---- What the keys, the right-click menu and the panel do ----------------
    def done_ok(self, viewport) -> None:
        self._finish(viewport, True)

    def cancel(self, viewport) -> None:
        self._finish(viewport, False)

    def set_length(self, viewport, value) -> bool:
        """What the blue handle stands for, metres (> 0)."""
        try:
            value = abs(float(value))
        except (TypeError, ValueError):
            return False
        if not (value > 0.0 and math.isfinite(value)):
            return False
        self.view.photo.scale_length = value
        self._changed(viewport)
        return True

    def set_exif_focal(self, viewport, on: bool) -> bool:
        """Keep the photo's own focal length (``on``), or read it from the
        lines. Refused, with a word, for a photo that does not say it."""
        pm = self.view.photo
        if not pm.exif_focal_35:
            flash = getattr(viewport, "flash_status", None)
            if callable(flash):
                flash(tr("This photo does not say its focal length."))
            return False
        pm.use_exif_focal = bool(on)
        self.refresh_hint(viewport)
        self._changed(viewport)
        return True

    def set_flip_sides(self, viewport, on: bool) -> None:
        """Show the other side of the photo (``on``): the lines fit two
        cameras, mirror images of each other, and the solver's pick is
        the wrong one for this photo — the model faces away, green side
        turned from the viewer (issue #1553)."""
        self.view.photo.flip_sides = bool(on)
        self._changed(viewport)

    def reset_lines(self, viewport, preset: str = "outside") -> None:
        self.view.photo.reset_lines(preset)
        self._changed(viewport, snap=True)

    def swap_axes(self, viewport) -> None:
        self.view.photo.swap_axes()
        self._changed(viewport, snap=True)

    def set_show_model(self, viewport, on: bool) -> None:
        self.view.photo.show_model = bool(on)
        self._changed(viewport)

    def set_photo_front(self, viewport, on: bool) -> None:
        self.view.photo.photo_front = bool(on)
        self._changed(viewport)

    def set_photo_opacity(self, viewport, value: float) -> None:
        self.view.photo.photo_opacity = max(0.05, min(1.0, float(value)))
        self._changed(viewport)

    def set_grid_plane(self, viewport, plane: str, on: bool) -> None:
        planes = set(type(self).grid_planes)
        (planes.add if on else planes.discard)(plane)
        type(self).grid_planes = planes
        self._changed(viewport, solve=False)

    def set_grid_spacing(self, viewport, value) -> bool:
        try:
            value = abs(float(value))
        except (TypeError, ValueError):
            return False
        if not (value > 0.0 and math.isfinite(value)):
            return False
        type(self).grid_spacing = value
        self._changed(viewport, solve=False)
        return True

    def _changed(self, viewport, snap: bool = False,
                 solve: bool = True) -> None:
        if self.done:
            return
        if solve:
            self._solve(viewport)
            if snap and isinstance(self.result, PM.Solution):
                PM.snap_scale_to_axis(self.view.photo, self.result)
                self._solve(viewport)
        viewport.update()
        self._notify()

    def _notify(self) -> None:
        if callable(self.on_change):
            self.on_change()

    def context_menu(self, viewport, global_pos) -> bool:
        """The tool's own right-click menu: everything the panel does."""
        if self.done:
            return False
        from PySide6.QtWidgets import QMenu
        menu = QMenu(viewport)
        self.fill_menu(menu, viewport)
        menu.exec(global_pos)
        return True

    def fill_menu(self, menu, viewport) -> None:
        pm = self.view.photo
        menu.addAction(tr("Done"), lambda: self.done_ok(viewport))
        menu.addAction(tr("Cancel"), lambda: self.cancel(viewport))
        menu.addSeparator()
        reset = menu.addMenu(tr("Reset lines"))
        for key, label in STARTS:
            reset.addAction(tr(label),
                            lambda k=key: self.reset_lines(viewport, k))
        menu.addAction(tr("Swap red and green"),
                       lambda: self.swap_axes(viewport))
        exif = menu.addAction(tr("Use the photo's focal length"))
        exif.setCheckable(True)
        exif.setChecked(bool(pm.use_exif_focal))
        exif.setEnabled(bool(pm.exif_focal_35))
        exif.toggled.connect(lambda on: self.set_exif_focal(viewport, on))
        flip = menu.addAction(tr("Show the other side"))
        flip.setCheckable(True)
        flip.setChecked(bool(pm.flip_sides))
        flip.toggled.connect(lambda on: self.set_flip_sides(viewport, on))
        menu.addSeparator()
        model = menu.addAction(tr("Show model"))
        model.setCheckable(True)
        model.setChecked(bool(pm.show_model))
        model.toggled.connect(lambda on: self.set_show_model(viewport, on))
        front = menu.addAction(tr("Photo in front of the model"))
        front.setCheckable(True)
        front.setChecked(bool(pm.photo_front))
        front.toggled.connect(lambda on: self.set_photo_front(viewport, on))
        grid = menu.addMenu(tr("Grid"))
        for key, label in GRID_PLANES:
            act = grid.addAction(tr(label))
            act.setCheckable(True)
            act.setChecked(key in type(self).grid_planes)
            act.toggled.connect(lambda on, k=key: self.set_grid_plane(
                viewport, k, on))

    def status_clause(self) -> str:
        pm = self.view.photo
        parts = [tr("Drag the ends of the lines onto edges of the photo"),
                 tr("type the blue length"),
                 tr("Enter = done, Esc = cancel")]
        if pm.exif_focal_35:
            parts.append(tr("F = photo's focal length: on")
                         if pm.use_exif_focal
                         else tr("F = photo's focal length: off"))
        return " · ".join(parts)

    def _finish(self, viewport, accept: bool, switch: bool = True) -> None:
        if self.done:
            return
        self.done = True
        self.drag = None
        if callable(self.on_finish):
            self.on_finish()
        view = self.view
        if accept:
            after_photo = view.photo.to_dict()
            # Nothing moved: nothing to keep (the camera comes from the
            # lines, and a look at them must not mark the document changed).
            if after_photo != self._before_photo:
                if not isinstance(self.result, PM.CalibrationError):
                    view.take_camera(viewport.camera)
                after_camera = view.camera_state()
                from core.saved_views import PhotoCalibrationCommand
                history = getattr(viewport, "history", None)
                cmd = PhotoCalibrationCommand(
                    view, self._before_photo, after_photo,
                    self._before_camera, after_camera)
                if history is not None:
                    history.execute(cmd)
                else:
                    cmd.do(viewport.scene)
        else:
            view.photo = PM.PhotoMatch.from_dict(self._before_photo)
            view.set_camera_state(self._before_camera)
            if viewport.photo_view is view:
                viewport.apply_photo_camera()
        viewport.update()
        if switch and callable(self.on_done):
            self.on_done()

    # ---- The camera ------------------------------------------------------------
    def _solve(self, viewport) -> None:
        if viewport.photo_view is not self.view:
            viewport.enter_photo(self.view)
        self.result = viewport.apply_photo_camera()

    # ---- Screen <-> photo ----------------------------------------------------------
    def _frame(self, viewport):
        from core.camera import frame_rect
        return frame_rect(max(viewport.width(), 1), max(viewport.height(), 1),
                          self.view.photo.aspect)

    def to_screen(self, viewport, uv) -> QPointF:
        x, y, w, h = self._frame(viewport)
        return QPointF(x + uv[0] * w, y + uv[1] * h)

    def to_photo(self, viewport, pos) -> tuple[float, float]:
        x, y, w, h = self._frame(viewport)
        return ((pos.x() - x) / w, (pos.y() - y) / h)

    def image_to_screen(self, viewport, xy) -> QPointF:
        return self.to_screen(viewport, self.view.photo.to_photo(xy))

    def handle_at(self, viewport, pos):
        """The handle under ``pos`` (nearest within reach), or a line
        caught by its middle as ``("line", "x0")``, or ``None``."""
        best, best_d = None, HANDLE_PX
        for name, uv in self.view.photo.handles().items():
            p = self.to_screen(viewport, uv)
            d = math.hypot(p.x() - pos.x(), p.y() - pos.y())
            if d <= best_d:
                best, best_d = name, d
        if best is not None:
            return best
        pm = self.view.photo
        for axis, lines in (("x", pm.x_lines), ("y", pm.y_lines)):
            for i, (a, b) in enumerate(lines):
                if _seg_dist(pos, self.to_screen(viewport, a),
                             self.to_screen(viewport, b)) <= LINE_PX:
                    return ("line", f"{axis}{i}")
        return None

    # ---- Dragging ------------------------------------------------------------------
    def on_screen_press(self, viewport, pos) -> bool:
        if self.done or self._frame(viewport) is None:
            return False
        hit = self.handle_at(viewport, pos)
        if hit is None:
            return False
        if isinstance(hit, tuple):
            self.drag = ("line", hit[1], self.to_photo(viewport, pos))
        else:
            self.drag = hit
        return True

    def on_screen_drag(self, viewport, pos) -> None:
        if self.drag is None:
            return
        pm = self.view.photo
        uv = self.to_photo(viewport, pos)
        if isinstance(self.drag, tuple):
            _kind, key, last = self.drag
            du, dv = uv[0] - last[0], uv[1] - last[1]
            lines = pm.x_lines if key[0] == "x" else pm.y_lines
            ln = lines[int(key[1])]
            lines[int(key[1])] = [[ln[0][0] + du, ln[0][1] + dv],
                                  [ln[1][0] + du, ln[1][1] + dv]]
            self.drag = ("line", key, uv)
        elif self.drag == "scale":
            uv = self._on_blue_axis(uv)
            pm.set_handle("scale", uv)
        else:
            pm.set_handle(self.drag, uv)
        self._solve(viewport)
        if self.drag != "scale" and isinstance(self.result, PM.Solution):
            # The blue axis moved with the lines: its handle follows it.
            PM.snap_scale_to_axis(pm, self.result)
            self._solve(viewport)
        self._notify()

    def on_screen_release(self, viewport, pos) -> None:
        self.drag = None
        self._notify()

    def on_screen_hover(self, viewport, pos) -> bool:
        if self.done:
            return False
        hit = self.handle_at(viewport, pos)
        if hit != self.hover:
            self.hover = hit
            if hit is None:
                viewport.unsetCursor()
            else:
                viewport.setCursor(Qt.SizeAllCursor if isinstance(hit, tuple)
                                   else Qt.CrossCursor)
        return True

    def _on_blue_axis(self, uv):
        """``uv`` brought onto the blue axis through the origin, when the
        camera is known; as it is otherwise."""
        sol = self.result
        if not isinstance(sol, PM.Solution):
            return uv
        pm = self.view.photo
        o = pm.to_image(pm.origin)
        p = pm.to_image(uv)
        d = sol.axis_image_direction(o, (0.0, 0.0, 1.0))
        if d is None:
            return uv
        t = max((p[0] - o[0]) * d[0] + (p[1] - o[1]) * d[1], 1e-3)
        return pm.to_photo((o[0] + d[0] * t, o[1] + d[1] * t))

    # ---- Drawing -------------------------------------------------------------------
    def draw_overlay(self, viewport, painter) -> None:
        if self.done or self._frame(viewport) is None:
            return
        pm = self.view.photo
        sol = self.result if isinstance(self.result, PM.Solution) else None
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        if sol is not None:
            self._draw_grid(viewport, painter, sol)
            self._draw_horizon(viewport, painter, sol)
        for axis, lines, colour in (("x", pm.x_lines, RED),
                                    ("y", pm.y_lines, GREEN)):
            vp = (sol.vp_x if axis == "x" else sol.vp_y) if sol else None
            for i, (a, b) in enumerate(lines):
                self._draw_line(viewport, painter, a, b, vp, colour,
                                self.hover == ("line", f"{axis}{i}"))
                for end, uv in (("a", a), ("b", b)):
                    self._draw_handle(painter, self.to_screen(viewport, uv),
                                      colour, self.hover == f"{axis}{i}{end}")
        o = self.to_screen(viewport, pm.origin)
        s = self.to_screen(viewport, pm.scale_point)
        painter.setPen(QPen(BLUE, 2.0))
        painter.drawLine(o, s)
        self._draw_handle(painter, s, BLUE, self.hover == "scale")
        self._draw_handle(painter, o, QColor(250, 250, 250),
                          self.hover == "origin", ring=QColor(20, 20, 20))
        from core.units import fmt_len
        self._label(painter, QPointF(s.x() + 10, s.y() - 6),
                    fmt_len(pm.scale_length), BLUE)
        self._draw_info(viewport, painter, sol)
        painter.restore()

    def _draw_line(self, viewport, painter, a, b, vp, colour, hot) -> None:
        pa, pb = self.to_screen(viewport, a), self.to_screen(viewport, b)
        painter.setPen(QPen(colour, 3.0 if hot else 2.0))
        painter.drawLine(pa, pb)
        if vp is None:
            return
        v = self.image_to_screen(viewport, vp)
        # From the end nearer the vanishing point, on to it (or far out).
        near = pa if (_d(pa, v) < _d(pb, v)) else pb
        far = pb if near is pa else pa
        dist = _d(near, v)
        if not math.isfinite(dist):
            return
        reach = 4.0 * (viewport.width() + viewport.height())
        if dist > reach:
            dx, dy = near.x() - far.x(), near.y() - far.y()
            n = math.hypot(dx, dy) or 1.0
            v = QPointF(near.x() + dx / n * reach, near.y() + dy / n * reach)
        pen = QPen(colour, 1.0, Qt.DashLine)
        painter.setPen(pen)
        painter.drawLine(near, v)

    def _draw_grid(self, viewport, painter, sol) -> None:
        planes = type(self).grid_planes
        if not planes:
            return
        painter.setPen(QPen(GRID, 1.0))
        for a, b in PM.grid_segments(sorted(planes), type(self).grid_spacing):
            seg = PM.project_segment(sol, a, b)
            if seg is None:
                continue
            painter.drawLine(self.image_to_screen(viewport, seg[0]),
                             self.image_to_screen(viewport, seg[1]))

    def _draw_horizon(self, viewport, painter, sol) -> None:
        a = self.image_to_screen(viewport, sol.vp_x)
        b = self.image_to_screen(viewport, sol.vp_y)
        dx, dy = b.x() - a.x(), b.y() - a.y()
        n = math.hypot(dx, dy)
        if n < 1e-9 or not math.isfinite(n):
            return
        reach = 4.0 * (viewport.width() + viewport.height())
        mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
        # Through the middle of the view, not only between the points.
        x, y, w, h = self._frame(viewport)
        centre = QPointF(x + w / 2, y + h / 2)
        t = ((centre.x() - mid.x()) * dx + (centre.y() - mid.y()) * dy) / n
        foot = QPointF(mid.x() + dx / n * t, mid.y() + dy / n * t)
        painter.setPen(QPen(HORIZON, 1.5))
        painter.drawLine(QPointF(foot.x() - dx / n * reach,
                                 foot.y() - dy / n * reach),
                         QPointF(foot.x() + dx / n * reach,
                                 foot.y() + dy / n * reach))

    @staticmethod
    def _draw_handle(painter, p, colour, hot, ring=None) -> None:
        r = 7.0 if hot else 5.0
        painter.setPen(QPen(ring or QColor(255, 255, 255), 1.5))
        painter.setBrush(colour)
        painter.drawEllipse(p, r, r)
        painter.setBrush(Qt.NoBrush)

    @staticmethod
    def _label(painter, at, text, colour) -> None:
        f = QFont(painter.font())
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QPen(QColor(255, 255, 255, 230), 3.0))
        painter.drawText(at, text)          # a halo for any photo
        painter.setPen(colour)
        painter.drawText(at, text)

    def info_lines(self, sol) -> list[tuple[str, bool]]:
        """What the box over the photo says: ``(text, is_warning)``."""
        pm = self.view.photo
        out = []
        if sol is None:
            err = self.result
            out.append((tr(str(err)) if err is not None
                        else tr("No camera fits these lines."), True))
            return out
        mm = PM.focal_35mm(sol.focal, pm.aspect)
        if pm.use_exif_focal and pm.exif_focal_35:
            out.append((tr("Focal length {mm} mm, the photo's own (F)",
                           mm=f"{mm:.0f}"), False))
        else:
            out.append((tr("Focal length {mm} mm (35 mm equivalent)",
                           mm=f"{mm:.0f}"), False))
            if pm.exif_focal_35:
                out.append((tr("The photo says {mm} mm",
                               mm=f"{pm.exif_focal_35:.0f}"), False))
                miss = PM.focal_mismatch(pm, sol)
                if miss is not None and miss > PM.FOCAL_MISMATCH:
                    out.append((tr(
                        "Far from the photo's own: check that each pair of "
                        "lines follows parallel edges."), True))
        return out

    def _draw_info(self, viewport, painter, sol) -> None:
        lines = self.info_lines(sol)
        if not lines:
            return
        x, y, w, h = self._frame(viewport)
        fm = painter.fontMetrics()
        lh = fm.height() + 2
        width = max(fm.horizontalAdvance(t) for t, _w in lines) + 16
        box = QRectF(x + 10, y + 10, width, lh * len(lines) + 10)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(20, 20, 20, 170))
        painter.drawRoundedRect(box, 4, 4)
        painter.setBrush(Qt.NoBrush)
        for k, (text, warn) in enumerate(lines):
            painter.setPen(QColor(255, 140, 120) if warn
                           else QColor(240, 240, 240))
            painter.drawText(QPointF(box.x() + 8,
                                     box.y() + 5 + fm.ascent() + k * lh),
                             text)


def _d(a, b) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def _seg_dist(p, a, b) -> float:
    """Distance from ``p`` to the segment ``a``–``b``, middle part only:
    the ends are the handles'."""
    dx, dy = b.x() - a.x(), b.y() - a.y()
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return float("inf")
    t = ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / L2
    if not 0.15 <= t <= 0.85:
        return float("inf")
    return math.hypot(p.x() - (a.x() + t * dx), p.y() - (a.y() + t * dy))
