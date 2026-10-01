# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Scale tool (S) — the classic grip box.

The rhythm:

- Activating with a selection wraps it in a **yellow box with green grips**
  (26 on a 3D box: 8 corners + 12 edge midpoints + 6 face centres; 8 on a
  flat selection). With nothing selected, the first click picks the entity
  under the cursor and the box appears around it.
- **Corner grips scale uniformly** (all axes, proportions kept). **Edge
  midpoints scale two axes**; **face centres scale one axis** — the
  Measurements box captions the operation "Scale", "Red, Green Scale",
  "Blue Scale"… matching the axis colours.
- Click a grip (it and its **anchor turn red**), move, click again — or
  drag and release. The anchor is the opposite side of the box.
- **Tap Ctrl** toggles *About Center* (anchor = box centre). **Tap Shift**
  toggles *Scale Uniformly* (an edge/face grip scales proportionally).
  Official doc words them as taps that "toggle this functionality".
- The Measurements box takes a **plain number as a factor** ("2" doubles),
  **per-axis factors** separated by ``;`` (our locale's field separator),
  a **negative factor to mirror** through the anchor (type -1, or
  drag a grip past its anchor), and a **number with a unit suffix as the
  new absolute size** of the grip's first axis ("2m" makes that side 2 m).
  Right after committing, typing + Enter redoes the scale at the new value
  (the hot-retype window Rotate already has).

The box sits on the object's OWN axes when a single group or component is
selected (issue #44), and on the drawing axes otherwise — the
world's at the top level, the open group's inside it. It is kept in that
frame's coordinates (``_lo``/``_hi``), mapped to the world to draw and pick.

DEFERRED (documented, not built): the Tape Measure whole-model rescale.
"""
from __future__ import annotations

import itertools

from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.history import (CompoundCommand, ScaleGroupCommand,
                          ScaleVerticesCommand, scale_matrix)
from core.i18n import tr
from tools.base import Tool, ToolContext
from tools.move import gather_images, gather_targets

_MIN_FACTOR = 1e-4
# Below this extent an axis is flat: it gets no grips and never scales
# (a 2D face shows the 8-grip box instead of a degenerate 26).
_FLAT = 1e-6
_AXIS_NAMES = ("Red", "Green", "Blue")     # X east, Y north, Z up (Z-up)


class _Grip:
    """One scaling grip: box-parameter position + the axes it scales."""

    __slots__ = ("params", "mask")

    def __init__(self, params: tuple, mask: tuple) -> None:
        self.params = params               # (tx, ty, tz), each 0 / 0.5 / 1
        self.mask = mask                   # axis indices this grip scales

    def kind(self, active_axes: int) -> str:
        n = len(self.mask)
        if n >= active_axes:
            return "corner"
        return "edge" if n == 2 else "face"


class ScaleTool(Tool):
    name = "Scale"
    shortcut = "S"
    description = (
        "Resize the selection by dragging the grips of its box; the "
        "corners keep its proportions.")
    vcb_label = "Scale"
    @property
    def uses_snap(self) -> bool:
        """Only while a grip is held: then a corner, a midpoint or an edge
        of ANOTHER object sets the size — scale «to» it (issue #233,
        @ales-limon). Before the grab, the grips take the click, not the
        geometry."""
        return self._grip is not None

    # The VCB tags unit-suffixed entries for us ("2m" = absolute size), so a
    # bare "2" can mean ×2, the usual reading.
    accepts_absolute_length = True

    def __init__(self) -> None:
        # Box + grips, in the coordinates of the box's frame (see
        # ``_pick_frame``): the world's unless the selection has its own.
        self._lo: QVector3D | None = None
        self._hi: QVector3D | None = None
        self._axes = None                  # (red, green, blue) or None = world
        self._orig = None
        self._grips: list[_Grip] = []
        self._box_version = -1
        # Targets resolved at grab time.
        self._groups: list = []
        self._positions: list[QVector3D] = []
        self._verts: list = []
        self._images: list = []
        # The operation in flight.
        self._grip: _Grip | None = None
        self._hover_grip: _Grip | None = None
        self._anchor: QVector3D | None = None
        self._factors = (1.0, 1.0, 1.0)    # live preview factors
        self._grabbed_px = None            # screen pos at grab (drag detect)
        self._moved = False
        # A tap toggles.
        self.about_center = False
        self.uniform = False
        # Hot retype window (same mechanism as Rotate).
        self._last: dict | None = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()
        self.about_center = False
        self.uniform = False
        self._last = None
        self._refresh_box(viewport)

    def on_deactivate(self, viewport) -> None:
        self._revert_preview(viewport)
        self._reset()
        self._last = None

    # ---- Box + grips --------------------------------------------------------
    def _selection_bounds(self, viewport):
        """World AABB of the selection: loose vertices, whole groups (their
        nested placements included) and reference images."""
        from core.group import iter_placements
        from core.image_plane import ImagePlane
        from core.mesh import Edge, Face

        self._pick_frame(viewport)
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        seen = False

        def absorb(p: QVector3D) -> None:
            nonlocal seen
            seen = True
            p = self._to_local(p)
            for i, c in enumerate((p.x(), p.y(), p.z())):
                if c < lo[i]:
                    lo[i] = c
                if c > hi[i]:
                    hi[i] = c

        for ent in viewport.scene.selection:
            if isinstance(ent, Edge):
                absorb(ent.a)
                absorb(ent.b)
            elif isinstance(ent, Face):
                for v in ent.vertices:
                    absorb(v)
            elif isinstance(ent, ImagePlane):
                for c in ent.corners():
                    absorb(c)
            elif hasattr(ent, "mesh"):     # Group / component instance
                for pg, m in iter_placements(ent):
                    for v in pg.mesh.vertices:
                        p = m.map(v.position) if m is not None else v.position
                        absorb(p)
        if not seen:
            return None, None
        return QVector3D(*lo), QVector3D(*hi)

    def _refresh_box(self, viewport) -> None:
        """(Re)build the grip box from the selection — cheap to call: keyed on
        ``scene.version``, which selection changes already bump."""
        if self._grip is not None:
            return                          # never while an operation is live
        if viewport.scene.version == self._box_version:
            return
        self._box_version = viewport.scene.version
        self._lo, self._hi = self._selection_bounds(viewport)
        self._grips = []
        self._hover_grip = None
        if self._lo is None:
            return
        ext = self._extents()
        active = [i for i in range(3) if ext[i] > _FLAT]
        if not active:
            self._lo = self._hi = None
            return
        choices = [(0.0, 0.5, 1.0) if i in active else (0.5,)
                   for i in range(3)]
        for params in itertools.product(*choices):
            mask = tuple(i for i in active if params[i] != 0.5)
            if not mask:
                continue                    # the centre is not a grip
            self._grips.append(_Grip(params, mask))

    def _extents(self) -> tuple:
        return (self._hi.x() - self._lo.x(),
                self._hi.y() - self._lo.y(),
                self._hi.z() - self._lo.z())

    def _active_axes(self) -> int:
        ext = self._extents()
        return sum(1 for i in range(3) if ext[i] > _FLAT)

    # ---- The box's frame (issue #44) ----------------------------------------
    def _pick_frame(self, viewport) -> None:
        """One group or component selected: its own axes. Anything else:
        the drawing axes. The world frame is kept as ``None`` so every
        number is exactly what it was before the box could turn."""
        from core import axes
        from core.group import Group, frame_axes, group_frame
        sel = list(viewport.scene.selection)
        frame = None
        if len(sel) == 1 and isinstance(sel[0], Group):
            frame = group_frame(sel[0])
        if frame is None and not axes.is_world():
            frame = axes.frame_matrix(axes.ORIGIN, *[axes.AXES[k]
                                                     for k in "xyz"])
        if frame is None:
            self._axes, self._orig = None, None
            return
        o, x, y, z = frame_axes(frame)
        if (x, y, z) == (QVector3D(1, 0, 0), QVector3D(0, 1, 0),
                         QVector3D(0, 0, 1)):
            self._axes, self._orig = None, None
            return
        self._axes, self._orig = (x, y, z), o

    def _to_local(self, p: QVector3D) -> QVector3D:
        if self._axes is None:
            return QVector3D(p)
        d = p - self._orig
        x, y, z = self._axes
        return QVector3D(QVector3D.dotProduct(d, x), QVector3D.dotProduct(d, y),
                         QVector3D.dotProduct(d, z))

    def _to_world(self, p: QVector3D) -> QVector3D:
        if self._axes is None:
            return QVector3D(p)
        x, y, z = self._axes
        return self._orig + x * p.x() + y * p.y() + z * p.z()

    def _grip_pos(self, grip: _Grip) -> QVector3D:
        lo, hi = self._lo, self._hi
        t = grip.params
        return self._to_world(QVector3D(lo.x() + (hi.x() - lo.x()) * t[0],
                                        lo.y() + (hi.y() - lo.y()) * t[1],
                                        lo.z() + (hi.z() - lo.z()) * t[2]))

    def _anchor_for(self, grip: _Grip) -> QVector3D:
        """The point straight opposite the grip — or the box centre
        while About Center is toggled on."""
        if self.about_center:
            return self._to_world((self._lo + self._hi) * 0.5)
        params = tuple(1.0 - t if i in grip.mask else 0.5
                       for i, t in enumerate(grip.params))
        return self._grip_pos(_Grip(params, grip.mask))

    def _grip_under(self, viewport, sx: float, sy: float) -> _Grip | None:
        threshold = float(getattr(viewport, "pick_threshold_px", 10.0))
        best, best_d = None, threshold
        for g in self._grips:
            px = viewport._world_to_pixel(self._grip_pos(g))
            if px is None:
                continue
            d = ((px[0] - sx) ** 2 + (px[1] - sy) ** 2) ** 0.5
            if d < best_d:
                best, best_d = g, d
        return best

    # ---- Cursor → factors ---------------------------------------------------
    def _ray(self, viewport, sx: float, sy: float):
        return viewport._pixel_to_ray(sx, sy)

    @staticmethod
    def _closest_on_line(o, d, a, u):
        """Point on line (a, u) closest to ray (o, d); None if parallel."""
        b = QVector3D.dotProduct(d, u)
        denom = 1.0 - b * b
        if abs(denom) < 1e-9:
            return None
        w = o - a
        d0 = QVector3D.dotProduct(d, w)
        e = QVector3D.dotProduct(u, w)
        s = (e - b * d0) / denom
        return a + u * s

    #: What a held grip may land on: named points and edges, projected onto
    #: the grip's line. Not a face (the grip would jump across every
    #: surface it passes) and not the engine's own directional inferences.
    _TARGET_KINDS = frozenset({
        "endpoint", "midpoint", "intersection", "center", "origin",
        "on_edge", "on_line", "from_point", "close", "guide",
        "component_origin", "arc_midpoint"})

    def snap_excluded(self):
        """What is being scaled stays out of the snap engine, or the grip
        would land on the very geometry it resizes. ``(edge ids, group
        ids)`` as Move gives it."""
        if self._grip is None:
            return None
        edges = {id(e) for v in self._verts for e in getattr(v, "edges", ())}
        return edges, {id(g) for g in self._groups}

    def _snapped_point(self, ctx):
        snap = getattr(ctx, "snap", None) if ctx is not None else None
        if snap is None or snap.kind not in self._TARGET_KINDS:
            return None
        return QVector3D(snap.point)

    def _factors_from_point(self, p: QVector3D):
        """The factors that put the held grip level with world point ``p``:
        ``p`` projected onto the anchor→grip line (one axis, or a corner /
        Shift), or per axis for an edge grip."""
        grip, anchor = self._grip, self._anchor
        g0 = self._grip_pos(grip)
        uniform = self.uniform or grip.kind(self._active_axes()) == "corner"
        if uniform or len(grip.mask) == 1:
            axis_dir = g0 - anchor
            length = axis_dir.length()
            if length < 1e-12:
                return None
            f = QVector3D.dotProduct(p - anchor, axis_dir) / (length * length)
            if uniform:
                ext = self._extents()
                return tuple(f if ext[i] > _FLAT else 1.0 for i in range(3))
            factors = [1.0, 1.0, 1.0]
            factors[grip.mask[0]] = f
            return tuple(factors)
        gl = self._to_local(g0) - self._to_local(anchor)
        pl = self._to_local(p) - self._to_local(anchor)
        factors = [1.0, 1.0, 1.0]
        for i in grip.mask:
            ga = (gl.x(), gl.y(), gl.z())[i]
            if abs(ga) < 1e-12:
                return None
            factors[i] = (pl.x(), pl.y(), pl.z())[i] / ga
        return tuple(factors)

    def _factors_for(self, ctx, viewport, sx: float, sy: float):
        p = self._snapped_point(ctx)
        if p is not None:
            got = self._factors_from_point(p)
            if got is not None:
                return got
        return self._factors_from_cursor(viewport, sx, sy)

    def _factors_from_cursor(self, viewport, sx: float, sy: float):
        grip, anchor = self._grip, self._anchor
        g0 = self._grip_pos(grip)
        o, d = self._ray(viewport, sx, sy)
        if o is None:
            return None
        uniform = self.uniform or grip.kind(self._active_axes()) == "corner"
        if uniform or len(grip.mask) == 1:
            # Cursor tracked along the anchor→grip line; crossing the anchor
            # flips the factor negative — the drag-past-zero mirror.
            axis_dir = g0 - anchor
            length = axis_dir.length()
            if length < 1e-12:
                return None
            u = axis_dir / length
            p = self._closest_on_line(o, d, anchor, u)
            if p is None:
                return None
            f = QVector3D.dotProduct(p - anchor, u) / length
            if uniform:
                ext = self._extents()
                return tuple(f if ext[i] > _FLAT else 1.0 for i in range(3))
            factors = [1.0, 1.0, 1.0]
            factors[grip.mask[0]] = f
            return tuple(factors)
        # Two axes (edge midpoint): track on the grip's own box plane.
        normal_axis = next(i for i in range(3) if i not in grip.mask)
        if self._axes is None:
            n = QVector3D(*[1.0 if i == normal_axis else 0.0
                            for i in range(3)])
        else:
            n = QVector3D(self._axes[normal_axis])
        denom = QVector3D.dotProduct(n, d)
        if abs(denom) < 1e-9:
            return None
        t = QVector3D.dotProduct(n, g0 - o) / denom
        if t < 0:
            return None
        p = o + d * t
        factors = [1.0, 1.0, 1.0]
        if self._axes is not None:
            gl = self._to_local(g0) - self._to_local(anchor)
            pl = self._to_local(p) - self._to_local(anchor)
            for i in grip.mask:
                ga = (gl.x(), gl.y(), gl.z())[i]
                if abs(ga) < 1e-12:
                    return None
                factors[i] = (pl.x(), pl.y(), pl.z())[i] / ga
            return tuple(factors)
        for i in grip.mask:
            ga = [g0.x(), g0.y(), g0.z()][i] - [anchor.x(), anchor.y(),
                                                anchor.z()][i]
            if abs(ga) < 1e-12:
                return None
            pa = [p.x(), p.y(), p.z()][i] - [anchor.x(), anchor.y(),
                                             anchor.z()][i]
            factors[i] = pa / ga
        return tuple(factors)

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        self._last = None                  # a click closes the retype window
        self._refresh_box(viewport)
        sx, sy = ctx.screen.x(), ctx.screen.y()

        if self._grip is not None:         # second click commits
            factors = self._factors_for(ctx, viewport, sx, sy)
            if factors is not None:
                self._commit(viewport, factors)
            return

        if self._lo is not None:
            grip = self._grip_under(viewport, sx, sy)
            if grip is not None:
                self._grab(viewport, grip, (sx, sy))
                return

        # No grip hit: with nothing selected, a click picks the entity under
        # the cursor and boxes it (click-to-scale).
        if not viewport.scene.selection:
            groups, positions = gather_targets(ctx)
            images = gather_images(ctx)
            picked = list(groups) + list(images)
            if not picked and positions:
                edge = viewport.pick_edge(sx, sy)
                face = viewport.pick_face(sx, sy) if edge is None else None
                picked = [e for e in (edge, face) if e is not None]
            if picked:
                viewport.scene.select(picked)
                self._refresh_box(viewport)
                viewport.update()
                return
            viewport.flash_status(
                tr("Select (or click) the geometry to scale first"))

    def _grab(self, viewport, grip: _Grip, screen_xy) -> None:
        from core.image_plane import ImagePlane
        from core.mesh import Edge, Face

        sel = viewport.scene.selection
        self._groups = [g for g in sel if hasattr(g, "mesh")
                        and not isinstance(g, (Edge, Face))]
        self._images = [im for im in sel if isinstance(im, ImagePlane)]
        positions: list[QVector3D] = []
        for ent in sel:
            if isinstance(ent, Edge):
                positions.extend([ent.a, ent.b])
            elif isinstance(ent, Face):
                positions.extend(ent.vertices)
        seen: list[QVector3D] = []
        for p in positions:
            if not any((p - q).length() < 1e-9 for q in seen):
                seen.append(QVector3D(p))
        self._positions = seen
        mesh = viewport.scene.mesh
        self._verts = [v for v in (mesh.vertex_at(p) for p in seen)
                       if v is not None]
        self._grip = grip
        self._anchor = self._anchor_for(grip)
        self._factors = (1.0, 1.0, 1.0)
        self._capture_originals(viewport)
        self._grabbed_px = screen_xy
        self._moved = False
        viewport.update()

    def on_hover(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        sx, sy = ctx.screen.x(), ctx.screen.y()
        if self._grip is None:
            self._refresh_box(viewport)
            hover = (self._grip_under(viewport, sx, sy)
                     if self._lo is not None else None)
            if hover is not self._hover_grip:
                self._hover_grip = hover
                viewport.update()
            return
        factors = self._factors_for(ctx, viewport, sx, sy)
        if factors is None:
            return
        if any(abs(f) < _MIN_FACTOR for f in factors):
            return
        if self._grabbed_px is not None:
            dx = sx - self._grabbed_px[0]
            dy = sy - self._grabbed_px[1]
            if (dx * dx + dy * dy) ** 0.5 > 4.0:
                self._moved = True
        self._apply_preview(viewport, factors)
        viewport.update()

    def on_release(self, viewport) -> None:
        """Both rhythms are accepted: click-move-click AND drag-release.
        A release after a real drag commits; a release in place leaves the
        operation live for the second click."""
        if self._grip is None or not self._moved:
            return
        if any(abs(f - 1.0) > 1e-9 for f in self._factors):
            self._commit(viewport, self._factors)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key_Control:
            # Official doc: "tap the Ctrl key … to toggle this functionality".
            self.about_center = not self.about_center
            self._reanchor(viewport)
            viewport.flash_status(
                tr("About Center: on") if self.about_center
                else tr("About Center: off"))
            return True
        if key == Qt.Key_Shift:
            self.uniform = not self.uniform
            viewport.flash_status(
                tr("Scale Uniformly: on") if self.uniform
                else tr("Scale Uniformly: off"))
            viewport.update()
            return True
        return False

    def _reanchor(self, viewport) -> None:
        """Ctrl mid-operation moves the anchor between centre and opposite
        side without losing the factors already dragged."""
        if self._grip is None:
            return
        current = self._factors
        self._apply_preview(viewport, (1.0, 1.0, 1.0))
        self._anchor = self._anchor_for(self._grip)
        self._apply_preview(viewport, current)
        viewport.update()

    def value_is_unitless(self) -> bool:
        """A bare number is a FACTOR, never a length (#176); one typed
        with a unit is the new size and still converts."""
        return True

    def on_value(self, viewport, value) -> bool:
        absolute = False
        if isinstance(value, tuple) and value and value[0] == "abs_len":
            absolute, value = True, value[1]
        if self._grip is not None:
            factors = self._typed_factors(value, absolute)
            if factors is None:
                return False
            self._commit(viewport, factors)
            return True
        if self._last is not None:
            # Hot retype: redo the scale just made at the new value.
            last = self._last
            stack = getattr(viewport.history, "undo_stack", None)
            if not stack or stack[-1] is not last["cmd"]:
                self._last = None
                return False
            factors = self._typed_factors(value, absolute, spec=last["spec"])
            if factors is None:
                return False
            viewport.history.undo()
            cmd = last["build"](factors)
            viewport.history.execute(cmd)
            self._last = {"cmd": cmd, "build": last["build"],
                          "spec": last["spec"]}
            viewport.update()
            return True
        return False

    def _typed_factors(self, value, absolute: bool, spec=None):
        """Map a typed value onto per-axis factors, the usual reading:
        one number = the grip's factor; ``a;b`` / ``a;b;c`` = one per axis of
        the grip; with a unit suffix the numbers are the new absolute sizes
        (metres) instead of factors."""
        if spec is None:
            grip = self._grip
            uniform = (self.uniform
                       or grip.kind(self._active_axes()) == "corner")
            mask = grip.mask
            ext = self._extents()
            active = tuple(i for i in range(3) if ext[i] > _FLAT)
        else:
            uniform, mask, ext, active = spec
        values = value if isinstance(value, tuple) else (value,)
        if not all(isinstance(v, float) for v in values):
            return None
        if any(abs(v) < _MIN_FACTOR for v in values):
            return None
        axes = active if uniform else mask
        factors = [1.0, 1.0, 1.0]
        if len(values) == 1:
            f = values[0]
            if absolute:
                base = ext[axes[0]]
                if base <= _FLAT:
                    return None
                f = f / base
            for i in axes:
                factors[i] = f
            return tuple(factors)
        if len(values) != len(axes):
            return None
        for i, v in zip(axes, values):
            if absolute:
                if ext[i] <= _FLAT:
                    return None
                v = v / ext[i]
            factors[i] = v
        return tuple(factors)

    def on_cancel(self, viewport) -> None:
        self._revert_preview(viewport)
        self._grip = None
        self._anchor = None
        self._last = None
        viewport.update()

    # ---- Live preview -------------------------------------------------------
    def _capture_originals(self, viewport) -> None:
        """Where everything that scales stood when the grip was taken. The
        live preview is computed from THESE on every move — never as a step
        from the previous frame. Chained steps drift in float32, and a drag
        that went down to 0.04 and back ended with some vertices a hair off
        their starting cell: the commit, which finds the vertices by their
        starting positions, missed them, scaled the rest and tore the
        faces (a user's video, 25-09: a rounded box shredded on release).
        Measured: 300 moves of that kind, 194 of 1600 vertices lost."""
        from PySide6.QtGui import QMatrix4x4
        orig_v: list = []
        orig_x: list = []
        for group in self._groups:
            if getattr(group, "xform", None) is not None:
                orig_x.append((group, QMatrix4x4(group.xform)))
            else:
                gmesh = group.mesh
                orig_v.extend((gmesh, v, QVector3D(v.position))
                              for v in gmesh.vertices)
        mesh = viewport.scene.mesh
        orig_v.extend((mesh, v, QVector3D(v.position)) for v in self._verts)
        self._orig_v = orig_v
        self._orig_x = orig_x
        self._orig_im = [(im, QVector3D(im.origin), QVector3D(im.u),
                          QVector3D(im.v)) for im in self._images]

    def _set_preview(self, viewport, factors: tuple) -> None:
        """Put everything at *factors* about the anchor, from the originals.
        At (1, 1, 1) it is an exact restore: the starting positions go back
        as they were stored, not through a matrix."""
        if getattr(self, "_orig_v", None) is None:
            return
        identity = all(abs(f - 1.0) < 1e-12 for f in factors)
        m = None if identity else scale_matrix(self._anchor, factors,
                                               self._axes)
        for mesh, v, p0 in self._orig_v:
            target = p0 if m is None else m.map(p0)
            mesh.move_vertex(v, target - v.position)
        for group, x0 in self._orig_x:
            group.xform = QMatrix4x4(x0) if m is None else m * x0
        for im, o0, u0, v0 in self._orig_im:
            if m is None:
                im.origin, im.u, im.v = (QVector3D(o0), QVector3D(u0),
                                         QVector3D(v0))
            else:
                im.origin, im.u, im.v = (m.map(o0), m.mapVector(u0),
                                         m.mapVector(v0))
        viewport.scene.version += 1

    def _apply_preview(self, viewport, target: tuple) -> None:
        if all(abs(t - f) < 1e-12 for t, f in zip(target, self._factors)):
            return
        self._set_preview(viewport, target)
        self._factors = target

    def _revert_preview(self, viewport) -> None:
        if any(abs(f - 1.0) > 1e-12 for f in self._factors):
            self._set_preview(viewport, (1.0, 1.0, 1.0))
            self._factors = (1.0, 1.0, 1.0)

    # ---- Commit -------------------------------------------------------------
    def _commit(self, viewport, factors: tuple) -> None:
        self._revert_preview(viewport)
        grip = self._grip
        uniform = (self.uniform
                   or (grip is not None
                       and grip.kind(self._active_axes()) == "corner"))
        mask = grip.mask if grip is not None else (0, 1, 2)
        ext = self._extents() if self._lo is not None else (1.0, 1.0, 1.0)
        active = tuple(i for i in range(3) if ext[i] > _FLAT)
        spec = (uniform, mask, ext, active)
        anchor = QVector3D(self._anchor)
        box_axes = self._axes
        groups = list(self._groups)
        positions = list(self._positions)
        images = list(self._images)

        def build(fs: tuple):
            packed = (fs[0] if fs[0] == fs[1] == fs[2] else fs)
            cmds: list = [ScaleGroupCommand(g, anchor, packed, box_axes)
                          for g in groups]
            if positions:
                cmds.append(ScaleVerticesCommand(positions, anchor, packed,
                                                 box_axes))
            if images:
                from core.history import ScaleImagePlanesCommand
                cmds.append(ScaleImagePlanesCommand(images, anchor, packed,
                                                    box_axes))
            if not cmds:
                return None
            return cmds[0] if len(cmds) == 1 else CompoundCommand(cmds)

        changed = any(abs(f - 1.0) > 1e-9 for f in factors)
        if changed and all(abs(f) >= _MIN_FACTOR for f in factors):
            cmd = build(factors)
            if cmd is not None:
                viewport.history.execute(cmd)
                # Right after scaling, a typed value redoes it.
                self._last = {"cmd": cmd, "build": build, "spec": spec}
        self._grip = None
        self._anchor = None
        self._factors = (1.0, 1.0, 1.0)
        self._orig_v = None                 # the operation is over
        self._box_version = -1              # geometry moved: rebuild the box
        self._refresh_box(viewport)
        viewport.update()

    def _reset(self) -> None:
        self._lo = self._hi = None
        self._grips = []
        self._grip = None
        self._hover_grip = None
        self._anchor = None
        self._factors = (1.0, 1.0, 1.0)
        self._groups = []
        self._positions = []
        self._verts = []
        self._images = []
        self._orig_v = None
        self._box_version = -1
        self._grabbed_px = None
        self._moved = False

    # ---- Feedback -----------------------------------------------------------
    def vcb_caption(self) -> str:
        """Caption the Measurements box by the axes in play."""
        grip = self._grip or self._hover_grip
        if grip is None:
            return "Scale"
        if self.uniform or grip.kind(self._active_axes()) == "corner":
            return "Scale"
        names = ", ".join(_AXIS_NAMES[i] for i in grip.mask)
        return f"{names} Scale"

    def value_label(self):
        """The live factor readout beside the box: one number
        for a uniform scale, one per axis otherwise."""
        if self._grip is None:
            return None
        if self.uniform or self._grip.kind(self._active_axes()) == "corner":
            text = f"{self._factors[self._grip.mask[0]]:.2f}"
        else:
            text = "; ".join(f"{self._factors[i]:.2f}"
                             for i in self._grip.mask)
        pos = (self._grip_pos(self._grip) if self._lo is not None
               else self._anchor)
        return (text, pos)

    # ---- What the viewport draws -------------------------------------------
    def scale_box_state(self):
        """Everything the overlay needs: the (live-scaled) box segments and
        each grip with its role — ``idle`` green, ``hover``/``active``/
        ``anchor`` red, as the official doc describes them."""
        if self._lo is None:
            return None
        lo, hi = self._lo, self._hi
        m = (scale_matrix(self._anchor, self._factors, self._axes)
             if self._grip is not None else None)

        def corner(tx, ty, tz):
            p = self._to_world(QVector3D(lo.x() + (hi.x() - lo.x()) * tx,
                                         lo.y() + (hi.y() - lo.y()) * ty,
                                         lo.z() + (hi.z() - lo.z()) * tz))
            return m.map(p) if m is not None else p

        ext = self._extents()
        axes = [i for i in range(3) if ext[i] > _FLAT]
        segments = []
        if len(axes) >= 2:
            # Every box edge that spans a non-flat axis.
            for axis in axes:
                others = [i for i in range(3) if i != axis]
                for ta in ((0.0,) if ext[others[0]] <= _FLAT else (0.0, 1.0)):
                    for tb in ((0.0,) if ext[others[1]] <= _FLAT
                               else (0.0, 1.0)):
                        t0 = [0.0, 0.0, 0.0]
                        t0[others[0]], t0[others[1]] = ta, tb
                        t1 = list(t0)
                        t1[axis] = 1.0
                        segments.append((corner(*t0), corner(*t1)))
        elif len(axes) == 1:
            t0 = [0.5, 0.5, 0.5]
            t1 = list(t0)
            t0[axes[0]], t1[axes[0]] = 0.0, 1.0
            segments.append((corner(*t0), corner(*t1)))
        grips = []
        for g in self._grips:
            p = self._grip_pos(g)
            if m is not None:
                p = m.map(p)
            role = "idle"
            if g is self._grip:
                role = "active"
            elif g is self._hover_grip and self._grip is None:
                role = "hover"
            grips.append((p, role))
        if self._grip is not None and self._anchor is not None:
            grips.append((QVector3D(self._anchor), "anchor"))
        return {"segments": segments, "grips": grips}
