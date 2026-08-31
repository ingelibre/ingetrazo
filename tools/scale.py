# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Scale tool (S) — SketchUp's grip box, built from the official doc
("Scaling Your Model or Parts of Your Model", help.sketchup.com).

The rhythm SketchUp documents:

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
  a **negative factor to mirror** through the anchor (SketchUp: type -1, or
  drag a grip past its anchor), and a **number with a unit suffix as the
  new absolute size** of the grip's first axis ("2m" makes that side 2 m).
  Right after committing, typing + Enter redoes the scale at the new value
  (the hot-retype window Rotate already has).

DEFERRED (documented, not built): the box aligned to a component's own
axes (today it is world-aligned), and the Tape Measure whole-model rescale.
"""
from __future__ import annotations

import itertools

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.history import (CompoundCommand, ScaleGroupCommand,
                          ScaleVerticesCommand, scale_matrix)
from core.i18n import tr
from tools.base import Tool, ToolContext
from tools.move import gather_images, gather_targets

_MIN_FACTOR = 1e-4
# Below this extent an axis is flat: it gets no grips and never scales
# (a 2D face shows SketchUp's 8-grip box instead of a degenerate 26).
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
    vcb_label = "Scale"
    uses_snap = False                      # grips, not geometry, take the click
    # The VCB tags unit-suffixed entries for us ("2m" = absolute size), so a
    # bare "2" can mean ×2 the way SketchUp reads it.
    accepts_absolute_length = True

    def __init__(self) -> None:
        # Box + grips (world-axis aligned, over the current selection).
        self._lo: QVector3D | None = None
        self._hi: QVector3D | None = None
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
        # SketchUp's tap toggles.
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

        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        seen = False

        def absorb(p: QVector3D) -> None:
            nonlocal seen
            seen = True
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

    def _grip_pos(self, grip: _Grip) -> QVector3D:
        lo, hi = self._lo, self._hi
        t = grip.params
        return QVector3D(lo.x() + (hi.x() - lo.x()) * t[0],
                         lo.y() + (hi.y() - lo.y()) * t[1],
                         lo.z() + (hi.z() - lo.z()) * t[2])

    def _anchor_for(self, grip: _Grip) -> QVector3D:
        """SketchUp: the point straight opposite the grip — or the box centre
        while About Center is toggled on."""
        if self.about_center:
            return (self._lo + self._hi) * 0.5
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

    def _factors_from_cursor(self, viewport, sx: float, sy: float):
        grip, anchor = self._grip, self._anchor
        g0 = self._grip_pos(grip)
        o, d = self._ray(viewport, sx, sy)
        if o is None:
            return None
        uniform = self.uniform or grip.kind(self._active_axes()) == "corner"
        if uniform or len(grip.mask) == 1:
            # Cursor tracked along the anchor→grip line; crossing the anchor
            # flips the factor negative — SketchUp's drag-past-zero mirror.
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
        n = QVector3D(*[1.0 if i == normal_axis else 0.0 for i in range(3)])
        denom = QVector3D.dotProduct(n, d)
        if abs(denom) < 1e-9:
            return None
        t = QVector3D.dotProduct(n, g0 - o) / denom
        if t < 0:
            return None
        p = o + d * t
        factors = [1.0, 1.0, 1.0]
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
            factors = self._factors_from_cursor(viewport, sx, sy)
            if factors is not None:
                self._commit(viewport, factors)
            return

        if self._lo is not None:
            grip = self._grip_under(viewport, sx, sy)
            if grip is not None:
                self._grab(viewport, grip, (sx, sy))
                return

        # No grip hit: with nothing selected, a click picks the entity under
        # the cursor and boxes it (SketchUp's click-to-scale).
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
        factors = self._factors_from_cursor(viewport, sx, sy)
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
        """SketchUp accepts both rhythms: click-move-click AND drag-release.
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
        """Map a typed value onto per-axis factors, SketchUp's reading:
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
    def _scale_live(self, viewport, step: tuple) -> None:
        if all(abs(f - 1.0) < 1e-12 for f in step):
            return
        m = scale_matrix(self._anchor, step)
        for group in self._groups:
            if getattr(group, "xform", None) is not None:
                group.xform = m * group.xform   # instance: O(1)
            else:
                gmesh = group.mesh
                for vx in list(gmesh.vertices):
                    gmesh.move_vertex(vx, m.map(vx.position) - vx.position)
        for vx in self._verts:
            viewport.scene.mesh.move_vertex(
                vx, m.map(vx.position) - vx.position)
        for im in self._images:
            im.origin = m.map(im.origin)
            im.u = m.mapVector(im.u)
            im.v = m.mapVector(im.v)
        viewport.scene.version += 1

    def _apply_preview(self, viewport, target: tuple) -> None:
        step = tuple(t / f for t, f in zip(target, self._factors))
        self._scale_live(viewport, step)
        self._factors = target

    def _revert_preview(self, viewport) -> None:
        if any(abs(f - 1.0) > 1e-12 for f in self._factors):
            self._scale_live(
                viewport, tuple(1.0 / f for f in self._factors))
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
        groups = list(self._groups)
        positions = list(self._positions)
        images = list(self._images)

        def build(fs: tuple):
            packed = (fs[0] if fs[0] == fs[1] == fs[2] else fs)
            cmds: list = [ScaleGroupCommand(g, anchor, packed)
                          for g in groups]
            if positions:
                cmds.append(ScaleVerticesCommand(positions, anchor, packed))
            if images:
                from core.history import ScaleImagePlanesCommand
                cmds.append(ScaleImagePlanesCommand(images, anchor, packed))
            if not cmds:
                return None
            return cmds[0] if len(cmds) == 1 else CompoundCommand(cmds)

        changed = any(abs(f - 1.0) > 1e-9 for f in factors)
        if changed and all(abs(f) >= _MIN_FACTOR for f in factors):
            cmd = build(factors)
            if cmd is not None:
                viewport.history.execute(cmd)
                # SketchUp: right after scaling, a typed value redoes it.
                self._last = {"cmd": cmd, "build": build, "spec": spec}
        self._grip = None
        self._anchor = None
        self._factors = (1.0, 1.0, 1.0)
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
        self._box_version = -1
        self._grabbed_px = None
        self._moved = False

    # ---- Feedback -----------------------------------------------------------
    def vcb_caption(self) -> str:
        """SketchUp captions the Measurements box by the axes in play."""
        grip = self._grip or self._hover_grip
        if grip is None:
            return "Scale"
        if self.uniform or grip.kind(self._active_axes()) == "corner":
            return "Scale"
        names = ", ".join(_AXIS_NAMES[i] for i in grip.mask)
        return f"{names} Scale"

    def value_label(self):
        """The live factor readout beside the box, SketchUp-style: one number
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
        m = (scale_matrix(self._anchor, self._factors)
             if self._grip is not None else None)

        def corner(tx, ty, tz):
            p = QVector3D(lo.x() + (hi.x() - lo.x()) * tx,
                          lo.y() + (hi.y() - lo.y()) * ty,
                          lo.z() + (hi.z() - lo.z()) * tz)
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
