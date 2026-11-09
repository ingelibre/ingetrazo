# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Solid Tools (core/solids.py, tools/solid_tools.py): what the classic
documentation says each one does, on two overlapping boxes."""
from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D

from core import solids
from core.group import Group, world_mesh
from core.history import History
from core.mesh import Mesh
from core.scene import Scene
from tools.base import ToolContext

pytest.importorskip("manifold3d")

RED, BLUE = [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _box(x0, y0, z0, x1, y1, z1, color, name="box"):
    m = Mesh()
    P = V
    faces = [
        [P(x0, y0, z0), P(x0, y1, z0), P(x1, y1, z0), P(x1, y0, z0)],
        [P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)],
        [P(x0, y0, z0), P(x1, y0, z0), P(x1, y0, z1), P(x0, y0, z1)],
        [P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)],
        [P(x1, y1, z0), P(x0, y1, z0), P(x0, y1, z1), P(x1, y1, z1)],
        [P(x0, y1, z0), P(x0, y0, z0), P(x0, y0, z1), P(x0, y1, z1)],
    ]
    for pts in faces:
        m.add_face(pts).attrs["color"] = list(color)
    return Group(m, name=name)


def _pair():
    return (_box(0, 0, 0, 2, 2, 2, RED, "A"),
            _box(1, 1, 1, 3, 3, 3, BLUE, "B"))


def _colours(g):
    return {tuple(f.attrs.get("color", ())) for f in g.mesh.faces}


# ---- What is a solid -------------------------------------------------------

def test_a_closed_box_is_a_solid_with_its_volume():
    a, _b = _pair()
    assert math.isclose(solids.solid_volume(a), 8.0, rel_tol=1e-9)


def test_an_open_box_is_not_a_solid():
    a, _b = _pair()
    a.mesh.remove_face(a.mesh.faces[0])
    assert solids.solid_volume(a) is None


def test_nested_groups_disqualify():
    a, b = _pair()
    a.adopt([b])
    assert solids.solid_volume(a) is None


# ---- The six operations ------------------------------------------------------

@pytest.mark.parametrize("op, volumes, removed", [
    (solids.OUTER_SHELL, [15.0], 2),
    (solids.UNION, [15.0], 2),
    (solids.SUBTRACT, [7.0], 2),        # A cuts B: B − A, A goes
    (solids.TRIM, [7.0], 1),            # the same, A stays
    (solids.INTERSECT, [1.0], 2),
    (solids.SPLIT, [7.0, 7.0, 1.0], 2),
])
def test_each_operation(op, volumes, removed):
    a, b = _pair()
    gone, made = solids.run(op, [a, b])
    assert len(gone) == removed
    assert [round(solids.solid_volume(g), 6) for g in made] == volumes
    assert all(g.xform is None for g in made)          # plain groups


def test_subtract_and_trim_cut_the_second_with_the_first():
    a, b = _pair()
    gone, (res,) = solids.run(solids.SUBTRACT, [a, b])
    assert gone == [a, b]
    # the result is B with a corner bitten out: every point of it lies in B
    for v in res.mesh.vertices:
        p = v.position
        assert all(1.0 - 1e-6 <= c <= 3.0 + 1e-6 for c in (p.x(), p.y(), p.z()))
    gone, (res,) = solids.run(solids.TRIM, [a, b])
    assert gone == [b]                                 # the cutter stays


def test_the_faces_of_a_cut_take_the_cutters_material():
    a, b = _pair()
    _gone, (res,) = solids.run(solids.SUBTRACT, [a, b])
    assert _colours(res) == {tuple(RED), tuple(BLUE)}
    red = [f for f in res.mesh.faces if f.attrs.get("color") == RED]
    assert len(red) == 3                               # the notch's walls


def test_the_result_has_clean_polygon_faces():
    a, b = _pair()
    _gone, (res,) = solids.run(solids.SUBTRACT, [a, b])
    m = res.mesh
    assert len(m.faces) == 9                           # 6 + the notch's 3
    assert len(m.vertices) - len(m.edges) + len(m.faces) == 2   # Euler
    assert len(m.vertices) == 14                       # no stray corners


def test_outer_shell_drops_an_inner_void_union_keeps_it():
    outer = _box(0, 0, 0, 4, 4, 4, RED, "cube")
    hollow = _box(1, 1, 1, 3, 3, 3, RED, "void")
    # a closed box with a box-shaped hole inside: flip the inner shell
    for f in list(hollow.mesh.faces):
        pts = list(reversed(f.vertices))
        outer.mesh.add_face(pts).attrs["color"] = RED
    other = _box(3, 3, 3, 5, 5, 5, BLUE)
    _g, (u,) = solids.run(solids.UNION, [outer, other])
    _g, (s,) = solids.run(solids.OUTER_SHELL, [outer, other])
    assert math.isclose(solids.solid_volume(u), 64 - 8 + 8 - 1, rel_tol=1e-6)
    assert math.isclose(solids.solid_volume(s), 64 + 8 - 1, rel_tol=1e-6)


def test_disjoint_solids_are_refused():
    a = _box(0, 0, 0, 1, 1, 1, RED)
    b = _box(5, 5, 5, 6, 6, 6, BLUE)
    with pytest.raises(solids.SolidError):
        solids.run(solids.SUBTRACT, [a, b])


def test_a_component_is_read_through_its_placement_and_left_alone():
    proto = _box(0, 0, 0, 2, 2, 2, RED).mesh
    inst = Group(proto, name="comp")
    xf = QMatrix4x4()
    xf.translate(10, 0, 0)
    inst.xform = xf
    twin = Group(proto, name="twin")
    twin.xform = QMatrix4x4()
    cutter = _box(11, 1, 1, 13, 3, 3, BLUE)
    faces_before = len(proto.faces)
    _gone, (res,) = solids.run(solids.SUBTRACT, [cutter, inst])
    assert res.xform is None and res.mesh is not proto   # a group comes out
    assert len(proto.faces) == faces_before              # definition intact
    xs = [v.position.x() for v in res.mesh.vertices]
    assert min(xs) >= 10.0 - 1e-6                        # in world space


def test_a_smooth_side_stays_smooth():
    """A cylinder with a bite out of it keeps soft seams on its side."""
    import core.edits  # noqa: F401  (Mesh helpers)
    m = Mesh()
    n, r, h = 24, 1.0, 2.0
    ring = [V(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n))
            for k in range(n)]
    top = [p + V(0, 0, h) for p in ring]
    m.add_face(list(reversed(ring)))
    m.add_face(top)
    for k in range(n):
        m.add_face([ring[k], ring[(k + 1) % n], top[(k + 1) % n], top[k]])
    for k in range(n):
        e = m.find_edge(m.vertex_at(ring[k]), m.vertex_at(top[k]))
        e.soft = True
    cyl = Group(m, name="cyl")
    cutter = _box(0.5, -0.3, -1, 3, 0.3, 3, BLUE)
    _gone, (res,) = solids.run(solids.SUBTRACT, [cutter, cyl])
    assert sum(1 for e in res.mesh.edges if e.soft) >= n - 4


def _curved_cylinder(n=24, r=1.0, h=2.0):
    """A cylinder as Push/Pull leaves it: soft side seams, and each rim one
    curve (one click selects the whole circle)."""
    import core.edits  # noqa: F401  (Mesh helpers)
    m = Mesh()
    ring = [V(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n))
            for k in range(n)]
    top = [p + V(0, 0, h) for p in ring]
    m.add_face(list(reversed(ring)))
    m.add_face(top)
    for k in range(n):
        m.add_face([ring[k], ring[(k + 1) % n], top[(k + 1) % n], top[k]])
    for k in range(n):
        m.find_edge(m.vertex_at(ring[k]), m.vertex_at(top[k])).soft = True
    m.tag_curve(ring)
    m.tag_curve(top)
    return Group(m, name="cyl")


def _curves_at(mesh, z):
    """Sizes of the curves whose edges all lie at height ``z``."""
    sizes: dict = {}
    for e in mesh.edges:
        if (e.curve is not None and abs(e.a.z() - z) < 1e-6
                and abs(e.b.z() - z) < 1e-6):
            sizes[e.curve] = sizes.get(e.curve, 0) + 1
    return sorted(sizes.values())


def test_a_circle_the_cut_does_not_touch_stays_one_curve():
    """A bite out of the side: both rims come out whole, as one curve each
    (they used to come out as 24 loose segments)."""
    cyl = _curved_cylinder()
    cutter = _box(0.5, -0.3, 0.5, 3, 0.3, 1.5, BLUE)
    _gone, (res,) = solids.run(solids.SUBTRACT, [cutter, cyl])
    assert _curves_at(res.mesh, 0.0) == [24]
    assert _curves_at(res.mesh, 2.0) == [24]


def test_a_circle_the_cut_breaks_is_one_curve_per_arc():
    cyl = _curved_cylinder()
    cutter = _box(0.5, -0.3, 1.0, 3, 0.3, 3, BLUE)      # notch through the top
    _gone, (res,) = solids.run(solids.SUBTRACT, [cutter, cyl])
    assert _curves_at(res.mesh, 0.0) == [24]
    arcs = _curves_at(res.mesh, 2.0)
    assert len(arcs) == 1 and 20 <= arcs[0] < 24       # the rest of the rim


def test_a_hidden_or_tagged_edge_keeps_its_flags():
    a, b = _pair()
    e = next(e for e in b.mesh.edges
             if e.a.z() == 3 and e.b.z() == 3 and e.a.x() == e.b.x() == 3)
    e.hidden = True
    e.layer = "Layer 2"
    _gone, (res,) = solids.run(solids.SUBTRACT, [a, b])
    kept = [e for e in res.mesh.edges
            if e.a.z() == 3 and e.b.z() == 3 and e.a.x() == e.b.x() == 3]
    assert kept and all(e.hidden and e.layer == "Layer 2" for e in kept)


# ---- The command ---------------------------------------------------------------

def test_one_undo_step_puts_everything_back():
    a, b = _pair()
    scene = Scene()
    hist = History(scene)
    scene.groups += [a, b]
    hist.execute(solids.SolidOperationCommand(solids.SUBTRACT, [a, b]))
    assert len(scene.groups) == 1 and scene.selection == set(scene.groups)
    hist.undo()
    assert scene.groups == [a, b]
    hist.redo()
    assert len(scene.groups) == 1


# ---- The tool ------------------------------------------------------------------

class _VP:
    def __init__(self, scene, picks):
        self.scene = scene
        self.history = History(scene)
        self._picks = list(picks)
        self.said = []

    def pick_group(self, x, y):
        return self._picks.pop(0) if self._picks else None

    def flash_status(self, text, msec=0):
        self.said.append(text)

    def update(self):
        pass


def _click(tool, vp):
    tool.on_click(ToolContext(viewport=vp, world=V(0, 0), screen=QPointF(0, 0),
                              modifiers=Qt.NoModifier, snap=None))


def test_the_tool_picks_one_then_two_and_the_first_cuts():
    from tools.solid_tools import SubtractTool
    a, b = _pair()
    scene = Scene()
    scene.groups += [a, b]
    vp = _VP(scene, [a, b])
    tool = SubtractTool()
    tool.on_activate(vp)
    _click(tool, vp)
    assert tool.first is a and tool.dragging
    _click(tool, vp)
    assert tool.first is None
    assert len(scene.groups) == 1
    assert math.isclose(solids.solid_volume(scene.groups[0]), 7.0, rel_tol=1e-6)


def test_the_tool_refuses_what_is_not_a_solid():
    from tools.solid_tools import UnionTool
    a, _b = _pair()
    open_box = _box(5, 5, 5, 6, 6, 6, BLUE)
    open_box.mesh.remove_face(open_box.mesh.faces[0])
    scene = Scene()
    scene.groups += [a, open_box]
    vp = _VP(scene, [open_box])
    tool = UnionTool()
    tool.on_activate(vp)
    _click(tool, vp)
    assert tool.first is None and vp.said


def test_union_runs_at_once_on_a_preselection():
    from tools.solid_tools import UnionTool
    a, b = _pair()
    scene = Scene()
    scene.groups += [a, b]
    scene.selection = {a, b}
    vp = _VP(scene, [])
    UnionTool().on_activate(vp)
    assert len(scene.groups) == 1
    assert math.isclose(solids.solid_volume(scene.groups[0]), 15.0, rel_tol=1e-6)


def test_a_wall_with_two_doors_in_a_row_takes_a_third_cut():
    """#227 (@fafecm): two door openings cut into a wall with their tops at
    one height, then a third Subtract refused «a flaw the operation cannot
    read». The wall face with two holes triangulates with a long edge
    running past both holes' top corners — fine to draw, not a closed
    triangle surface for the boolean. The conversion now splits those
    triangles when, and only when, the boolean refuses the plain one."""
    wall = _box(0, 0, 0, 10, 0.2, 3, RED, "wall")
    for x0, x1 in ((2, 3), (5, 6)):           # tops and bottoms aligned
        door = _box(x0, -1, 0.1, x1, 1, 2.1, BLUE, "door")
        removed, created = solids.run(solids.SUBTRACT, [door, wall])
        assert len(created) == 1
        wall = created[0]
    window = _box(7, -1, 1, 8, 1, 2, BLUE, "window")
    removed, created = solids.run(solids.SUBTRACT, [window, wall])
    assert len(created) == 1
    expected = 10 * 0.2 * 3 - 2 * (1 * 0.2 * 2) - 1 * 0.2 * 1
    assert abs(solids.solid_volume(created[0]) - expected) < 1e-6


def test_the_t_junction_split_keeps_the_surface():
    """The split adds a point inside each triangle it fans, never moves a
    corner and never drops area."""
    import numpy as np
    v = np.array([[0, 0, 0], [2, 0, 0], [1, 1, 0], [1, 0, 0]], dtype=float)
    t = np.array([[0, 1, 2]], dtype=np.uint32)      # (1,0,0) lies on 0-1
    f = np.array([7], dtype=np.uint32)
    v2, t2, f2 = solids._conform_t_junctions(v, t, f)
    assert np.allclose(v2[:4], v)
    assert set(f2.tolist()) == {7}
    area = sum(np.linalg.norm(np.cross(v2[b] - v2[a], v2[c] - v2[a])) / 2
               for a, b, c in t2.tolist())
    assert abs(area - 1.0) < 1e-12
    edges = {frozenset(e) for a, b, c in t2.tolist()
             for e in ((a, b), (b, c), (c, a))}
    assert frozenset((0, 1)) not in edges            # split at vertex 3
