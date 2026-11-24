# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Section Box tool — Tools ▸ Section Box.

Flow:
- Picking the tool: with a box SELECTED, edits that box (it cuts now). With
  anything else, a NEW box, cutting and selected: around the selection, or
  around the whole model when nothing is selected. So the button always
  means what it looks like; an existing box is taken up by selecting it (a
  click on an edge, its row in the Browser), and the switch beside the tool
  turns one on without editing it. A model keeps as many boxes as it
  needs, one cutting at a time: «Show all section boxes» draws the others
  in grey, to see them and click one (#1552).
- Each face carries a GRIP at its centre: a round dot with a short double
  arrow along the face's normal. Press and drag the grip — or the face
  itself — (or click, move, click) to slide the face
  along its axis: pull it out and the box grows that way, push it in and it
  shrinks. A point of the model under the cursor pulls the face level with
  it when the face passes within a few pixels of it. Type a distance and Enter while dragging to move it exactly
  that far, the way the drag goes (a negative number turns it round).
- The grips also show on a box selected with Select: dragging one picks up
  this tool and moves that face.
- Esc puts a face being dragged back. Enter or Tab ends the editing: the
  box keeps cutting, its grips go away and Select comes back. The box is an object like a section
  plane: select it, right-click it or find it in the Browser to switch its
  cut, its frame and its fill; Delete takes it away.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen, QPolygonF, QVector3D

from core.history import section_box_added, section_box_changed
from core.i18n import tr
from core.section import (SectionBox, SectionPlane, box_arrows,
                          box_face_hit, box_face_quad)
from core.units import fmt_len
from tools.base import Tool, ToolContext

#: A press that moves less than this many pixels before the release is a
#: click (the drag stays open for a second click), not a stroke.
_DRAG_PX = 4.0
#: Each grip is a double arrow through the face's centre: this many pixels
#: to each side, whatever the zoom; and how near the cursor must come.
ARROW_PX = 22.0
_ARROW_HIT_PX = 9.0
#: The round grip in the middle, pixels of radius.
_GRIP_PX = 5.5
#: A point of the model pulls the dragged face level with it only from
#: this near, on screen.
_MAGNET_PX = 8.0
#: The points that pull: a definite spot of the model. A point somewhere
#: along an edge or a guide (on_edge, on_line) names no height of its own.
_CORNERS = frozenset({"endpoint", "midpoint", "intersection", "center",
                      "centre", "arc_midpoint", "component_origin"})
_ORANGE = QColor(243, 115, 41)


def the_box(scene):
    """The section box a «fit» acts on: the one selected, else the one
    cutting, else the last made — or ``None``."""
    picked = [e for e in scene.selection if isinstance(e, SectionBox)]
    if picked:
        return picked[-1]
    return scene.active_section_box() or (
        scene.section_boxes[-1] if scene.section_boxes else None)


def place_box(viewport, fit_selection: bool = True,
              new: bool = True) -> bool:
    """A section box around the selection (``fit_selection``) or the whole
    model, cutting and with its frame, as one undo step, selected (its
    grips out). ``new``: a NEW box, named, the others switched off. Not
    ``new``: the box there is (:func:`the_box`) fitted there instead —
    its name, fill and identity stay — and a new one only with none.
    Returns whether a box was placed: an empty model has nothing to box."""
    scene = viewport.scene
    lo = hi = None
    if fit_selection and _fit_targets(scene):
        lo, hi = scene.selection_bounds()
    if lo is None:
        lo, hi = scene.bounds()
    if lo is None:
        return False
    fitted = SectionBox.around(lo, hi)
    box = None if new else the_box(scene)
    if box is None:
        fitted.name = next_box_name(scene.section_boxes)
        viewport.history.execute(section_box_added(scene, fitted))
        box = fitted
    else:
        state = box.copy()
        state.lo, state.hi = fitted.lo, fitted.hi
        state.active, state.hidden = True, False
        if not state.same_as(box):
            viewport.history.execute(section_box_changed(scene, box, state))
    scene.select([box])
    return True


def next_box_name(boxes) -> str:
    """«Section box 1», «Section box 2»… — the first number not taken."""
    taken = {b.name for b in boxes}
    n = 1
    while tr("Section box {n}", n=n) in taken:
        n += 1
    return tr("Section box {n}", n=n)


def _live(viewport):
    """The box the tool works on: the one cutting."""
    scene = getattr(viewport, "scene", None)
    active = getattr(scene, "active_section_box", None)
    return active() if callable(active) else None


def _fit_targets(scene) -> list:
    """What in the selection a new box should frame: everything but the
    section objects themselves (a selected box asks to be edited, not
    replaced)."""
    return [e for e in scene.selection
            if not isinstance(e, (SectionBox, SectionPlane))]


def _closest_on_axis(c: QVector3D, axis: int, o: QVector3D, d: QVector3D):
    """The coordinate along ``axis`` of the point of the line through ``c``
    parallel to that axis nearest the ray ``o + s·d``; ``None`` when the
    ray runs along the axis."""
    e = [0.0, 0.0, 0.0]
    e[axis] = 1.0
    e = QVector3D(*e)
    w = c - o
    b = QVector3D.dotProduct(e, d)
    dd = QVector3D.dotProduct(d, d)
    denom = dd - b * b
    if denom < 1e-9:
        return None
    u = (b * QVector3D.dotProduct(d, w) - dd * QVector3D.dotProduct(e, w)) \
        / denom
    return (c.x(), c.y(), c.z())[axis] + u


def arrow_pixels(viewport, box) -> list:
    """``(index, centre, tip)`` on screen of the six grips of ``box``: the
    face's centre and the outer tip of its double arrow, :data:`ARROW_PX`
    out of the face whatever the zoom (the inner tip is the mirror of it).
    Grips whose face centre does not project are left out."""
    centre = (box.lo + box.hi) * 0.5
    c = viewport._world_to_pixel(centre)
    if c is None:
        return []
    ppm = 0.0                           # pixels per metre near the box
    for a in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
        p = viewport._world_to_pixel(centre + QVector3D(*a))
        if p is not None:
            ppm = max(ppm, math.hypot(p[0] - c[0], p[1] - c[1]))
    if ppm < 1e-9:
        return []
    out = []
    for index, base, tip in box_arrows(box, ARROW_PX / ppm):
        b = viewport._world_to_pixel(base)
        t = viewport._world_to_pixel(tip)
        if b is not None and t is not None:
            out.append((index, b, t))
    return out


def pick_arrow(viewport, box, sx: float, sy: float):
    """The face whose grip — its double arrow or the dot at its centre —
    is under the cursor, or ``None``."""
    best, best_d = None, _ARROW_HIT_PX
    for index, b, t in arrow_pixels(viewport, box):
        inner = (2 * b[0] - t[0], 2 * b[1] - t[1])
        dx, dy = t[0] - inner[0], t[1] - inner[1]
        ln2 = dx * dx + dy * dy
        u = 0.0 if ln2 < 1e-9 else max(0.0, min(1.0, (
            (sx - inner[0]) * dx + (sy - inner[1]) * dy) / ln2))
        d = math.hypot(inner[0] + u * dx - sx, inner[1] + u * dy - sy)
        if d < best_d:
            best, best_d = index, d
    return best


def _head(painter, tip, ux, uy, size) -> None:
    """A solid arrow head at ``tip`` pointing along (ux, uy)."""
    bx, by = tip[0] - ux * size, tip[1] - uy * size
    w = size * 0.55
    painter.drawPolygon(QPolygonF([
        QPointF(*tip), QPointF(bx - uy * w, by + ux * w),
        QPointF(bx + uy * w, by - ux * w)]))


def draw_arrows(viewport, painter, box, hot=None) -> None:
    """The six grips: a short double arrow along each face's normal — pull
    out, push in — with a round dot at the face's centre to take it by.
    The one under the cursor (or being dragged) is heavier."""
    painter.save()
    for index, b, t in arrow_pixels(viewport, box):
        dx, dy = t[0] - b[0], t[1] - b[1]
        ln = math.hypot(dx, dy)
        heavy = index == hot
        if ln >= 6.0:                   # seen straight on: the dot alone
            ux, uy = dx / ln, dy / ln
            inner = (2 * b[0] - t[0], 2 * b[1] - t[1])
            head = 9.0 if heavy else 7.5
            painter.setPen(QPen(_ORANGE, 3.0 if heavy else 2.0,
                                Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(inner[0] + ux * head * 0.6,
                                     inner[1] + uy * head * 0.6),
                             QPointF(t[0] - ux * head * 0.6,
                                     t[1] - uy * head * 0.6))
            painter.setPen(QPen(QColor(255, 255, 255, 220), 1.0))
            painter.setBrush(_ORANGE)
            _head(painter, t, ux, uy, head)
            _head(painter, inner, -ux, -uy, head)
        r = _GRIP_PX + (1.5 if heavy else 0.0)
        painter.setPen(QPen(QColor(255, 255, 255), 1.5))
        painter.setBrush(_ORANGE)
        painter.drawEllipse(QPointF(*b), r, r)
    painter.restore()


class SectionBoxTool(Tool):
    name = "Section Box"
    description = ("Keep only what lies inside a box, and drag its faces "
                   "to frame the part you work on.")
    vcb_label = "Distance"

    def __init__(self) -> None:
        self.hover_face: int | None = None
        self.drag_face: int | None = None
        self._start: SectionBox | None = None     # the box before the drag
        self._press = None                        # (x, y) of the press
        self._grab = 0.0          # face minus the cursor's spot at the press
        self._moved = False
        self._viewport = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._viewport = viewport
        self.hover_face = None
        self._end_drag(viewport, keep=False)
        scene = viewport.scene
        # Which box: the one selected (it cuts now); else a NEW one, around
        # what is selected or the whole model.
        picked = [e for e in scene.selection if isinstance(e, SectionBox)]
        box = picked[-1] if picked else None
        if box is None or _fit_targets(scene):
            if not place_box(viewport):
                viewport.flash_status(tr("Nothing to put a section box "
                                         "around yet"), 4000)
                return
        elif not box.active or box.hidden:
            # Edited, it cuts and its frame shows: a hidden frame has no
            # face to drag (Edit Section Box from the Browser).
            on = box.copy()
            on.active = True
            on.hidden = False
            viewport.history.execute(section_box_changed(scene, box, on))
        # A box is placed to be SEEN: cuts and frames switched off come
        # back on, as for a new section plane.
        if not (getattr(scene, "show_section_cuts", True)
                and getattr(scene, "show_section_planes", True)):
            scene.show_section_cuts = True
            scene.show_section_planes = True
        window = viewport.window() if hasattr(viewport, "window") else None
        sync = getattr(window, "_sync_section_menu", None)
        if callable(sync):
            sync()
        viewport.update()

    def on_deactivate(self, viewport) -> None:
        self._end_drag(viewport, keep=False)
        self.hover_face = None

    # ---- Input --------------------------------------------------------------
    def on_hover(self, ctx: ToolContext) -> None:
        vp = self._viewport = ctx.viewport
        box = _live(vp)
        if box is None:
            self.hover_face = None
            return
        sx, sy = ctx.screen.x(), ctx.screen.y()
        if self.drag_face is None:
            self.hover_face = self._pick_face(vp, sx, sy)
            vp.update()
            return
        if self._press is not None and math.hypot(
                sx - self._press[0], sy - self._press[1]) >= _DRAG_PX:
            self._moved = True
        value = self._drag_value(ctx)
        if value is not None:
            self._show(vp, self._start.with_face(self.drag_face, value))

    def on_click(self, ctx: ToolContext) -> None:
        vp = self._viewport = ctx.viewport
        if self.drag_face is not None:
            self._commit(vp)                      # the second click
            return
        # A grey box's EDGE first (Show all section boxes): that one cuts
        # now and the tool goes on with it. Before the faces of the box that
        # cuts — a box inside it lies all over them, and a thin edge is the
        # deliberate target (#1552). Its own grips still win.
        sx, sy = ctx.screen.x(), ctx.screen.y()
        live = _live(vp)
        on_grip = live is not None and pick_arrow(vp, live, sx, sy) is not None
        pick = getattr(vp, "pick_section_box", None)
        other = pick(sx, sy) if pick and not on_grip else None
        if other is not None and other is not live:
            self.take_up(vp, other)
            return
        face = self._pick_face(vp, sx, sy)
        if face is not None:
            self.begin_drag(vp, face, sx, sy)

    def on_double_click(self, ctx: ToolContext) -> None:
        """A double click on a grey box: the first click already took it
        up (:meth:`on_click`); the second has nothing more to do."""

    def take_up(self, viewport, box) -> None:
        """Go on with ``box``: it cuts (the others stop) and its frame
        shows, one undo step, selected with its grips out."""
        self._end_drag(viewport, keep=False)
        scene = viewport.scene
        if not box.active or box.hidden:
            on = box.copy()
            on.active, on.hidden = True, False
            viewport.history.execute(section_box_changed(scene, box, on))
        scene.select([box])
        self.hover_face = None
        window = viewport.window() if hasattr(viewport, "window") else None
        sync = getattr(window, "_sync_section_menu", None)
        if callable(sync):
            sync()
        viewport.update()

    def begin_drag(self, viewport, face: int, sx: float, sy: float) -> None:
        """Start sliding ``face`` from the press at (sx, sy) — a click on
        the face or its arrow here, or on an arrow with Select."""
        box = _live(viewport)
        if box is None:
            return
        self._viewport = viewport
        self.drag_face = face
        self.hover_face = face
        self._start = box.copy()
        self._press = (sx, sy)
        self._moved = False
        # Grabbed at an arrow's tip, the face must not jump to the tip: it
        # keeps its distance to the spot the press took on its axis.
        at = self._axis_value(viewport, sx, sy)
        self._grab = (0.0 if at is None
                      else self._start.face_value(face) - at)
        viewport.update()

    def on_release(self, viewport) -> None:
        # A press-drag-release stroke commits; a press that stayed put is the
        # first click of a click-move-click.
        if self.drag_face is not None and self._moved:
            self._commit(viewport)

    def on_value(self, viewport, value) -> bool:
        if isinstance(value, tuple) or self.drag_face is None:
            return False
        # The typed distance goes the way the drag goes, as Push/Pull's
        # does: pulling out grows the box by it, pushing in shrinks it; a
        # negative number turns it round. Before any movement, out.
        way = -1.0 if self._moved_out(viewport) < -1e-9 else 1.0
        out = 1.0 if self.drag_face % 2 else -1.0
        start = self._start.face_value(self.drag_face)
        self._show(viewport, self._start.with_face(
            self.drag_face, start + out * way * float(value)))
        self._commit(viewport)
        return True

    def on_cancel(self, viewport) -> None:
        self._end_drag(viewport, keep=False)
        viewport.update()

    # ---- Done with the box: Enter or Tab ------------------------------------
    #: The keys that end the editing: the box keeps cutting as it stands,
    #: its grips go away and Select comes back.
    DONE_KEYS = (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab)

    def claims_key(self, key: int, modifiers) -> bool:
        """Tab, taken before Qt moves the focus with it. Enter is not
        claimed: a distance typed while dragging reads it first."""
        return key == Qt.Key_Tab and not modifiers & (
            Qt.ControlModifier | Qt.AltModifier)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key not in self.DONE_KEYS:
            return False
        self.finish(viewport)
        return True

    def finish(self, viewport) -> None:
        """Stop editing the box: a face being dragged stays where it is,
        the box keeps cutting, it is deselected (no grips) and the Select
        tool comes back."""
        if self.drag_face is not None:
            self._commit(viewport)
        scene = viewport.scene
        boxes = [e for e in scene.selection if isinstance(e, SectionBox)]
        for box in boxes:
            scene.selection.discard(box)
        if boxes:
            scene.bump_view()
        window = viewport.window() if hasattr(viewport, "window") else None
        activate = getattr(window, "_activate_tool", None)
        if callable(activate):
            activate("select")
        viewport.update()

    # ---- Live readout and overlay -------------------------------------------
    def value_label(self):
        if self.drag_face is None or self._start is None:
            return None
        box = _live(self._viewport)
        if box is None:
            return None
        quad = box_face_quad(box, self.drag_face)
        return (fmt_len(abs(self._moved_out(self._viewport))),
                (quad[0] + quad[2]) * 0.5)

    def rubber_band_lines(self):
        return []

    def draw_overlay(self, viewport, painter) -> None:
        """The face under the cursor (or being dragged), lit; the arrows
        are the viewport's (they show on a selected box too)."""
        box = _live(viewport)
        face = self.drag_face if self.drag_face is not None \
            else self.hover_face
        if box is None or face is None:
            return
        pts = [viewport._world_to_pixel(p) for p in box_face_quad(box, face)]
        if any(p is None for p in pts):
            return
        painter.save()
        painter.setPen(QPen(_ORANGE, 2.5))
        painter.setBrush(QColor(243, 115, 41, 50))
        painter.drawPolygon(QPolygonF([QPointF(*p) for p in pts]))
        painter.restore()

    # ---- Internals ----------------------------------------------------------
    @staticmethod
    def _pick_face(viewport, sx: float, sy: float):
        """The face to drag at (sx, sy): its arrow first, else the face of
        the box the cursor's ray meets."""
        box = _live(viewport)
        if box is None:
            return None
        face = pick_arrow(viewport, box, sx, sy)
        if face is not None:
            return face
        o, d = viewport._pixel_to_ray(sx, sy)
        if o is None or d is None:
            return None
        hit = box_face_hit(box, o, d)
        return None if hit is None else hit[0]

    def _moved_out(self, viewport) -> float:
        """How far the dragged face stands OUT of where it started (< 0:
        pushed in)."""
        box = _live(viewport)
        if box is None or self._start is None or self.drag_face is None:
            return 0.0
        moved = (box.face_value(self.drag_face)
                 - self._start.face_value(self.drag_face))
        return moved if self.drag_face % 2 else -moved

    def _drag_value(self, ctx: ToolContext):
        """Where the dragged face goes: where the cursor takes it along its
        axis — and, when a point of the model the cursor names would put the
        face within a few pixels of there, level with that point (a
        magnet, not a jump: a corner of the floor seen past the face used to
        throw the face down to it the moment the drag began)."""
        axis = self.drag_face // 2
        at = self._axis_value(ctx.viewport, ctx.screen.x(), ctx.screen.y())
        if at is None:
            return None
        free = at + self._grab
        snap = getattr(ctx, "snap", None)
        if snap is not None and getattr(snap, "kind", None) in _CORNERS:
            w = ctx.world
            level = (w.x(), w.y(), w.z())[axis]
            if self._pixels_apart(ctx.viewport, free, level) <= _MAGNET_PX:
                return level
        return free

    def _pixels_apart(self, viewport, a: float, b: float) -> float:
        """How far apart on screen the dragged face's centre stands with
        the face at ``a`` and at ``b`` along its axis."""
        pa = viewport._world_to_pixel(self._centre_at(a))
        pb = viewport._world_to_pixel(self._centre_at(b))
        if pa is None or pb is None:
            return float("inf")
        return math.hypot(pa[0] - pb[0], pa[1] - pb[1])

    def _centre_at(self, value: float) -> QVector3D:
        quad = box_face_quad(self._start, self.drag_face)
        c = (quad[0] + quad[2]) * 0.5
        xyz = [c.x(), c.y(), c.z()]
        xyz[self.drag_face // 2] = value
        return QVector3D(*xyz)

    def _axis_value(self, viewport, sx: float, sy: float):
        """Where the cursor at (sx, sy) stands on the dragged face's axis
        (the line through its centre, along its normal)."""
        o, d = viewport._pixel_to_ray(sx, sy)
        if o is None or d is None:
            return None
        quad = box_face_quad(self._start, self.drag_face)
        centre = (quad[0] + quad[2]) * 0.5
        return _closest_on_axis(centre, self.drag_face // 2, o, d)

    def _show(self, viewport, box: SectionBox) -> None:
        """The drag's live box: the scene's own box takes the new corners in
        place — no document change until the commit, which puts the box
        back as it was and changes it in one undo step."""
        live = _live(viewport)
        if live is None:
            return
        live.lo, live.hi = QVector3D(box.lo), QVector3D(box.hi)
        viewport.update()

    def _commit(self, viewport) -> None:
        live = _live(viewport)
        start, self._start = self._start, None
        self.drag_face = None
        self._press = None
        self._moved = False
        if live is None or start is None:
            return
        new = live.copy()
        live.lo, live.hi = QVector3D(start.lo), QVector3D(start.hi)
        if not new.same_as(start):
            viewport.history.execute(
                section_box_changed(viewport.scene, live, new))
        viewport.update()

    def _end_drag(self, viewport, keep: bool) -> None:
        if self.drag_face is not None and self._start is not None \
                and not keep:
            live = _live(viewport)
            if live is not None:
                live.lo = QVector3D(self._start.lo)
                live.hi = QVector3D(self._start.hi)
        self.drag_face = None
        self._start = None
        self._press = None
        self._moved = False
