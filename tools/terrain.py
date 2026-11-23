# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Draw ▸ Terrain: build ground out of triangles and shape it.

- **Terrain from Scratch** (:class:`TerrainGridTool`): two clicks lay a
  rectangular grid of triangles at the first click's level — flat, or
  with natural irregularities. Typed before the first click, a length
  sets the cell size and ``cell;relief`` the irregularities too (``1;0.8``:
  1 m cells, swells and hollows up to 0.8 m; ``…;0`` flat again); after
  it, ``width;height`` sets the rectangle. The grid is one new group named
  «Terrain», its inner edges soft.
- **Deform Terrain** (:class:`TerrainDeformTool`): click the ground, move
  up or down and click again; the ground rises (or sinks) by that much at
  the point and less and less out to the radius, smoothly. Typed before
  the click, a length sets the radius; after it, the height.

- **Stamp Platform** (:class:`TerrainStampTool`): click a face — a
  house's footprint drawn over the ground — then the ground, move up or
  down and click: a level platform that shape is cut into the ground,
  with a straight slope round it out to where it meets the ground. Typed
  before, a length sets the slope's width; after, the rise above the
  shape.
- **Drape** (:class:`TerrainDrapeTool`): select edges (a path, a
  boundary) and click the ground: they are cut into it, seen from above,
  as lines on the terrain.

- **Flip Edge** (:class:`TerrainFlipTool`): click near an inner edge of
  the ground; the two triangles on it take the other diagonal — a ridge
  or a valley the triangulation drew the wrong way, put right.
- **Add Detail** (:class:`TerrainDetailTool`): click the ground; the
  triangles within the radius split in four, keeping the shape, for a
  finer Deform or Stamp there. Typed first, the radius (0: one triangle).

- **Terrain from Contours** / **from Points**: select contour lines at
  their heights, or survey points (guide points — a DXF's points arrive
  as such — edges, groups), and pick the tool up: a terrain through them
  (:mod:`core.terrain_build`). A number typed right after sets the cell
  size / the longest rim side and builds it again.
- **Set Height** (:class:`TerrainHeightTool`): click a flat contour or a
  guide point and type its height — what a 2D drawing only wrote in a
  label.

Deform, Stamp and Drape work on any triangulated geometry — the loose geometry, the open
group's, or a group's own from outside it, whoever built it — through
:class:`core.terrain_mesh.DeformTerrainCommand` (one undo step).
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.i18n import tr
from core.terrain_mesh import (MIN_SIZE,
                               DeformTerrainCommand, deform_preview,
                               grid_cells, grid_terrain, terrain_group)
from tools.base import Tool, ToolContext

_UP = QVector3D(0.0, 0.0, 1.0)
#: Segments of the radius ring drawn round the cursor.
_RING_SEGMENTS = 48
#: Grid lines drawn in the preview, at most, along each side.
_PREVIEW_LINES = 60


def _fmt(length: float) -> str:
    from core.units import fmt_len
    return fmt_len(length)


def _vertical_plane(viewport, anchor: QVector3D):
    """The vertical plane through ``anchor`` that faces the camera — the ray
    always hits it, so the height can be read off any pixel."""
    cam = getattr(viewport, "camera", None)
    if cam is None or anchor is None:
        return None
    forward = cam.target - cam.eye()
    side = forward - _UP * QVector3D.dotProduct(forward, _UP)
    if side.length() < 1e-6:
        return None                     # straight down: no such plane
    return QVector3D(anchor), side.normalized()


class TerrainGridTool(Tool):
    """Draw ▸ Terrain ▸ Terrain from Scratch."""

    name = "Terrain from Scratch"
    description = ("Lay a grid of triangles to shape into terrain, flat or "
                   "irregular. Type the cell size first.")
    vcb_label = "Cell size"
    allow_inferences = False

    #: The cell size the next grid takes (model units); kept between uses.
    cell = 1.0
    #: How far the next grid's irregularities rise and sink (0 = flat).
    relief = 0.0

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None
        self.hover_point: QVector3D | None = None

    def vcb_caption(self) -> str:
        return "Dimensions" if self.start_point is not None else "Cell size"

    def on_activate(self, viewport) -> None:
        self.start_point = None
        self.hover_point = None

    def on_deactivate(self, viewport) -> None:
        self.on_activate(viewport)

    def on_cancel(self, viewport) -> None:
        self.start_point = None
        viewport.update()

    def drag_plane(self, viewport):
        if self.start_point is None:
            return None
        return QVector3D(self.start_point), QVector3D(_UP)

    def _level(self, p: QVector3D) -> QVector3D:
        """``p`` brought down (or up) to the level of the first click."""
        return QVector3D(p.x(), p.y(), self.start_point.z())

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        if self.start_point is None:
            self.start_point = QVector3D(ctx.world)
            return
        self._commit(ctx.viewport, self._level(ctx.world))

    def on_value(self, viewport, value) -> bool:
        if self.start_point is None:
            relief = self.relief
            if isinstance(value, tuple):
                if len(value) != 2:
                    return False
                value, relief = (float(x) for x in value)
                if relief < 0.0:
                    return False
            if value < MIN_SIZE:
                return False
            self.cell, self.relief = float(value), float(relief)
            if self.relief > 0.0:
                viewport.flash_status(tr(
                    "Cell size: {size}, relief: {relief}",
                    size=_fmt(self.cell), relief=_fmt(self.relief)))
            else:
                viewport.flash_status(tr("Cell size: {size}",
                                         size=_fmt(self.cell)))
            self.refresh_hint(viewport)
            return True
        if isinstance(value, tuple) and len(value) == 2:
            w, h = (abs(float(x)) for x in value)
        elif not isinstance(value, tuple):
            w = h = abs(float(value))
        else:
            return False
        if w < MIN_SIZE or h < MIN_SIZE:
            return False
        # Toward the side the cursor is heading, like the Rectangle.
        sx = sy = 1.0
        if self.hover_point is not None:
            sx = -1.0 if self.hover_point.x() < self.start_point.x() else 1.0
            sy = -1.0 if self.hover_point.y() < self.start_point.y() else 1.0
        far = self.start_point + QVector3D(sx * w, sy * h, 0.0)
        self._commit(viewport, far)
        return True

    def _commit(self, viewport, far: QVector3D) -> None:
        vertices, triangles = grid_terrain(self.start_point, far, self.cell,
                                           self.relief)
        if not triangles:
            viewport.flash_status(tr("The terrain needs some width and depth."))
            return
        from core.history import InsertGroupCommand
        viewport.history.execute(InsertGroupCommand(
            terrain_group(vertices, triangles)))
        self.start_point = None
        viewport.update()

    def status_clause(self) -> str:
        if self.relief > 0.0:
            return tr("Cell {size}, relief {relief}", size=_fmt(self.cell),
                      relief=_fmt(self.relief))
        return tr("Cell {size}", size=_fmt(self.cell))

    def value_label(self):
        if self.start_point is None or self.hover_point is None:
            return None
        far = self._level(self.hover_point)
        w = abs(far.x() - self.start_point.x())
        h = abs(far.y() - self.start_point.y())
        nx, ny = grid_cells(w, h, self.cell)
        return (f"{_fmt(w)} × {_fmt(h)}  ({nx} × {ny})", self.hover_point)

    def rubber_band_lines(self):
        if self.start_point is None or self.hover_point is None:
            return []
        a, b = self.start_point, self._level(self.hover_point)
        x0, x1 = sorted((a.x(), b.x()))
        y0, y1 = sorted((a.y(), b.y()))
        z = a.z()
        if x1 - x0 < MIN_SIZE and y1 - y0 < MIN_SIZE:
            return []
        nx, ny = grid_cells(x1 - x0, y1 - y0, self.cell)
        lines = []
        # The rim, then the inner grid lines (thinned on a dense grid so
        # the preview stays light; the grid itself keeps every cell).
        step_x = max(1, math.ceil(nx / _PREVIEW_LINES))
        step_y = max(1, math.ceil(ny / _PREVIEW_LINES))
        for i in list(range(0, nx, step_x)) + [nx]:
            x = x0 + (x1 - x0) * i / nx
            lines.append((QVector3D(x, y0, z), QVector3D(x, y1, z)))
        for j in list(range(0, ny, step_y)) + [ny]:
            y = y0 + (y1 - y0) * j / ny
            lines.append((QVector3D(x0, y, z), QVector3D(x1, y, z)))
        return lines


class TerrainDeformTool(Tool):
    """Draw ▸ Terrain ▸ Deform Terrain."""

    name = "Deform Terrain"
    description = ("Push the ground up or down at a point, smoothly out to "
                   "a radius. Type the radius first.")
    vcb_label = "Radius"
    allow_inferences = False

    #: The radius of the next push (model units); kept between uses.
    radius = 3.0

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None
        self.hover_point: QVector3D | None = None
        self._viewport = None
        #: ``(mesh, xform)`` of the geometry clicked.
        self._target = None

    def vcb_caption(self) -> str:
        return "Height" if self.start_point is not None else "Radius"

    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def _reset(self) -> None:
        self.start_point = None
        self._target = None

    def drag_plane(self, viewport):
        if self.start_point is None:
            return None
        return _vertical_plane(viewport, self.start_point)

    def height(self) -> float:
        """The push the cursor asks for now (up is positive)."""
        if self.start_point is None or self.hover_point is None:
            return 0.0
        return self.hover_point.z() - self.start_point.z()

    def on_hover(self, ctx: ToolContext) -> None:
        self._viewport = ctx.viewport
        self.hover_point = ctx.world
        ctx.viewport.update()

    @staticmethod
    def pick_target(viewport, screen):
        """``(mesh, xform)`` of the geometry under the cursor, or ``None``:
        the loose geometry (the open group's, inside one) or the group the
        face belongs to — its own mesh and the matrix that places it."""
        picker = getattr(viewport, "pick_face_placement", None)
        if not callable(picker):
            return None
        face, place = picker(screen.x(), screen.y())
        if face is None:
            return None
        if place is None:
            return viewport.scene.mesh, None
        return place.mesh, getattr(place, "xform", None)

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if self.start_point is None:
            target = self.pick_target(vp, ctx.screen)
            if target is None:
                vp.flash_status(tr("Click the ground you want to deform."))
                return
            self._target = target
            self.start_point = QVector3D(ctx.world)
            self.hover_point = QVector3D(ctx.world)
            return
        self.hover_point = ctx.world
        self._commit(vp, self.height())

    def on_value(self, viewport, value) -> bool:
        if isinstance(value, tuple):
            return False
        if self.start_point is None:
            if value < MIN_SIZE:
                return False
            self.radius = float(value)
            viewport.flash_status(tr("Radius: {size}", size=_fmt(value)))
            self.refresh_hint(viewport)
            viewport.update()
            return True
        self._commit(viewport, float(value))
        return True

    def _commit(self, viewport, height: float) -> None:
        if abs(height) < 1e-6 or self._target is None:
            self._reset()
            viewport.update()
            return
        mesh, xform = self._target
        cmd = DeformTerrainCommand(mesh, self.start_point, self.radius,
                                   height, xform)
        viewport.history.execute(cmd)
        if cmd.moved == 0 and viewport.history.last_error is None:
            viewport.flash_status(tr("No ground within the radius to move."))
        self._reset()
        viewport.update()

    def status_clause(self) -> str:
        return tr("Radius {size}", size=_fmt(self.radius))

    def value_label(self):
        if self.start_point is None or self.hover_point is None:
            return None
        h = self.height()
        sign = "+" if h >= 0 else "−"
        return (sign + _fmt(abs(h)), self.hover_point)

    def _ring(self, centre: QVector3D):
        r = self.radius
        pts = [QVector3D(centre.x() + r * math.cos(2 * math.pi * k / _RING_SEGMENTS),
                         centre.y() + r * math.sin(2 * math.pi * k / _RING_SEGMENTS),
                         centre.z())
               for k in range(_RING_SEGMENTS)]
        return [(pts[k], pts[(k + 1) % len(pts)]) for k in range(len(pts))]

    def rubber_band_lines(self):
        if self.start_point is None:
            if self.hover_point is None:
                return []
            return self._ring(self.hover_point)
        h = self.height()
        lines = self._ring(self.start_point)
        top = self.start_point + QVector3D(0.0, 0.0, h)
        lines.append((QVector3D(self.start_point), top))
        if self._target is not None and abs(h) > 1e-6:
            mesh, xform = self._target
            lines += deform_preview(mesh, self.start_point, self.radius, h,
                                    xform)
        return lines


def _face_outline(viewport, screen):
    """``(points, mesh, face)`` of the face under the cursor, its outline
    in the world; ``None`` over nothing."""
    picker = getattr(viewport, "pick_face_placement", None)
    if not callable(picker):
        return None
    face, place = picker(screen.x(), screen.y())
    if face is None:
        return None
    xform = getattr(place, "xform", None) if place is not None else None
    mesh = place.mesh if place is not None else viewport.scene.mesh
    pts = [xform.map(v.position) if xform is not None else QVector3D(v.position)
           for v in face.loop]
    return pts, mesh, face


class TerrainStampTool(Tool):
    """Draw ▸ Terrain ▸ Stamp Platform."""

    name = "Stamp Platform"
    description = ("Cut a level platform the shape of a face into the "
                   "ground, with a slope round it. Type the slope width "
                   "first.")
    vcb_label = "Slope"
    allow_inferences = False

    #: The plan width of the slope round the next platform; kept.
    slope = 1.0

    def __init__(self) -> None:
        #: The platform's outline (world points) and the mesh it is in.
        self.footprint: list | None = None
        self._footprint_mesh = None
        #: The ground clicked: where, and ``(mesh, xform)``.
        self.start_point: QVector3D | None = None
        self.hover_point: QVector3D | None = None
        self._target = None

    def vcb_caption(self) -> str:
        return "Height" if self.start_point is not None else "Slope"

    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def _reset(self) -> None:
        self.footprint = None
        self._footprint_mesh = None
        self.start_point = None
        self._target = None

    def drag_plane(self, viewport):
        if self.start_point is None:
            return None
        return _vertical_plane(viewport, self.start_point)

    def level(self) -> float:
        """The height of the shape: where the platform goes with no rise."""
        if not self.footprint:
            return 0.0
        return sum(p.z() for p in self.footprint) / len(self.footprint)

    def platform_height(self) -> float:
        """Where the platform would go now: the shape's level plus how far
        the cursor has risen since the ground was clicked."""
        h = self.level()
        if self.start_point is not None and self.hover_point is not None:
            h += self.hover_point.z() - self.start_point.z()
        return h

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        if self.footprint is None:
            got = _face_outline(vp, ctx.screen)
            if got is None or len(got[0]) < 3:
                vp.flash_status(tr("Click the face with the platform's shape."))
                return
            self.footprint, self._footprint_mesh, _face = got
            return
        if self.start_point is None:
            target = TerrainDeformTool.pick_target(vp, ctx.screen)
            if target is None:
                vp.flash_status(tr("Click the ground to stamp the platform into."))
                return
            if target[0] is self._footprint_mesh:
                vp.flash_status(tr(
                    "The shape and the ground are the same geometry: group "
                    "one of them first."))
                return
            self._target = target
            self.start_point = QVector3D(ctx.world)
            self.hover_point = QVector3D(ctx.world)
            return
        self.hover_point = ctx.world
        self._commit(vp, self.platform_height())

    def on_value(self, viewport, value) -> bool:
        if isinstance(value, tuple):
            return False
        if self.start_point is None:
            if value < 0.0:
                return False
            self.slope = float(value)
            viewport.flash_status(tr("Slope: {size}", size=_fmt(value)))
            self.refresh_hint(viewport)
            return True
        self._commit(viewport, self.level() + float(value))
        return True

    def _commit(self, viewport, height: float) -> None:
        mesh, xform = self._target
        from core.terrain_mesh import StampCommand
        cmd = StampCommand(mesh, self.footprint, height, self.slope, xform)
        viewport.history.execute(cmd)
        if cmd.result == 0 and viewport.history.last_error is None:
            viewport.flash_status(tr("The shape is not over this ground."))
        self._reset()
        viewport.update()

    def status_clause(self) -> str:
        return tr("Slope {size}", size=_fmt(self.slope))

    def value_label(self):
        if self.start_point is None or self.hover_point is None:
            return None
        rise = self.platform_height() - self.level()
        sign = "+" if rise >= 0 else "−"
        return (sign + _fmt(abs(rise)), self.hover_point)

    def rubber_band_lines(self):
        if not self.footprint:
            return []
        h = self.platform_height()
        top = [QVector3D(p.x(), p.y(), h) for p in self.footprint]
        lines = [(top[k], top[(k + 1) % len(top)]) for k in range(len(top))]
        if self.start_point is not None and abs(h - self.level()) > 1e-6:
            lines += [(QVector3D(p), q) for p, q in zip(self.footprint, top)]
        return lines


class TerrainDrapeTool(Tool):
    """Draw ▸ Terrain ▸ Drape."""

    name = "Drape"
    description = ("Cut the selected edges into the ground below them, as "
                   "lines on the terrain.")
    allow_inferences = False

    def on_activate(self, viewport) -> None:
        pass

    def on_deactivate(self, viewport) -> None:
        pass

    @staticmethod
    def selected_segments(scene, target_mesh) -> list:
        """World ``[(a, b), ...]`` of the selected edges — loose ones, and
        the shown edges of selected groups — leaving out the ground's own."""
        from core.group import Group, world_mesh
        from core.mesh import Edge
        own = {id(e) for e in getattr(target_mesh, "edges", ())}
        out = []
        for item in scene.selection:
            if isinstance(item, Edge):
                if id(item) not in own:
                    out.append((QVector3D(item.a), QVector3D(item.b)))
            elif isinstance(item, Group) and item.mesh is not target_mesh:
                for e in world_mesh(item).edges:
                    if not e.soft and not e.hidden:
                        out.append((QVector3D(e.a), QVector3D(e.b)))
        return out

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        target = TerrainDeformTool.pick_target(vp, ctx.screen)
        if target is None:
            vp.flash_status(tr("Click the ground to drape the edges onto."))
            return
        mesh, xform = target
        segments = self.selected_segments(vp.scene, mesh)
        if not segments:
            vp.flash_status(tr(
                "Select the edges to drape first, then click the ground."))
            return
        from core.terrain_mesh import DrapeCommand
        cmd = DrapeCommand(mesh, segments, xform)
        vp.history.execute(cmd)
        if cmd.result == 0 and vp.history.last_error is None:
            vp.flash_status(tr("The selected edges are not over this ground."))
        vp.update()


# ---- Flip edge / Add detail --------------------------------------------------

#: The status-bar word for each reason an edge does not flip.
_FLIP_WHY = {
    "rim": "That edge is on the terrain's rim: there is nothing to flip it "
           "toward.",
    "polygon": "Only an edge between two triangles can be flipped.",
    "hard": "That edge is a line on the ground: soften it first to flip it.",
    "concave": "Seen from above, the two triangles make no convex shape: "
               "flipping would fold them.",
}


def _nearest_side(face, xform, world: QVector3D):
    """The corners ``(u, w)`` of the side of ``face`` nearest the world
    point ``world`` (where the cursor meets the face)."""
    loop = face.loop
    best, best_d = None, math.inf
    for k in range(len(loop)):
        u, w = loop[k], loop[(k + 1) % len(loop)]
        a = xform.map(u.position) if xform is not None else u.position
        b = xform.map(w.position) if xform is not None else w.position
        ab = b - a
        l2 = QVector3D.dotProduct(ab, ab)
        t = 0.0 if l2 < 1e-24 else max(0.0, min(1.0, QVector3D.dotProduct(
            world - a, ab) / l2))
        d = (world - (a + ab * t)).length()
        if d < best_d:
            best, best_d = (u, w), d
    return best


class TerrainFlipTool(Tool):
    """Draw ▸ Terrain ▸ Flip Edge: the edge two triangles share turned to
    the other diagonal of their quad — a ridge or a valley the
    triangulation got wrong, put right."""

    name = "Flip Edge"
    description = ("Click an edge between two triangles of the ground to "
                   "turn it to the other diagonal.")
    allow_inferences = False
    uses_snap = False

    def __init__(self) -> None:
        #: ``(mesh, xform, edge)`` under the cursor.
        self._target = None

    def on_activate(self, viewport) -> None:
        self._target = None

    def on_deactivate(self, viewport) -> None:
        self._target = None

    @staticmethod
    def pick(viewport, screen, world):
        """``(mesh, xform, edge)``: the side of the ground face under the
        cursor nearest to it — the inner edges of a terrain are soft and
        not drawn, so the face, not the edge, is what the cursor finds."""
        picker = getattr(viewport, "pick_face_placement", None)
        if not callable(picker) or world is None:
            return None
        face, place = picker(screen.x(), screen.y())
        if face is None:
            return None
        mesh = place.mesh if place is not None else viewport.scene.mesh
        xform = getattr(place, "xform", None) if place is not None else None
        side = _nearest_side(face, xform, world)
        if side is None:
            return None
        edge = mesh.find_edge(*side)
        return None if edge is None else (mesh, xform, edge)

    def on_hover(self, ctx: ToolContext) -> None:
        self._target = self.pick(ctx.viewport, ctx.screen, ctx.world)
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        from core.terrain_mesh import FlipEdgeCommand, flip_problem
        vp = ctx.viewport
        target = self.pick(vp, ctx.screen, ctx.world)
        if target is None:
            vp.flash_status(tr("Click an edge of the ground."))
            return
        mesh, xform, edge = target
        why = flip_problem(mesh, edge, xform)
        if why is not None:
            vp.flash_status(tr(_FLIP_WHY[why]))
            return
        vp.history.execute(FlipEdgeCommand(mesh, edge.v0.position,
                                           edge.v1.position, xform))
        self._target = self.pick(vp, ctx.screen, ctx.world)
        vp.update()

    def rubber_band_lines(self):
        from core.terrain_mesh import flip_preview, flip_problem
        if self._target is None:
            return []
        mesh, xform, edge = self._target
        if edge not in edge.v0.edges or flip_problem(mesh, edge, xform):
            return []
        return flip_preview(edge, xform)


class TerrainDetailTool(Tool):
    """Draw ▸ Terrain ▸ Add Detail: the ground triangles round the click
    split in four, the ground keeping its shape — more corners where Deform
    or Stamp need them. Typed first, a radius (0: the triangle clicked)."""

    name = "Add Detail"
    description = ("Split the ground triangles round the click in four, for "
                   "finer deforming. Type the radius first (0: one triangle).")
    vcb_label = "Radius"
    allow_inferences = False
    uses_snap = False

    #: The reach of the next split (model units); kept between uses.
    radius = 1.0

    def __init__(self) -> None:
        self.hover_point: QVector3D | None = None
        #: ``(mesh, xform)`` of the ground under the cursor.
        self._target = None

    def on_activate(self, viewport) -> None:
        self._target = None

    def on_deactivate(self, viewport) -> None:
        self._target = None
        self.hover_point = None

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = ctx.world
        self._target = TerrainDeformTool.pick_target(ctx.viewport, ctx.screen)
        ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        from core.terrain_mesh import AddDetailCommand, detail_preview
        vp = ctx.viewport
        target = TerrainDeformTool.pick_target(vp, ctx.screen)
        if target is None or ctx.world is None:
            vp.flash_status(tr("Click the ground to add detail to."))
            return
        mesh, xform = target
        if not detail_preview(mesh, ctx.world, self.radius, xform):
            vp.flash_status(tr("No ground triangles within the radius."))
            return
        vp.history.execute(AddDetailCommand(mesh, ctx.world, self.radius,
                                            xform))
        vp.update()

    def on_value(self, viewport, value) -> bool:
        if isinstance(value, tuple) or value < 0.0:
            return False
        self.radius = float(value)
        viewport.flash_status(tr("Radius: {size}", size=_fmt(value)))
        self.refresh_hint(viewport)
        viewport.update()
        return True

    def status_clause(self) -> str:
        if self.radius <= 0.0:
            return tr("Only the clicked triangle")
        return tr("Radius {size}", size=_fmt(self.radius))

    def rubber_band_lines(self):
        from core.terrain_mesh import detail_preview
        if self.hover_point is None:
            return []
        lines = []
        if self.radius > 0.0:
            lines += TerrainDeformTool._ring(self, self.hover_point)
        if self._target is not None:
            mesh, xform = self._target
            lines += detail_preview(mesh, self.hover_point, self.radius,
                                    xform)
        return lines


# ---- From survey data --------------------------------------------------------

def selected_points(scene) -> list:
    """World survey points in the selection: guide points, the ends of
    selected edges and the vertices of selected groups. With none of them
    selected, every guide point the model shows (a survey imported from a
    drawing arrives as guide points)."""
    from core.group import Group, world_mesh
    from core.mesh import Edge
    out = []
    for item in scene.selection:
        if isinstance(item, Edge):
            out += [QVector3D(item.a), QVector3D(item.b)]
        elif isinstance(item, Group):
            out += [QVector3D(v.position) for v in world_mesh(item).vertices]
        elif _is_guide_point(item):
            out.append(QVector3D(item.point))
    if out:
        return out
    shown = getattr(scene, "entity_selectable", None)
    return [QVector3D(g.point) for g in getattr(scene, "guides", ())
            if _is_guide_point(g) and (shown is None or shown(g))]


def _is_guide_point(item) -> bool:
    from core.guide import Guide
    return isinstance(item, Guide) and item.direction is None


class _BuildTool(Tool):
    """A terrain built from the selection the moment the tool is picked
    up; a number typed afterwards sets its parameter and, while the new
    terrain is the last thing done, builds it again with it."""

    allow_inferences = False
    #: The parameter (model units), kept between uses; ``None`` = automatic.
    value: float | None = None

    def __init__(self) -> None:
        self._source = None
        self._last = None                   # the InsertGroupCommand

    def source(self, scene):  # pragma: no cover - overridden
        raise NotImplementedError

    def make(self, source):  # pragma: no cover - overridden
        raise NotImplementedError

    def empty_hint(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def on_activate(self, viewport) -> None:
        self._last = None
        source = self.source(viewport.scene)
        if not source:
            viewport.flash_status(tr(self.empty_hint()))
            return
        self._source = source
        self._build(viewport)

    def on_deactivate(self, viewport) -> None:
        self._last = None

    def on_click(self, ctx: ToolContext) -> None:
        source = self.source(ctx.viewport.scene)
        if source:
            self._source = source
            self._last = None
            self._build(ctx.viewport)
        else:
            ctx.viewport.flash_status(tr(self.empty_hint()))

    def _build(self, viewport) -> bool:
        from core.history import InsertGroupCommand
        from core.terrain_build import TerrainBuildError
        try:
            vertices, triangles = self.make(self._source)
        except TerrainBuildError as exc:
            viewport.flash_status(tr(str(exc)))
            return False
        cmd = InsertGroupCommand(terrain_group(vertices, triangles))
        viewport.history.execute(cmd)
        self._last = cmd
        viewport.update()
        return True

    def on_value(self, viewport, value) -> bool:
        if isinstance(value, tuple) or value < 0.0:
            return False
        self.value = float(value) if value > 0.0 else None
        self.refresh_hint(viewport)
        stack = getattr(viewport.history, "undo_stack", None)
        if self._last is not None and stack and stack[-1] is self._last:
            viewport.history.undo()
            self._build(viewport)
        viewport.update()
        return True


class TerrainFromContoursTool(_BuildTool):
    """Draw ▸ Terrain ▸ From Contours."""

    name = "Terrain from Contours"
    description = ("Build a terrain through the selected contour lines, "
                   "each at its height. Type the cell size to change it.")
    vcb_label = "Cell size"

    def empty_hint(self) -> str:
        return "Select the contour lines first, at their heights."

    def source(self, scene):
        return TerrainDrapeTool.selected_segments(scene, None)

    def cell(self, segments) -> float:
        """The typed cell, or one fitting the contours: a hundredth of
        their longest side, never under 10 cm."""
        if self.value:
            return self.value
        xs = [p.x() for s in segments for p in s]
        ys = [p.y() for s in segments for p in s]
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        return max(span / 100.0, 0.1)

    def make(self, source):
        from core.terrain_build import contour_terrain
        return contour_terrain(source, self.cell(source))

    def status_clause(self) -> str:
        if self.value:
            return tr("Cell {size}", size=_fmt(self.value))
        return tr("Cell size: automatic")


class TerrainFromPointsTool(_BuildTool):
    """Draw ▸ Terrain ▸ From Points."""

    name = "Terrain from Points"
    description = ("Join the selected points — or every guide point — into "
                   "a terrain of triangles through each one. Type a longest "
                   "side to trim the rim.")
    vcb_label = "Longest side"

    def empty_hint(self) -> str:
        return "Select the points first, or add guide points."

    def source(self, scene):
        return selected_points(scene)

    def make(self, source):
        from core.terrain_build import points_terrain
        return points_terrain(source, self.value or 0.0)

    def status_clause(self) -> str:
        if self.value:
            return tr("Longest side {size}", size=_fmt(self.value))
        return tr("Longest side: no limit")


# ---- Set height --------------------------------------------------------------

def line_chain(mesh, edge) -> list:
    """The vertices of the line ``edge`` belongs to: every edge without a
    face reached from it through shared corners (a contour drawn or
    imported as a polyline)."""
    seen_e = {id(edge)}
    todo = [edge]
    verts = {}
    while todo:
        e = todo.pop()
        for v in (e.v0, e.v1):
            if id(v) in verts:
                continue
            verts[id(v)] = v
            for nxt in v.edges:
                if id(nxt) not in seen_e and not nxt.faces:
                    seen_e.add(id(nxt))
                    todo.append(nxt)
    return list(verts.values())


class TerrainHeightTool(Tool):
    """Draw ▸ Terrain ▸ Set Height: lift a flat contour, or a guide point,
    to its height — what a 2D drawing only wrote in a label."""

    name = "Set Height"
    description = ("Click a contour line or a guide point and type its "
                   "height: the whole line goes to it.")
    vcb_label = "Height"
    uses_snap = False

    #: The height set last (model units), shown as a reminder.
    last: float | None = None

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None
        #: ``("line", mesh, vertices, xform)`` or ``("guide", guide)``.
        self._target = None

    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def _reset(self) -> None:
        self.start_point = None
        self._target = None

    def pick(self, viewport, screen):
        """What the cursor is on: a guide point, a loose line (or the open
        group's), or a line of the group under the cursor."""
        x, y = screen.x(), screen.y()
        guide = getattr(viewport, "pick_guide", lambda *_a: None)(x, y)
        if _is_guide_point(guide):
            return ("guide", guide)
        edge = getattr(viewport, "pick_edge", lambda *_a: None)(x, y)
        if edge is not None and not edge.faces:
            return ("line", viewport.scene.mesh,
                    line_chain(viewport.scene.mesh, edge), None)
        group = getattr(viewport, "pick_group", lambda *_a: None)(x, y)
        if group is not None:
            got = self._group_line(viewport, group, x, y)
            if got is not None:
                return got
        return None

    @staticmethod
    def _group_line(viewport, group, x, y):
        """The line of ``group`` nearest the pixel, within the pick
        distance: read from outside, as the imported layer groups are."""
        to_px = getattr(viewport, "_world_to_pixel", None)
        if to_px is None:
            return None
        xform = getattr(group, "xform", None)
        best, best_d = None, getattr(viewport, "pick_threshold_px", 8.0)
        for e in group.mesh.edges:
            if e.faces:
                continue
            a, b = e.v0.position, e.v1.position
            if xform is not None:
                a, b = xform.map(a), xform.map(b)
            pa, pb = to_px(a), to_px(b)
            if pa is None or pb is None:
                continue
            dx, dy = pb[0] - pa[0], pb[1] - pa[1]
            l2 = dx * dx + dy * dy
            t = 0.0 if l2 < 1e-12 else max(0.0, min(1.0, (
                (x - pa[0]) * dx + (y - pa[1]) * dy) / l2))
            d = math.hypot(x - (pa[0] + dx * t), y - (pa[1] + dy * t))
            if d < best_d:
                best, best_d = e, d
        if best is None:
            return None
        return ("line", group.mesh, line_chain(group.mesh, best), xform)

    def on_click(self, ctx: ToolContext) -> None:
        target = self.pick(ctx.viewport, ctx.screen)
        if target is None:
            ctx.viewport.flash_status(tr(
                "Click a contour line or a guide point."))
            return
        self._target = target
        self.start_point = QVector3D(ctx.world)
        ctx.viewport.update()

    def current_height(self) -> float | None:
        t = self._target
        if t is None:
            return None
        if t[0] == "guide":
            return t[1].point.z()
        _k, _mesh, verts, xform = t
        if not verts:
            return None
        p = verts[0].position
        return (xform.map(p) if xform is not None else p).z()

    def on_value(self, viewport, value) -> bool:
        if isinstance(value, tuple):
            return False
        if self._target is None:
            viewport.flash_status(tr("Click a contour line or a guide point."))
            return True
        from core.terrain_mesh import SetGuideHeightCommand, SetHeightCommand
        t = self._target
        if t[0] == "guide":
            cmd = SetGuideHeightCommand(t[1], float(value))
        else:
            _k, mesh, verts, xform = t
            cmd = SetHeightCommand(mesh, verts, float(value), xform)
        viewport.history.execute(cmd)
        TerrainHeightTool.last = float(value)
        self.refresh_hint(viewport)
        self._reset()
        viewport.update()
        return True

    def status_clause(self) -> str:
        if self.last is None:
            return ""
        return tr("Last {size}", size=_fmt(self.last))

    def value_label(self):
        h = self.current_height()
        if h is None or self.start_point is None:
            return None
        return (_fmt(h), self.start_point)

    def rubber_band_lines(self):
        t = self._target
        if t is None or t[0] != "line":
            return []
        _k, _mesh, verts, xform = t
        ids = {id(v) for v in verts}
        lines = []
        seen = set()
        for v in verts:
            for e in v.edges:
                if e.faces or id(e) in seen or id(e.other(v)) not in ids:
                    continue
                seen.add(id(e))
                a, b = e.v0.position, e.v1.position
                if xform is not None:
                    a, b = xform.map(a), xform.map(b)
                lines.append((QVector3D(a), QVector3D(b)))
        return lines
