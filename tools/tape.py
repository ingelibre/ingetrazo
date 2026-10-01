# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Tape Measure tool (T): measure distances and place construction guides.

The classic behaviour, two modes decided by what the first click lands on:

- **From an edge's body** → dragging pulls out an infinite **guide line**
  parallel to that edge, at the dragged (or VCB-typed) offset. This is the
  alignment workflow: pull a guide 2.5 m off a wall, then draw against it.
  A **guide line's body** works the same way (issue #22): pull a
  second guide 2 m off the first, and so on across a whole grid.
- **From free space, or a spot on an edge** → the second click just
  **measures**: the distance shows live at the cursor and in the status bar,
  and stays in the measurements box. No geometry is created.

- **From an axis** (nothing drawn yet) → the same: the red, green or blue
  axis is a source, so a guide 20 m off the origin comes before the first
  line (Rafael, Revisión 3 — how a plan is placed against its datum).
- **From a named point** (endpoint, corner, origin, intersection) → the
  second click, or a typed distance, leaves a **guide point** there with
  its dashed guide segment back to the start (Rafael uses it
  to centre a circle or set a roof's overhang). Clicking another named
  point instead just **measures**, as does starting in free space.

Guides are scaffolding (``Scene.guides``): dashed overlay lines the snap engine
locks onto, erasable with the Eraser or Edit ▸ Delete Guides. Esc cancels.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.guide import Guide
from core.history import AddGuideCommand
from core.i18n import tr
from tools.base import Tool, ToolContext
from core.units import fmt_len, fmt_len_fine

# The drawing axes (core.axes): the open group's own inside it (#44).
from core.axes import AXES as _AXES  # noqa: E402


class TapeMeasureTool(Tool):
    name = "Tape Measure"
    shortcut = "T"
    description = (
        "Measure distances, or pull guide lines off edges to draw "
        "against.")
    vcb_label = "Distance"
    #: The Line tool's axis magnet, both halves (@pacaeiro, issue #41:
    #: «TAPE and PROTRACTOR should have the soft magnetic snap of X, Y,
    #: Z, just like the line tool»): a measurement within 3° of an axis
    #: lands ON it, and the axis the work plane cannot hold is found on
    #: screen. Measuring along an axis is the everyday case.
    magnetic_axis_deg = 3.0
    screen_axis_px = 9.0
    #: The viewport shows «On axis» while this tool hovers a model axis
    #: before its first click (``Viewport._axis_source_cue``).
    axis_source = True

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None
        self.hover_point: QVector3D | None = None
        self.chain_first_point: QVector3D | None = None  # silence close-snap
        self.work_plane: tuple | None = None
        self._edge = None            # source edge → guide-line mode
        self._from_point = False     # started on a named point → guide point
        self._measured: float | None = None
        #: Ctrl on the Tape cycles THREE ways, as the usual status
        #: bar spells out: «Ctrl = Líneas guía del ciclo / Puntos guía /
        #: Medida» (Marco's screenshot, 2026-09-17).
        #:
        #:   "line"    — a guide LINE parallel to the edge clicked (ours)
        #:   "point"   — a guide POINT at the measured distance
        #:   "measure" — nothing left behind
        #:
        #: Reset on pickup, like the usual + (issue #29, @pacaeiro).
        self._mode = "line"

    #: Snap kinds that make the first click a POINT the tape measures
    #: from — a guide segment needs a real point; a midpoint or a
    #: spot on an edge is not one (Rafael: «el punto medio es ficticio»).
    _POINT_KINDS = frozenset(("endpoint", "origin", "intersection",
                              "component_origin", "center"))

    #: The order Ctrl walks, and the label each one flashes.
    _MODES = (("line", "Guides: guide lines"),
              ("point", "Guides: guide points"),
              ("measure", "Guides: off — measure only"))

    def status_clause(self) -> str:
        """The usual wording, kept on screen: «Ctrl = Líneas guía del
        ciclo/Puntos guía/Medida». The active one is bracketed, because the
        cursor's + says "this leaves something" but not WHICH of the two
        guide modes is on."""
        names = {"line": tr("guide lines"), "point": tr("guide points"),
                 "measure": tr("measure")}
        parts = [f"[{v}]" if k == self._mode else v for k, v in names.items()]
        return "Ctrl = " + " / ".join(parts)

    @property
    def _guides(self) -> bool:
        """Whether this mode leaves anything behind."""
        return self._mode != "measure"

    @property
    def cursor_plus(self) -> bool:
        """The little + beside the cursor: this one will leave a
        guide — a line or a point."""
        return self._guides

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        # Picking the tool up starts in guide mode, as users expect — the
        # + «appears or disappears depending on whether you tapped Ctrl
        # SINCE YOU PICKED UP THE TOOL». Ours used to stay off for good, so
        # after one measure-only reading the guides looked broken (Marco,
        # 2026-09-17: «solo funciona con ctrl»).
        self._mode = "line"
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    # ---- Keyboard -----------------------------------------------------------
    def on_key(self, viewport, key: int, modifiers) -> bool:
        # Ctrl toggles guide creation (the Tape either measures or
        # leaves a guide, and the cursor shows a + when it will) -- on the
        # RELEASE of a Ctrl pressed alone. On the press, Ctrl+Z switched
        # the mode too, silently (Alejandro Limón, #183).
        if key == Qt.Key_Control:
            return True
        return super().on_key(viewport, key, modifiers)

    def on_key_release(self, viewport, key: int) -> bool:
        if key != Qt.Key_Control:
            return False
        tapped = getattr(viewport, "ctrl_tapped", None)
        if callable(tapped) and not tapped():
            return False                 # Ctrl was part of a shortcut
        self._toggle_mode(viewport)
        return True

    def _toggle_mode(self, viewport) -> None:
        names = [m for m, _lbl in self._MODES]
        self._mode = names[(names.index(self._mode) + 1) % len(names)]
        viewport.flash_status(
            tr(dict(self._MODES)[self._mode]))
        apply = getattr(viewport, "_apply_tool_cursor", None)
        if apply is not None:
            apply()                  # the + appears or disappears now
        hint = getattr(viewport, "refresh_status_hint", None)
        if hint is not None:
            hint()                   # the clause says the new mode
        viewport.update()

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        if self.start_point is None:
            self.start_point = ctx.world
            # Clicking an edge's BODY starts guide mode; an endpoint measures.
            kind = ctx.snap.kind if ctx.snap is not None else "none"
            # pick_edge_ANY, not pick_edge: the plain one only ever sees
            # the loose mesh, so a click on a component's edge found
            # nothing and fell through to plain measuring (issue #28,
            # @pacaeiro). A group's edges are read from outside
            # without opening it by the rest of IngeTrazo — this
            # is the same picker the Down-arrow reference lock uses, which
            # hands a group's edge back as a world pseudo-edge.
            pick_any = getattr(viewport, "pick_edge_any", None)
            edge = (pick_any(ctx.screen.x(), ctx.screen.y()) if pick_any
                    else viewport.pick_edge(ctx.screen.x(), ctx.screen.y()))
            if edge is None:
                # A guide LINE is a source too (a ``Guide`` exposes the same
                # ``.a``/``.b`` span as an edge): guides pulled from guides
                # are how a grid is laid out (issue #22, @pacaeiro).
                pick = getattr(viewport, "pick_guide", None)
                g = pick(ctx.screen.x(), ctx.screen.y()) if pick else None
                if g is not None and getattr(g, "is_line", False):
                    edge = g
            self._from_point = kind in self._POINT_KINDS
            if (edge is None and kind == "on_axis" and ctx.snap is not None
                    and ctx.snap.axis in _AXES):
                # The cue already found the axis and put the point ON it.
                axis = QVector3D(_AXES[ctx.snap.axis])
                edge = Guide(QVector3D(0, 0, 0), axis)
                self.start_point = QVector3D(ctx.snap.point)
            if edge is None and not self._from_point:
                # The model's own axes are sources too: with nothing drawn
                # yet, a click on the red axis pulls a guide parallel to
                # it (Rafael, Revisión 3). The start is the foot on the
                # axis, so the offset is measured from the line itself.
                pick_axis = getattr(viewport, "pick_axis", None)
                name = (pick_axis(ctx.screen.x(), ctx.screen.y())
                        if pick_axis else None)
                if name is not None:
                    axis = QVector3D(_AXES[name])
                    edge = Guide(QVector3D(0, 0, 0), axis)
                    self.start_point = axis * QVector3D.dotProduct(
                        ctx.world, axis)
            self._edge = edge if (self._mode == "line" and edge is not None
                                  and kind not in ("endpoint", "midpoint",
                                                   "close", "origin",
                                                   "intersection")) else None
            return
        kind = ctx.snap.kind if ctx.snap is not None else "none"
        if self._mode == "point":
            # A guide POINT at the measured spot — no source edge needed,
            # which is the whole use: marking a place on a face.
            self._place_guide_point(viewport, ctx.world)
        elif self._edge is not None:
            offset = self._guide_offset(ctx.world)
            if offset is not None:
                self._place_guide(viewport, offset)
        elif (self._mode == "line" and self._from_point
              and kind not in self._POINT_KINDS
              and (ctx.world - self.start_point).length() > 1e-9):
            # From a named point to a free spot: a guide point there, with
            # its segment back to the start. To another named
            # point it only measures — nobody wants a guide on a corner.
            self._place_guide_point(viewport, ctx.world, self.start_point)
        else:
            dist = (ctx.world - self.start_point).length()
            self._measured = dist
            viewport.flash_status(
                tr("Distance: {d}").format(d=fmt_len_fine(dist)), 4000)
        self._reset()
        viewport.update()

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        ctx.viewport.update()

    def on_value(self, viewport, value) -> bool:
        """Typing a distance places the guide — line or point — exactly
        there, instead of wherever the second click landed."""
        if (self.start_point is None or isinstance(value, tuple)
                or self.hover_point is None):
            return False
        if self._mode == "point":
            d = self.hover_point - self.start_point
            if d.length() < 1e-9:
                return False
            self._place_guide_point(
                viewport, self.start_point + d.normalized() * float(value))
            self._reset()
            viewport.update()
            return True
        if self._edge is None:
            if self._mode == "line" and self._from_point:
                d = self.hover_point - self.start_point
                if d.length() < 1e-9:
                    return False
                self._place_guide_point(
                    viewport, self.start_point + d.normalized() * float(value),
                    self.start_point)
                self._reset()
                viewport.update()
                return True
            return False
        offset = self._guide_offset(self.hover_point)
        if offset is None or offset.length() < 1e-9:
            return False
        self._place_guide(viewport, offset.normalized() * float(value))
        self._reset()
        viewport.update()
        return True

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- Preview ------------------------------------------------------------
    def rubber_band_lines(self):
        if self.start_point is None or self.hover_point is None:
            return []
        if self._edge is not None:
            offset = self._guide_offset(self.hover_point)
            if offset is not None:
                return [(self.start_point, self.start_point + offset)]
        return [(self.start_point, self.hover_point)]

    def guide_preview_lines(self):
        """The guide line the next click leaves, parallel to its source."""
        if (self._edge is None or self.start_point is None
                or self.hover_point is None):
            return []
        offset = self._guide_offset(self.hover_point)
        if offset is None:
            return []
        return [Guide(self.start_point + offset, self._edge_dir()).segment()]

    def value_label(self):
        if self.start_point is None or self.hover_point is None:
            return None
        if self._edge is not None:
            offset = self._guide_offset(self.hover_point)
            d = offset.length() if offset is not None else 0.0
        else:
            d = (self.hover_point - self.start_point).length()
        mid = (self.start_point + self.hover_point) * 0.5
        return (fmt_len(d), mid)

    # ---- Internals ----------------------------------------------------------
    def _edge_dir(self) -> QVector3D:
        return (self._edge.b - self._edge.a).normalized()

    def _guide_offset(self, world: QVector3D) -> QVector3D | None:
        """Cursor offset perpendicular to the source edge (the guide's pull)."""
        if self._edge is None or self.start_point is None:
            return None
        d = self._edge_dir()
        delta = world - self.start_point
        return delta - d * QVector3D.dotProduct(delta, d)

    def _place_guide_point(self, viewport, where: QVector3D,
                           origin: QVector3D | None = None) -> None:
        """A guide POINT (a ``Guide`` with no direction) at ``where`` —
        with its guide segment back to ``origin`` when measured from a
        named point."""
        viewport.history.execute(AddGuideCommand(
            Guide(QVector3D(where), None, origin)))
        d = (where - self.start_point).length()
        viewport.flash_status(
            (tr("Guide point at {d}, with its segment") if origin is not None
             else tr("Guide point at {d}")).format(d=fmt_len_fine(d)), 3000)

    def _place_guide(self, viewport, offset: QVector3D) -> None:
        guide = Guide(self.start_point + offset, self._edge_dir())
        viewport.history.execute(AddGuideCommand(guide))
        viewport.flash_status(
            tr("Guide at {d}").format(d=fmt_len_fine(offset.length())), 3000)

    def _reset(self) -> None:
        self.start_point = None
        self._edge = None
        self._from_point = False
        self.work_plane = None
