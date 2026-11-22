# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Draw ▸ Terrain: a flat grid of triangles built from scratch, and pushing
any triangulated ground up or down at a point — smoothly out to a radius,
one undo step, on the loose geometry or a group's mesh from outside."""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group
from core.history import History
from core.mesh import Mesh
from core.scene import Scene
from core.terrain_mesh import (MAX_CELLS_PER_SIDE, DeformTerrainCommand,
                               StampCommand, deform_mesh, deform_offsets,
                               deform_preview, falloff, grid_cells,
                               grid_terrain, imprint_segments,
                               platform_heights, relief_heights,
                               stamp_platform, terrain_group, terrain_mesh)
from tools.base import ToolContext
from tools.terrain import (TerrainDeformTool, TerrainDrapeTool,
                           TerrainGridTool, TerrainStampTool)


def _z_at(mesh, x, y):
    for v in mesh.vertices:
        p = v.position
        if abs(p.x() - x) < 1e-4 and abs(p.y() - y) < 1e-4:
            return p.z()
    raise AssertionError(f"no vertex at ({x}, {y})")


def _grid(w=10.0, d=10.0, cell=1.0, z=0.0):
    return terrain_mesh(*grid_terrain(QVector3D(0, 0, z),
                                      QVector3D(w, d, z), cell))


# ---- Grid --------------------------------------------------------------------

def test_grid_cells_fill_the_rectangle_and_stay_bounded():
    assert grid_cells(10.0, 4.0, 1.0) == (10, 4)
    assert grid_cells(10.0, 4.0, 3.0) == (3, 1)        # nearest whole count
    assert grid_cells(0.2, 0.2, 5.0) == (1, 1)         # never zero cells
    # A slip of the keyboard cannot ask for millions of triangles.
    assert grid_cells(1000.0, 1000.0, 0.001) == (MAX_CELLS_PER_SIDE,
                                                 MAX_CELLS_PER_SIDE)


def test_grid_is_two_triangles_per_cell_facing_up():
    verts, tris = grid_terrain(QVector3D(2, 3, 1.5), QVector3D(-2, -1, 9), 1.0)
    assert len(verts) == 5 * 5
    assert len(tris) == 2 * 4 * 4
    assert {round(v.z(), 6) for v in verts} == {1.5}   # level at the 1st click
    xs = sorted({round(v.x(), 6) for v in verts})
    assert xs[0] == -2.0 and xs[-1] == 2.0
    for a, b, c in tris:
        n = QVector3D.crossProduct(verts[b] - verts[a], verts[c] - verts[a])
        assert n.z() > 0                               # counter-clockwise


def test_a_rectangle_with_no_area_gives_no_grid():
    assert grid_terrain(QVector3D(0, 0, 0), QVector3D(5, 0, 0), 1.0) == ([], [])


def test_terrain_mesh_softens_the_inside_and_keeps_the_rim():
    mesh = _grid(4.0, 3.0, 1.0)
    assert len(mesh.faces) == 2 * 4 * 3
    assert all(len(f.loop) == 3 for f in mesh.faces)
    rim = [e for e in mesh.edges if len(e.faces) == 1]
    inner = [e for e in mesh.edges if len(e.faces) == 2]
    assert len(rim) == 2 * (4 + 3)
    assert inner and all(e.soft for e in inner)
    assert not any(e.soft for e in rim)
    # Soft edges join the triangles into one surface for selection.
    assert len(mesh.surface_of(mesh.faces[0])) == len(mesh.faces)


def test_terrain_group_is_named_terrain():
    g = terrain_group(*grid_terrain(QVector3D(0, 0, 0), QVector3D(2, 2, 0), 1))
    assert isinstance(g, Group)
    assert g.name == "Terrain"
    assert len(g.mesh.faces) == 8


def test_relief_swells_and_sinks_up_to_its_height_around_the_level():
    import numpy as np
    xs, ys = np.meshgrid(np.linspace(0, 40, 81), np.linspace(0, 30, 61))
    h = relief_heights(xs.ravel(), ys.ravel(), 0.8, seed=7)
    assert np.abs(h).max() == pytest.approx(0.8)
    assert h.mean() == pytest.approx(0.0, abs=1e-9)   # keeps the level
    assert h.max() > 0.2 and h.min() < -0.2           # swells AND hollows
    # Gentle: between points 0.5 m apart it never jumps like a spike.
    grid = h.reshape(xs.shape)
    assert np.abs(np.diff(grid, axis=1)).max() < 0.25
    assert np.abs(np.diff(grid, axis=0)).max() < 0.25


def test_relief_repeats_with_a_seed_and_is_flat_at_zero():
    import numpy as np
    xs, ys = [0.0, 3.0, 7.5, 12.0], [0.0, 4.0, 1.0, 9.0]
    a = relief_heights(xs, ys, 1.0, seed=3)
    assert np.array_equal(a, relief_heights(xs, ys, 1.0, seed=3))
    assert not np.array_equal(a, relief_heights(xs, ys, 1.0, seed=4))
    assert not relief_heights(xs, ys, 0.0).any()


def test_grid_with_relief_is_irregular_but_keeps_its_plan():
    flat, tris = grid_terrain(QVector3D(0, 0, 2), QVector3D(20, 10, 2), 1.0)
    rough, tris2 = grid_terrain(QVector3D(0, 0, 2), QVector3D(20, 10, 2), 1.0,
                                relief=0.6, seed=1)
    assert tris2 == tris
    assert [(v.x(), v.y()) for v in rough] == [(v.x(), v.y()) for v in flat]
    zs = [v.z() for v in rough]
    assert max(zs) - min(zs) > 0.5
    assert max(abs(z - 2.0) for z in zs) == pytest.approx(0.6, abs=1e-5)
    # Still a ground seen from above: every triangle faces up.
    for a, b, c in tris2:
        n = QVector3D.crossProduct(rough[b] - rough[a], rough[c] - rough[a])
        assert n.z() > 0


# ---- Deform ------------------------------------------------------------------

def test_falloff_is_full_at_the_centre_and_level_at_the_rim():
    assert falloff(0.0, 3.0) == pytest.approx(1.0)
    assert falloff(1.5, 3.0) == pytest.approx(0.5)
    assert falloff(3.0, 3.0) == 0.0
    assert falloff(7.0, 3.0) == 0.0
    # Level at both ends: no peak at the centre, no step at the rim.
    eps = 1e-3
    assert falloff(eps, 3.0) == pytest.approx(1.0, abs=1e-5)
    assert falloff(3.0 - eps, 3.0) == pytest.approx(0.0, abs=1e-5)


def test_deform_raises_the_centre_by_the_height_and_less_outwards():
    mesh = _grid()
    moved = deform_mesh(mesh, QVector3D(5, 5, 0), 3.0, 2.0)
    assert moved > 0
    assert _z_at(mesh, 5, 5) == pytest.approx(2.0)
    assert 0.0 < _z_at(mesh, 6, 5) < 2.0
    assert _z_at(mesh, 6, 5) > _z_at(mesh, 7, 5)
    assert _z_at(mesh, 8, 5) == pytest.approx(0.0)     # at the radius
    assert _z_at(mesh, 0, 0) == pytest.approx(0.0)     # far away
    # Only up: no vertex slides sideways.
    xy = sorted((round(v.position.x(), 6), round(v.position.y(), 6))
                for v in mesh.vertices)
    assert xy == sorted((float(i), float(j))
                        for i in range(11) for j in range(11))


def test_a_negative_height_digs_a_hollow():
    mesh = _grid()
    deform_mesh(mesh, QVector3D(5, 5, 0), 3.0, -1.5)
    assert _z_at(mesh, 5, 5) == pytest.approx(-1.5)
    assert all(v.position.z() <= 1e-9 for v in mesh.vertices)


def test_the_radius_is_measured_in_plan_on_a_slope():
    """A tilted ground rises evenly round the point: the distance that
    counts is the one seen from above, not along the slope."""
    mesh = _grid()
    for v in list(mesh.vertices):            # tilt it: z = x
        mesh.place_vertex(v, QVector3D(v.position.x(), v.position.y(),
                                       v.position.x()))
    before = {(round(v.position.x()), round(v.position.y())): v.position.z()
              for v in mesh.vertices}
    deform_mesh(mesh, QVector3D(5, 5, 5), 3.0, 1.0)
    rise = {(round(v.position.x()), round(v.position.y())):
            v.position.z() - before[(round(v.position.x()),
                                     round(v.position.y()))]
            for v in mesh.vertices}
    assert rise[(4, 5)] == pytest.approx(rise[(6, 5)])
    assert rise[(5, 4)] == pytest.approx(rise[(6, 5)])


def test_deform_through_a_matrix_moves_straight_up_in_the_world():
    """A group placed by a matrix (a copied group, a component) is pushed
    in the world: the centre and the radius are the world's, and the
    vertices go up in the world, whatever the matrix turns."""
    mesh = _grid()
    xf = QMatrix4x4()
    xf.translate(100.0, 0.0, 0.0)
    xf.rotate(90.0, 0.0, 0.0, 1.0)
    offsets = deform_offsets(mesh, QVector3D(95, 5, 0), 3.0, 2.0, xf)
    assert offsets
    for v, off in offsets.items():
        w0 = xf.map(v.position)
        w1 = xf.map(v.position + off)
        assert w1.x() == pytest.approx(w0.x(), abs=1e-5)
        assert w1.y() == pytest.approx(w0.y(), abs=1e-5)
        assert w1.z() > w0.z()
    top = max(offsets, key=lambda v: xf.map(v.position + offsets[v]).z())
    peak = xf.map(top.position)
    assert (peak.x(), peak.y()) == (pytest.approx(95), pytest.approx(5))


def test_deform_folds_a_bent_quad_into_planar_pieces():
    """Ground that is not triangles yet — a plain rectangle face — bends
    into planar triangles instead of a warped face."""
    mesh = Mesh()
    mesh.add_face([QVector3D(0, 0, 0), QVector3D(10, 0, 0),
                   QVector3D(10, 10, 0), QVector3D(0, 10, 0)])
    deform_mesh(mesh, QVector3D(10, 10, 0), 5.0, 2.0)
    assert len(mesh.faces) >= 2
    for f in mesh.faces:
        n = f.normal()
        d = QVector3D.dotProduct(n, f.loop[0].position)
        for v in f.loop:
            assert QVector3D.dotProduct(n, v.position) == pytest.approx(
                d, abs=1e-4)


def test_preview_moves_the_edges_without_touching_the_mesh():
    mesh = _grid()
    lines = deform_preview(mesh, QVector3D(5, 5, 0), 2.0, 1.0)
    assert lines
    assert max(max(a.z(), b.z()) for a, b in lines) == pytest.approx(1.0)
    assert all(v.position.z() == 0.0 for v in mesh.vertices)


def test_command_is_one_undo_step_on_a_group_from_outside():
    scene = Scene()
    history = History(scene)
    g = terrain_group(*grid_terrain(QVector3D(0, 0, 0),
                                    QVector3D(10, 10, 0), 1.0))
    scene.groups.append(g)
    cmd = DeformTerrainCommand(g.mesh, QVector3D(5, 5, 0), 3.0, 2.0)
    history.execute(cmd)
    assert history.last_error is None
    assert _z_at(g.mesh, 5, 5) == pytest.approx(2.0)
    assert len(scene.mesh.faces) == 0                 # the loose stays empty
    history.undo()
    assert _z_at(g.mesh, 5, 5) == pytest.approx(0.0)
    history.redo()
    assert _z_at(g.mesh, 5, 5) == pytest.approx(2.0)


# ---- Tools -------------------------------------------------------------------

class _Vp:
    def __init__(self, scene, pick=None):
        self.scene = scene
        self.history = History(scene)
        self.flashes = []
        self._pick = pick
        self.camera = None

    def update(self):
        pass

    def flash_status(self, text, *_a):
        self.flashes.append(text)

    def pick_face_placement(self, x, y):
        return self._pick(x, y) if self._pick else (None, None)


def _ctx(vp, x, y, z=0.0):
    return ToolContext(viewport=vp, world=QVector3D(x, y, z),
                       screen=QPointF(x, y), modifiers=Qt.NoModifier,
                       snap=SimpleNamespace(kind="none"))


def test_grid_tool_two_clicks_insert_one_selected_group():
    scene = Scene()
    vp = _Vp(scene)
    tool = TerrainGridTool()
    tool.on_activate(vp)
    assert tool.on_value(vp, 2.0)                       # the cell size
    tool.on_click(_ctx(vp, 0, 0, 1.0))
    tool.on_hover(_ctx(vp, 8, 6, 1.0))
    assert tool.rubber_band_lines()
    assert "4 × 3" in tool.value_label()[0]
    tool.on_click(_ctx(vp, 8, 6, 5.0))      # a snap off the level: ignored
    assert len(scene.groups) == 1
    g = scene.groups[0]
    assert len(g.mesh.faces) == 2 * 4 * 3
    assert {round(v.position.z(), 6) for v in g.mesh.vertices} == {1.0}
    assert g in scene.selection
    vp.history.undo()
    assert scene.groups == []


def test_grid_tool_takes_cell_and_relief_before_the_first_click():
    scene = Scene()
    vp = _Vp(scene)
    tool = TerrainGridTool()
    tool.on_activate(vp)
    assert tool.on_value(vp, (1.0, 0.8))               # «1;0.8»
    assert (tool.cell, tool.relief) == (1.0, 0.8)
    assert "0.8" in tool.status_clause() or "0,8" in tool.status_clause()
    assert tool.on_value(vp, 2.0)                      # the cell alone
    assert (tool.cell, tool.relief) == (2.0, 0.8)      # the relief stays
    assert not tool.on_value(vp, (1.0, -1.0))          # no negative relief
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_click(_ctx(vp, 20, 10))
    zs = [v.position.z() for v in scene.groups[0].mesh.vertices]
    assert max(zs) - min(zs) > 0.5
    assert tool.on_value(vp, (2.0, 0.0))               # «2;0»: flat again
    assert tool.relief == 0.0


def test_grid_tool_takes_typed_dimensions_toward_the_cursor():
    scene = Scene()
    vp = _Vp(scene)
    tool = TerrainGridTool()
    tool.on_activate(vp)
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_hover(_ctx(vp, -1, 1))
    assert tool.on_value(vp, (6.0, 4.0))
    xs = [v.position.x() for v in scene.groups[0].mesh.vertices]
    ys = [v.position.y() for v in scene.groups[0].mesh.vertices]
    assert (min(xs), max(xs)) == (pytest.approx(-6.0), pytest.approx(0.0))
    assert (min(ys), max(ys)) == (pytest.approx(0.0), pytest.approx(4.0))


def test_deform_tool_pushes_the_group_it_is_clicked_on():
    scene = Scene()
    g = terrain_group(*grid_terrain(QVector3D(0, 0, 0),
                                    QVector3D(10, 10, 0), 1.0))
    scene.groups.append(g)
    vp = _Vp(scene, pick=lambda x, y: (g.mesh.faces[0], g))
    tool = TerrainDeformTool()
    tool.on_activate(vp)
    assert tool.on_value(vp, 4.0)                       # the radius
    assert tool.radius == 4.0
    tool.on_click(_ctx(vp, 5, 5))
    tool.on_hover(_ctx(vp, 5, 5, 1.5))
    assert tool.value_label()[0].startswith("+")
    assert len(tool.rubber_band_lines()) > 48           # ring + moved edges
    tool.on_click(_ctx(vp, 5, 5, 1.5))
    assert _z_at(g.mesh, 5, 5) == pytest.approx(1.5)
    assert tool.start_point is None                     # ready for the next
    vp.history.undo()
    assert _z_at(g.mesh, 5, 5) == pytest.approx(0.0)


def test_deform_tool_takes_a_typed_height_and_refuses_thin_air():
    scene = Scene()
    verts, tris = grid_terrain(QVector3D(0, 0, 0), QVector3D(10, 10, 0), 1)
    for a, b, c in tris:
        scene.mesh.add_face([verts[a], verts[b], verts[c]])
    vp = _Vp(scene, pick=lambda x, y: (scene.mesh.faces[0], None))
    tool = TerrainDeformTool()
    tool.on_activate(vp)
    tool.on_click(_ctx(vp, 5, 5))
    assert tool.on_value(vp, -2.0)
    assert _z_at(scene.mesh, 5, 5) == pytest.approx(-2.0)
    # Nothing under the cursor: no push, a word in the status bar.
    empty = _Vp(Scene())
    tool.on_click(_ctx(empty, 1, 1))
    assert tool.start_point is None and empty.flashes


# ---- Drape -------------------------------------------------------------------


def _sound(mesh):
    """Every face a triangle, no edge shared by more than two faces."""
    assert all(len(f.loop) == 3 for f in mesh.faces)
    assert all(len(e.faces) <= 2 for e in mesh.edges)


def _tilted(w=10.0, d=10.0, cell=1.0):
    """A grid on the plane z = 0.5 x + 0.2 y."""
    mesh = _grid(w, d, cell)
    for v in list(mesh.vertices):
        p = v.position
        mesh.place_vertex(v, QVector3D(p.x(), p.y(), 0.5 * p.x() + 0.2 * p.y()))
    return mesh


def test_drape_cuts_a_line_into_the_ground_along_it():
    mesh = _tilted()
    a, b = QVector3D(0.3, 0.2, 9.0), QVector3D(9.7, 6.1, 9.0)
    edges = imprint_segments(mesh, [(a, b)])
    _sound(mesh)
    assert edges and all(not e.soft for e in edges)
    plan = sum(math.hypot(e.b.x() - e.a.x(), e.b.y() - e.a.y()) for e in edges)
    assert plan == pytest.approx(math.hypot(9.4, 5.9), abs=1e-4)
    # On the ground, not at the height it was drawn.
    for e in edges:
        for p in (e.a, e.b):
            assert p.z() == pytest.approx(0.5 * p.x() + 0.2 * p.y(), abs=1e-5)
    # The ground is still the same surface: nothing moved, nothing lost.
    area = sum(f.area() for f in mesh.faces)
    assert area == pytest.approx(10 * 10 * math.sqrt(1 + 0.25 + 0.04), rel=1e-5)


def test_drape_keeps_the_paint_and_the_part_off_the_ground_is_ignored():
    mesh = _grid()
    for f in mesh.faces:
        f.attrs["color"] = [0.2, 0.6, 0.3]
    edges = imprint_segments(mesh, [(QVector3D(-5, 5, 0), QVector3D(5, 5, 0))])
    _sound(mesh)
    plan = sum(e.length() for e in edges)
    assert plan == pytest.approx(5.0, abs=1e-4)
    assert all(f.attrs.get("color") == [0.2, 0.6, 0.3] for f in mesh.faces)


def test_drape_along_an_existing_grid_line_only_shows_it():
    mesh = _grid()
    n = len(mesh.faces)
    edges = imprint_segments(mesh, [(QVector3D(0, 3, 0), QVector3D(10, 3, 0))])
    assert len(mesh.faces) == n
    assert len(edges) == 10 and all(not e.soft for e in edges)


def test_drape_leaves_faces_that_look_down_alone():
    mesh = _grid()
    bottom = mesh.add_face([QVector3D(0, 0, -3), QVector3D(0, 10, -3),
                            QVector3D(10, 10, -3), QVector3D(10, 0, -3)])
    assert bottom.normal().z() < 0
    imprint_segments(mesh, [(QVector3D(1, 1, 0), QVector3D(9, 8, 0))])
    assert bottom in mesh.faces and len(bottom.loop) == 4


def test_drape_through_a_group_matrix():
    mesh = _grid()
    xf = QMatrix4x4()
    xf.translate(50.0, 0.0, 2.0)
    edges = imprint_segments(mesh, [(QVector3D(51, 5, 0), QVector3D(59, 5, 0))],
                             xf)
    assert sum(e.length() for e in edges) == pytest.approx(8.0, abs=1e-4)
    tilted = QMatrix4x4()
    tilted.rotate(30.0, 1.0, 0.0, 0.0)
    assert imprint_segments(_grid(), [(QVector3D(1, 5, 0), QVector3D(9, 5, 0))],
                            tilted) == []


# ---- Stamp -------------------------------------------------------------------

_FOOT = [QVector3D(10.5, 7.3, 0), QVector3D(18.2, 7.3, 0),
         QVector3D(18.2, 13.1, 0), QVector3D(10.5, 13.1, 0)]


def _rough():
    return terrain_mesh(*grid_terrain(QVector3D(0, 0, 0), QVector3D(30, 20, 0),
                                      1.0, relief=1.2, seed=3))


def _inside(p, eps=1e-6):
    return (10.5 - eps <= p.x() <= 18.2 + eps
            and 7.3 - eps <= p.y() <= 13.1 + eps)


def _plan_gap(p):
    """Plan distance from p to the footprint rectangle (0 inside)."""
    dx = max(10.5 - p.x(), 0.0, p.x() - 18.2)
    dy = max(7.3 - p.y(), 0.0, p.y() - 13.1)
    return math.hypot(dx, dy)


def test_platform_heights_level_inside_and_slope_out_to_the_ground():
    pts = [QVector3D(14, 10, 3.0), QVector3D(19.2, 10, 3.0),
           QVector3D(20.2, 10, 3.0), QVector3D(25, 10, 3.0)]
    foot = [(p.x(), p.y()) for p in _FOOT]
    zs = platform_heights(pts, foot, 1.0, 2.0)
    assert list(zs) == pytest.approx([1.0, 2.0, 3.0, 3.0])


def test_stamp_cuts_a_level_platform_with_its_edge_shown():
    mesh = _rough()
    before = {(round(v.position.x(), 4), round(v.position.y(), 4)):
              v.position.z() for v in mesh.vertices}
    moved = stamp_platform(mesh, _FOOT, 0.4, 2.0)
    assert moved > 0
    _sound(mesh)
    inside = [v.position for v in mesh.vertices if _inside(v.position)]
    assert inside and all(p.z() == pytest.approx(0.4) for p in inside)
    # The outline is cut exactly and shown: a hard edge all round.
    hard = [e for e in mesh.edges if not e.soft and len(e.faces) == 2]
    assert sum(e.length() for e in hard) == pytest.approx(2 * (7.7 + 5.8),
                                                          abs=1e-4)
    for v in mesh.vertices:
        p = v.position
        key = (round(p.x(), 4), round(p.y(), 4))
        gap = _plan_gap(p)
        if gap >= 2.0 and key in before:          # past the slope: as it was
            assert p.z() == pytest.approx(before[key], abs=1e-6)
        elif 0.0 < gap < 2.0 and key in before:   # on the slope: in between
            lo, hi = sorted((0.4, before[key]))
            assert lo - 1e-6 <= p.z() <= hi + 1e-6


def test_stamp_cuts_where_the_ground_is_high_and_fills_where_it_is_low():
    mesh = _grid(30, 20, 1.0)
    for v in list(mesh.vertices):                 # a slope across the site
        p = v.position
        mesh.place_vertex(v, QVector3D(p.x(), p.y(), (p.x() - 14.0) * 0.3))
    stamp_platform(mesh, _FOOT, 0.0, 1.5)
    zs = {round(v.position.x(), 4): v.position.z() for v in mesh.vertices
          if abs(v.position.y() - 10.0) < 1e-6}
    assert zs[12.0] == pytest.approx(0.0)         # was -0.6: filled
    assert zs[17.0] == pytest.approx(0.0)         # was +0.9: cut
    assert zs[25.0] == pytest.approx((25 - 14) * 0.3)


def test_stamp_command_is_one_undo_step_on_a_group():
    scene = Scene()
    history = History(scene)
    g = Group(_rough(), "Terrain")
    scene.groups.append(g)
    z0 = sorted(v.position.z() for v in g.mesh.vertices)
    history.execute(StampCommand(g.mesh, _FOOT, 0.4, 2.0))
    assert history.last_error is None
    history.undo()
    assert sorted(v.position.z() for v in g.mesh.vertices) == z0
    history.redo()
    assert any(_inside(v.position) and v.position.z() == pytest.approx(0.4)
               for v in g.mesh.vertices)


# ---- Stamp and Drape tools ---------------------------------------------------

class _Seq:
    """A picker answering from a list, one answer per click."""

    def __init__(self, *answers):
        self.answers = list(answers)

    def __call__(self, x, y):
        return self.answers.pop(0) if self.answers else (None, None)


def test_stamp_tool_shape_then_ground_then_height():
    scene = Scene()
    g = Group(_rough(), "Terrain")
    house = Group(Mesh(), "Footprint")
    foot = house.mesh.add_face([QVector3D(p.x(), p.y(), 2.0) for p in _FOOT])
    scene.groups += [g, house]
    vp = _Vp(scene, pick=_Seq((foot, house), (g.mesh.faces[0], g)))
    tool = TerrainStampTool()
    tool.on_activate(vp)
    assert tool.on_value(vp, 1.5)                       # the slope
    tool.on_click(_ctx(vp, 14, 10, 2.0))                # the shape
    assert tool.footprint and tool.start_point is None
    assert tool.level() == pytest.approx(2.0)
    tool.on_click(_ctx(vp, 14, 10, 0.5))                # the ground
    assert tool.start_point is not None
    tool.on_hover(_ctx(vp, 14, 10, 0.0))                # 0.5 below the click
    assert tool.platform_height() == pytest.approx(1.5)
    assert tool.rubber_band_lines()
    tool.on_click(_ctx(vp, 14, 10, 0.0))
    inside = [v.position.z() for v in g.mesh.vertices if _inside(v.position)]
    assert inside and all(z == pytest.approx(1.5) for z in inside)
    assert tool.footprint is None                       # ready for the next
    vp.history.undo()
    assert not any(_inside(v.position) and abs(v.position.z() - 1.5) < 1e-9
                   for v in g.mesh.vertices)


def test_stamp_tool_typed_rise_and_refusals():
    scene = Scene()
    g = Group(_rough(), "Terrain")
    house = Group(Mesh(), "Footprint")
    foot = house.mesh.add_face(_FOOT)
    scene.groups += [g, house]
    vp = _Vp(scene, pick=_Seq((None, None), (foot, house), (foot, house),
                              (g.mesh.faces[0], g)))
    tool = TerrainStampTool()
    tool.on_activate(vp)
    tool.on_click(_ctx(vp, 0, 0))                       # nothing: refused
    assert tool.footprint is None and vp.flashes
    tool.on_click(_ctx(vp, 14, 10))                     # the shape
    tool.on_click(_ctx(vp, 14, 10))                     # the shape again
    assert tool.start_point is None                     # not its own ground
    tool.on_click(_ctx(vp, 14, 10))                     # the ground
    assert tool.on_value(vp, 0.25)                      # rise over the shape
    inside = [v.position.z() for v in g.mesh.vertices if _inside(v.position)]
    assert inside and all(z == pytest.approx(0.25) for z in inside)


def test_drape_tool_cuts_the_selected_edges_into_the_clicked_ground():
    scene = Scene()
    g = Group(_grid(), "Terrain")
    scene.groups.append(g)
    path = [scene.mesh.add_edge(QVector3D(1, 1, 5), QVector3D(5, 8, 5)),
            scene.mesh.add_edge(QVector3D(5, 8, 5), QVector3D(9, 2, 5))]
    vp = _Vp(scene, pick=lambda x, y: (g.mesh.faces[0], g))
    tool = TerrainDrapeTool()
    tool.on_click(_ctx(vp, 5, 5))                       # nothing selected
    assert vp.flashes and not vp.history.undo_stack
    scene.selection.update(path)
    n = len(g.mesh.faces)
    tool.on_click(_ctx(vp, 5, 5))
    assert len(g.mesh.faces) > n
    _sound(g.mesh)
    hard = [e for e in g.mesh.edges if not e.soft and len(e.faces) == 2]
    want = math.hypot(4, 7) + math.hypot(4, 6)
    assert sum(e.length() for e in hard) == pytest.approx(want, abs=1e-4)
    assert len(scene.mesh.edges) == 2                   # the path stays
    vp.history.undo()
    assert len(g.mesh.faces) == n


def test_stamp_hint_follows_its_three_steps():
    from views.status_hints import phase_of
    tool = TerrainStampTool()
    assert phase_of("terrain_stamp", tool) == "idle"
    tool.footprint = list(_FOOT)
    assert phase_of("terrain_stamp", tool) == "ground"
    tool.start_point = QVector3D(14, 10, 0)
    assert phase_of("terrain_stamp", tool) == "height"
