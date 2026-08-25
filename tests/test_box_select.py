# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Rubber-band box selection — window vs crossing (SketchUp-style).

- Left-to-right drag (``crossing=False``, "window"): selects only entities whose
  screen projection is *entirely* inside the box.
- Right-to-left drag (``crossing=True``, "crossing"): selects anything the box
  touches (a vertex inside, or an edge crossing the box).

Headless: a stub viewport projects world (x, y) straight to pixels so the box
maths is exercised without a GL context.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.geometry import Edge, Face
from core.scene import Scene
from tools.select import SelectTool


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


class _StubViewport:
    def __init__(self, scene):
        self.scene = scene
    def _world_to_pixel(self, v):
        return (v.x(), v.y())
    def update(self):
        pass


def _scene():
    s = Scene()
    s.edges.append(Edge(V(1, 1), V(2, 2)))      # fully inside (0,0,5,5)
    s.edges.append(Edge(V(4, 4), V(10, 10)))    # one end inside, crosses out
    s.edges.append(Edge(V(20, 20), V(30, 30)))  # fully outside
    s.faces.append(Face([V(1, 1), V(2, 1), V(2, 2), V(1, 2)]))      # fully inside
    s.faces.append(Face([V(4, 4), V(10, 4), V(10, 10), V(4, 10)]))  # partly inside
    return s


RECT = (0.0, 0.0, 5.0, 5.0)


def test_window_selects_only_fully_enclosed():
    scene = _scene()
    vp = _StubViewport(scene)
    SelectTool().on_box_select(vp, RECT, crossing=False, additive=False)
    assert scene.edges[0] in scene.selection          # fully inside edge
    assert scene.edges[1] not in scene.selection      # crosses out → excluded
    assert scene.edges[2] not in scene.selection
    assert scene.faces[0] in scene.selection          # fully inside face
    assert scene.faces[1] not in scene.selection      # partly inside → excluded


def test_crossing_selects_anything_touched():
    scene = _scene()
    vp = _StubViewport(scene)
    SelectTool().on_box_select(vp, RECT, crossing=True, additive=False)
    assert scene.edges[0] in scene.selection          # inside
    assert scene.edges[1] in scene.selection          # touches the box
    assert scene.edges[2] not in scene.selection      # fully outside
    assert scene.faces[0] in scene.selection
    assert scene.faces[1] in scene.selection          # a vertex is inside


def test_box_select_additive_keeps_previous():
    scene = _scene()
    vp = _StubViewport(scene)
    scene.select([scene.edges[2]])                    # pre-select the far edge
    SelectTool().on_box_select(vp, RECT, crossing=False, additive=True)
    assert scene.edges[2] in scene.selection          # kept
    assert scene.edges[0] in scene.selection          # added by the box


# ---- Groups (the "box select skips groups" report) --------------------------

def _group_at(scene, x0, y0, size=2.0):
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    m.add_face([V(x0, y0), V(x0 + size, y0),
                V(x0 + size, y0 + size), V(x0, y0 + size)])
    g = Group(m)
    scene.groups.append(g)
    return g


def test_window_box_selects_groups_fully_inside():
    scene = Scene()
    vp = _StubViewport(scene)
    g_in = _group_at(scene, 1, 1)                     # fully inside (0,0,5,5)
    g_part = _group_at(scene, 4, 4)                   # sticks out
    g_out = _group_at(scene, 20, 20)
    SelectTool().on_box_select(vp, RECT, crossing=False, additive=False)
    assert g_in in scene.selection
    assert g_part not in scene.selection
    assert g_out not in scene.selection


def test_crossing_box_selects_touched_groups():
    scene = Scene()
    vp = _StubViewport(scene)
    g_in = _group_at(scene, 1, 1)
    g_part = _group_at(scene, 4, 4)
    g_out = _group_at(scene, 20, 20)
    SelectTool().on_box_select(vp, RECT, crossing=True, additive=False)
    assert g_in in scene.selection
    assert g_part in scene.selection                  # touched → selected
    assert g_out not in scene.selection


def test_crossing_box_catches_group_edge_straddling_it():
    # No vertex lands inside the box; a wireframe edge passes through it.
    from core.group import Group
    from core.mesh import Mesh
    scene = Scene()
    vp = _StubViewport(scene)
    m = Mesh()
    m.add_edge(V(-10, 2.5), V(10, 2.5))
    g = Group(m)
    scene.groups.append(g)
    SelectTool().on_box_select(vp, RECT, crossing=True, additive=False)
    assert g in scene.selection


def test_box_select_maps_instances_to_world():
    # The prototype lives at the origin; only the instance whose TRANSFORM
    # puts it inside the box may be selected.
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group
    from core.mesh import Mesh
    scene = Scene()
    vp = _StubViewport(scene)
    proto = Mesh()
    proto.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])

    def instance(dx, dy):
        g = Group(proto)
        t = QMatrix4x4()
        t.translate(V(dx, dy, 0))
        g.xform = t
        scene.groups.append(g)
        return g

    near = instance(1, 1)                             # world (1,1)-(2,2): inside
    far = instance(20, 20)                            # world (20,20)-(21,21)
    SelectTool().on_box_select(vp, RECT, crossing=False, additive=False)
    assert near in scene.selection
    assert far not in scene.selection


def test_crossing_box_selects_guides_window_does_not():
    # An infinite guide line can never be fully enclosed → only a crossing box
    # takes it (SketchUp). Guide points behave like any point.
    from core.guide import Guide
    scene = Scene()
    vp = _StubViewport(scene)
    line = Guide(V(2, 2), V(1, 0, 0))                 # crosses the box
    point = Guide(V(3, 3))                            # inside the box
    far_point = Guide(V(50, 50))
    scene.guides += [line, point, far_point]

    SelectTool().on_box_select(vp, RECT, crossing=False, additive=False)
    assert line not in scene.selection                # window: never the line
    assert point in scene.selection
    assert far_point not in scene.selection

    SelectTool().on_box_select(vp, RECT, crossing=True, additive=False)
    assert line in scene.selection                    # crossing takes it
    assert point in scene.selection


def test_delete_key_erases_selected_guides():
    from PySide6.QtCore import Qt
    from core.guide import Guide
    from core.history import History
    scene = Scene()
    vp = _StubViewport(scene)
    vp.history = History(scene)
    g = Guide(V(0, 0), V(1, 0, 0))
    scene.guides.append(g)
    scene.selection.add(g)
    assert SelectTool().on_key(vp, Qt.Key_Delete, Qt.NoModifier) is True
    assert scene.guides == []
    assert g not in scene.selection
    assert vp.history.undo()
    assert scene.guides == [g]


def test_box_ignores_other_groups_inside_group_edit():
    scene = Scene()
    vp = _StubViewport(scene)
    edited = _group_at(scene, 30, 30)
    other = _group_at(scene, 1, 1)                    # would fall in the box
    scene.begin_group_edit(edited)
    SelectTool().on_box_select(vp, RECT, crossing=True, additive=False)
    assert other not in scene.selection
    scene.end_group_edit()
