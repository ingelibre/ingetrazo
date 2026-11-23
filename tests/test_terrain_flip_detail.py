# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Draw ▸ Terrain ▸ Flip Edge and Add Detail: an inner edge of the ground
turned to the other diagonal of its two triangles, and the triangles round
a click split in four without opening a crack — one undo step each, on
the loose geometry or a group's mesh from outside it."""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group
from core.history import History
from core.scene import Scene
from core.terrain_mesh import (FLIP_CONCAVE, FLIP_HARD, FLIP_POLYGON,
                               FLIP_RIM, AddDetailCommand, FlipEdgeCommand,
                               add_detail, detail_preview, flip_edge,
                               flip_preview, flip_problem, grid_terrain,
                               imprint_segments, terrain_group, terrain_mesh)
from tools.base import ToolContext
from tools.terrain import TerrainDetailTool, TerrainFlipTool


def _grid(w=4.0, d=4.0, cell=1.0):
    return terrain_mesh(*grid_terrain(QVector3D(0, 0, 0), QVector3D(w, d, 0),
                                      cell))


def _v(mesh, x, y):
    for v in mesh.vertices:
        p = v.position
        if abs(p.x() - x) < 1e-6 and abs(p.y() - y) < 1e-6:
            return v
    raise AssertionError(f"no vertex at ({x}, {y})")


def _edge(mesh, a, b):
    return mesh.find_edge(_v(mesh, *a), _v(mesh, *b))


def _cell_diagonal(mesh, x, y):
    """The diagonal the grid drew across cell ``(x, y)``–``(x+1, y+1)``."""
    e = _edge(mesh, (x, y), (x + 1, y + 1))
    if e is None:
        e = _edge(mesh, (x + 1, y), (x, y + 1))
    assert e is not None
    return e


def _plan_area(mesh):
    total = 0.0
    for f in mesh.faces:
        pts = [v.position for v in f.loop]
        for k in range(len(pts)):
            a, b = pts[k], pts[(k + 1) % len(pts)]
            total += a.x() * b.y() - b.x() * a.y()
    return total / 2.0


def _sound(mesh, w=4.0, d=4.0):
    """Every face a triangle facing up, no edge on more than two faces, an
    open side only on the rim, and no corner sitting inside another
    face's side (no crack)."""
    assert all(len(f.loop) == 3 for f in mesh.faces)
    assert all(f.normal().z() > 0.0 for f in mesh.faces)
    for e in mesh.edges:
        assert len(e.faces) <= 2
        if len(e.faces) == 1:
            a, b = e.v0.position, e.v1.position
            on_rim = any(abs(a.x() - s) < 1e-6 and abs(b.x() - s) < 1e-6
                         for s in (0.0, w)) or any(
                abs(a.y() - s) < 1e-6 and abs(b.y() - s) < 1e-6
                for s in (0.0, d))
            assert on_rim, f"crack along {a} – {b}"
    for e in mesh.edges:
        a, b = e.v0.position, e.v1.position
        ab = b - a
        l2 = QVector3D.dotProduct(ab, ab)
        for v in mesh.vertices:
            if v is e.v0 or v is e.v1:
                continue
            t = QVector3D.dotProduct(v.position - a, ab) / l2
            if 1e-6 < t < 1 - 1e-6:
                assert (v.position - (a + ab * t)).length() > 1e-6, (
                    f"corner {v.position} inside a side")


# ---- Flip edge ---------------------------------------------------------------

def test_flip_turns_the_shared_edge_to_the_other_diagonal():
    m = _grid()
    old = _cell_diagonal(m, 1, 1)
    ends = {(round(old.v0.position.x()), round(old.v0.position.y())),
            (round(old.v1.position.x()), round(old.v1.position.y()))}
    faces, edges, area = len(m.faces), len(m.edges), _plan_area(m)
    assert flip_problem(m, old) is None
    assert flip_edge(m, old)
    assert (len(m.faces), len(m.edges)) == (faces, edges)
    assert _plan_area(m) == pytest.approx(area)
    other = ({(1, 2), (2, 1)} if ends == {(1, 1), (2, 2)}
             else {(1, 1), (2, 2)})
    a, b = sorted(other)
    new = _edge(m, a, b)
    assert new is not None and new.soft                # keeps the old flags
    assert _edge(m, *sorted(ends)) is None
    _sound(m)


def test_flip_moves_the_ridge_and_flipping_again_puts_it_back():
    """A saddle cell: the diagonal decides whether its middle is a valley
    or a ridge."""
    m = _grid()
    for (x, y), z in (((1, 2), 1.0), ((2, 1), 1.0)):
        v = _v(m, x, y)
        m.place_vertex(v, QVector3D(x, y, z))
    e = _cell_diagonal(m, 1, 1)
    first = {id(e.v0), id(e.v1)}
    assert flip_edge(m, e)
    e2 = _cell_diagonal(m, 1, 1)
    assert {id(e2.v0), id(e2.v1)} != first
    assert flip_edge(m, e2)
    e3 = _cell_diagonal(m, 1, 1)
    assert {(round(v.position.x()), round(v.position.y()))
            for v in (e3.v0, e3.v1)} == {
        (round(v.position.x()), round(v.position.y())) for v in (e.v0, e.v1)}
    _sound(m)


def test_flip_refuses_the_rim_a_hard_line_a_concave_pair_and_polygons():
    m = _grid()
    rim = _edge(m, (0, 0), (1, 0))
    assert flip_problem(m, rim) == FLIP_RIM
    line = _cell_diagonal(m, 2, 2)
    line.soft = False
    assert flip_problem(m, line) == FLIP_HARD
    assert not flip_edge(m, line)
    # Pull a corner across, in plan: the pair round the diagonal of cell
    # (0, 2) stops being convex.
    e = _cell_diagonal(m, 0, 2)
    pair_corners = {(round(v.position.x()), round(v.position.y()))
                    for f in e.faces for v in f.loop} - {
        (round(e.v0.position.x()), round(e.v0.position.y())),
        (round(e.v1.position.x()), round(e.v1.position.y()))}
    cx, cy = sorted(pair_corners)[0]
    v = _v(m, cx, cy)
    # Towards and past the diagonal's middle.
    mx = (e.v0.position.x() + e.v1.position.x()) / 2
    my = (e.v0.position.y() + e.v1.position.y()) / 2
    m.place_vertex(v, QVector3D(cx + 1.6 * (mx - cx), cy + 1.6 * (my - cy), 0))
    assert flip_problem(m, e) == FLIP_CONCAVE
    # A quad face: not two triangles.
    from core.mesh import Mesh
    q = Mesh()
    q.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0),
                QVector3D(0, 1, 0)])
    q.add_face([QVector3D(1, 0, 0), QVector3D(2, 0, 0), QVector3D(1, 1, 0)])
    shared = q.find_edge(q.vertex_at(QVector3D(1, 0, 0)),
                         q.vertex_at(QVector3D(1, 1, 0)))
    shared.soft = True
    assert flip_problem(q, shared) == FLIP_POLYGON


def test_flip_keeps_the_paint_of_both_triangles():
    m = _grid()
    e = _cell_diagonal(m, 1, 1)
    f1, f2 = e.faces
    f1.attrs["material"] = "grass"
    f2.attrs["material"] = "gravel"
    assert flip_edge(m, e)
    corners = {id(e.v0), id(e.v1)}
    new = [f for f in m.faces
           if f.attrs.get("material") in ("grass", "gravel")]
    assert len(new) == 2
    assert {f.attrs["material"] for f in new} == {"grass", "gravel"}
    assert not any(corners == {id(v) for v in f.loop[:2]} for f in new)


def test_flip_preview_is_the_quad_and_its_new_diagonal():
    m = _grid()
    e = _cell_diagonal(m, 1, 1)
    lines = flip_preview(e)
    assert len(lines) == 5
    c, d = lines[-1]
    assert {(round(c.x()), round(c.y())), (round(d.x()), round(d.y()))} != {
        (round(e.v0.position.x()), round(e.v0.position.y())),
        (round(e.v1.position.x()), round(e.v1.position.y()))}
    assert len(m.faces) == 32                          # untouched


def test_flip_command_is_one_undo_step_on_a_turned_group():
    scene = Scene()
    history = History(scene)
    g = terrain_group(*grid_terrain(QVector3D(0, 0, 0), QVector3D(4, 4, 0),
                                    1.0))
    xf = QMatrix4x4()
    xf.translate(10, 5, 2)
    xf.rotate(30, 0, 0, 1)
    g.xform = xf
    scene.groups.append(g)
    e = _cell_diagonal(g.mesh, 1, 1)
    before = {id(e.v0), id(e.v1)}
    ends = (QVector3D(e.v0.position), QVector3D(e.v1.position))
    history.execute(FlipEdgeCommand(g.mesh, *ends, xf))
    assert history.last_error is None
    assert g.mesh.find_edge(g.mesh.vertex_at(ends[0]),
                            g.mesh.vertex_at(ends[1])) is None
    history.undo()
    back = g.mesh.find_edge(g.mesh.vertex_at(ends[0]),
                            g.mesh.vertex_at(ends[1]))
    assert back is not None
    history.redo()
    assert g.mesh.find_edge(g.mesh.vertex_at(ends[0]),
                            g.mesh.vertex_at(ends[1])) is None
    assert len(scene.mesh.faces) == 0
    assert before                                      # (ids were real)


# ---- Add detail --------------------------------------------------------------

def test_radius_zero_splits_the_clicked_triangle_in_four_without_cracks():
    m = _grid()
    area = _plan_area(m)
    n = add_detail(m, QVector3D(1.3, 1.6, 0), 0.0)
    assert n == 1
    assert _plan_area(m) == pytest.approx(area)
    # 32 triangles: one became 4, its three neighbours 2 each.
    assert len(m.faces) == 32 - 4 + 4 + 3 * 2
    _sound(m)


def test_a_radius_splits_everything_it_reaches_and_closes_the_gaps():
    m = _grid()
    area = _plan_area(m)
    n = add_detail(m, QVector3D(2, 2, 0), 1.2)
    assert n >= 8
    assert _plan_area(m) == pytest.approx(area)
    _sound(m)
    # And again on the finer ground: still sound.
    add_detail(m, QVector3D(2.2, 1.9, 0), 0.6)
    assert _plan_area(m) == pytest.approx(area)
    _sound(m)


def test_detail_keeps_the_shape_of_a_sloping_ground():
    m = _grid()
    for v in list(m.vertices):
        p = v.position
        m.place_vertex(v, QVector3D(p.x(), p.y(), 0.5 * p.x() + 0.2 * p.y()))
    add_detail(m, QVector3D(2, 2, 0), 1.5)
    for v in m.vertices:
        p = v.position
        assert p.z() == pytest.approx(0.5 * p.x() + 0.2 * p.y(), abs=1e-6)


def test_detail_keeps_soft_inner_edges_hard_lines_and_paint():
    m = _grid()
    line = imprint_segments(m, [(QVector3D(0.5, 2.0, 5), QVector3D(3.5, 2.0, 5))])
    assert line
    for f in m.faces:
        f.attrs["material"] = "grass"
    add_detail(m, QVector3D(2, 2, 0), 1.0)
    hard_on_line = [e for e in m.edges
                    if not e.soft and len(e.faces) == 2
                    and abs(e.v0.position.y() - 2) < 1e-6
                    and abs(e.v1.position.y() - 2) < 1e-6]
    xs = sorted({round(v.position.x(), 6) for e in hard_on_line
                 for v in (e.v0, e.v1)})
    assert xs[0] == pytest.approx(0.5) and xs[-1] == pytest.approx(3.5)
    # Every other inner edge is soft, the rim stays hard.
    for e in m.edges:
        if len(e.faces) == 1:
            assert not e.soft
        elif e not in hard_on_line:
            assert e.soft
    assert all(f.attrs.get("material") == "grass" for f in m.faces)


def test_detail_out_of_reach_and_faces_looking_down_are_left_alone():
    m = _grid()
    assert add_detail(m, QVector3D(50, 50, 0), 1.0) == 0
    assert len(m.faces) == 32
    from core.mesh import Mesh
    down = Mesh()
    down.add_face([QVector3D(0, 0, 0), QVector3D(0, 1, 0), QVector3D(1, 0, 0)])
    assert down.faces[0].normal().z() < 0
    assert add_detail(down, QVector3D(0.2, 0.2, 0), 1.0) == 0


def test_detail_preview_draws_the_middle_triangles_without_touching():
    m = _grid()
    lines = detail_preview(m, QVector3D(1.3, 1.6, 0), 0.0)
    assert len(lines) == 3
    assert len(m.faces) == 32
    assert detail_preview(m, QVector3D(50, 50, 0), 1.0) == []


def test_detail_command_is_one_undo_step_through_a_group_matrix():
    scene = Scene()
    history = History(scene)
    g = terrain_group(*grid_terrain(QVector3D(0, 0, 0), QVector3D(4, 4, 0),
                                    1.0))
    xf = QMatrix4x4()
    xf.translate(100, 0, 0)
    g.xform = xf
    scene.groups.append(g)
    # (1.3, 1.6) of the group is (101.3, 1.6) in the world.
    cmd = AddDetailCommand(g.mesh, QVector3D(101.3, 1.6, 0), 0.0, xf)
    history.execute(cmd)
    assert cmd.result == 1 and len(g.mesh.faces) == 38
    history.undo()
    assert len(g.mesh.faces) == 32
    history.redo()
    assert len(g.mesh.faces) == 38
    _sound(g.mesh)


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

    def refresh_hint(self, *_a):
        pass

    def pick_face_placement(self, x, y):
        return self._pick(x, y) if self._pick else (None, None)


def _ctx(vp, x, y, z=0.0):
    return ToolContext(viewport=vp, world=QVector3D(x, y, z),
                       screen=QPointF(x, y), modifiers=Qt.NoModifier,
                       snap=SimpleNamespace(kind="none"))


def _face_at(mesh, x, y):
    for f in mesh.faces:
        a, b, c = (v.position for v in f.loop)
        d = (b.y() - c.y()) * (a.x() - c.x()) + (c.x() - b.x()) * (a.y() - c.y())
        l0 = ((b.y() - c.y()) * (x - c.x()) + (c.x() - b.x()) * (y - c.y())) / d
        l1 = ((c.y() - a.y()) * (x - c.x()) + (a.x() - c.x()) * (y - c.y())) / d
        if min(l0, l1, 1 - l0 - l1) >= -1e-9:
            return f
    return None


def test_flip_tool_flips_the_side_nearest_the_click_in_a_group():
    scene = Scene()
    g = terrain_group(*grid_terrain(QVector3D(0, 0, 0), QVector3D(4, 4, 0),
                                    1.0))
    scene.groups.append(g)
    vp = _Vp(scene, pick=lambda x, y: (_face_at(g.mesh, x, y), g))
    tool = TerrainFlipTool()
    tool.on_activate(vp)
    e = _cell_diagonal(g.mesh, 1, 1)
    mx = (e.v0.position.x() + e.v1.position.x()) / 2
    my = (e.v0.position.y() + e.v1.position.y()) / 2
    # Just off the diagonal's middle, inside one of its triangles.
    f = e.faces[0]
    cx = sum(v.position.x() for v in f.loop) / 3
    cy = sum(v.position.y() for v in f.loop) / 3
    px, py = mx + 0.1 * (cx - mx), my + 0.1 * (cy - my)
    tool.on_hover(_ctx(vp, px, py))
    assert len(tool.rubber_band_lines()) == 5
    ends = {(round(e.v0.position.x()), round(e.v0.position.y())),
            (round(e.v1.position.x()), round(e.v1.position.y()))}
    tool.on_click(_ctx(vp, px, py))
    assert _edge(g.mesh, *sorted(ends)) is None
    assert not vp.flashes
    vp.history.undo()
    assert _edge(g.mesh, *sorted(ends)) is not None


def test_flip_tool_says_why_it_will_not_and_leaves_the_history_alone():
    scene = Scene()
    g = terrain_group(*grid_terrain(QVector3D(0, 0, 0), QVector3D(4, 4, 0),
                                    1.0))
    scene.groups.append(g)
    vp = _Vp(scene, pick=lambda x, y: (_face_at(g.mesh, x, y), g))
    tool = TerrainFlipTool()
    tool.on_hover(_ctx(vp, 0.5, 0.02))                  # by the rim
    assert tool.rubber_band_lines() == []
    tool.on_click(_ctx(vp, 0.5, 0.02))
    assert vp.flashes and "rim" in vp.flashes[-1]
    assert not vp.history.undo_stack
    empty = _Vp(Scene())
    tool.on_click(_ctx(empty, 1, 1))
    assert empty.flashes


def test_detail_tool_radius_click_and_refusals():
    scene = Scene()
    g = terrain_group(*grid_terrain(QVector3D(0, 0, 0), QVector3D(4, 4, 0),
                                    1.0))
    scene.groups.append(g)
    vp = _Vp(scene, pick=lambda x, y: (_face_at(g.mesh, x, y), g))
    tool = TerrainDetailTool()
    tool.on_activate(vp)
    assert not tool.on_value(vp, -1.0)
    assert not tool.on_value(vp, (1.0, 2.0))
    assert tool.on_value(vp, 0.0)
    assert tool.status_clause() == "Only the clicked triangle"
    tool.on_hover(_ctx(vp, 1.3, 1.6))
    assert len(tool.rubber_band_lines()) == 3          # no ring at 0
    tool.on_click(_ctx(vp, 1.3, 1.6))
    assert len(g.mesh.faces) == 38
    assert tool.on_value(vp, 2.0)
    assert "Radius" in tool.status_clause()
    tool.on_hover(_ctx(vp, 2, 2))
    assert len(tool.rubber_band_lines()) > 48          # ring + new edges
    vp.history.undo()
    assert len(g.mesh.faces) == 32
    # Nothing under the cursor.
    empty = _Vp(Scene())
    tool.on_click(_ctx(empty, 1, 1))
    assert empty.flashes
