# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Click modifiers of the Select tool — SketchUp's rules (Marco, 2026-09-07:
«debería haber una opción para deseleccionar ciertas líneas o planos haciendo
shift+clic»).

Shift TOGGLES what it picks (an already-selected line or face drops out),
Ctrl adds, Shift+Ctrl removes, and a plain click replaces. The rubber-band
box reads the same modifiers, and a modified click on empty space must NOT
wipe the selection you are building.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.geometry import Edge, Face
from core.scene import Scene
from tools.base import ToolContext
from tools.select import SelectTool, selection_mode


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


class _StubViewport:
    """A viewport that picks whatever the test hands it."""

    def __init__(self, scene, pick=None):
        self.scene = scene
        self.pick = pick

    # the pick cascade SelectTool._pick walks
    def pick_group(self, x, y):
        return None

    def pick_edge(self, x, y):
        return self.pick if isinstance(self.pick, Edge) else None

    def pick_dimension(self, x, y):
        return None

    def pick_geopath(self, x, y):
        return None

    def pick_face(self, x, y):
        return self.pick if isinstance(self.pick, Face) else None

    def _world_to_pixel(self, v):
        return (v.x(), v.y())

    def update(self):
        pass


def _scene():
    s = Scene()
    s.edges.append(Edge(V(1, 1), V(2, 2)))
    s.edges.append(Edge(V(4, 4), V(10, 10)))
    s.faces.append(Face([V(1, 1), V(2, 1), V(2, 2), V(1, 2)]))
    return s


def _click(vp, entity, modifiers=Qt.NoModifier):
    vp.pick = entity
    SelectTool().on_click(ToolContext(
        viewport=vp, world=V(0, 0), screen=QPointF(0.0, 0.0),
        modifiers=modifiers, snap=None))


def test_the_modifiers_map_to_the_four_modes():
    assert selection_mode(Qt.NoModifier) == "replace"
    assert selection_mode(Qt.ShiftModifier) == "toggle"
    assert selection_mode(Qt.ControlModifier) == "add"
    assert selection_mode(Qt.ShiftModifier | Qt.ControlModifier) == "remove"


def test_shift_click_takes_a_selected_edge_out_and_puts_an_unselected_one_in():
    scene = _scene()
    vp = _StubViewport(scene)
    a, b = scene.edges[0], scene.edges[1]
    _click(vp, a)                                   # plain click: just a
    assert scene.selection == {a}
    _click(vp, b, Qt.ShiftModifier)                 # shift: b joins
    assert scene.selection == {a, b}
    _click(vp, a, Qt.ShiftModifier)                 # shift again: a leaves
    assert scene.selection == {b}


def test_ctrl_adds_and_shift_ctrl_removes():
    scene = _scene()
    vp = _StubViewport(scene)
    a, b = scene.edges[0], scene.edges[1]
    _click(vp, a)
    _click(vp, b, Qt.ControlModifier)
    assert scene.selection == {a, b}
    _click(vp, b, Qt.ControlModifier)               # Ctrl never takes away
    assert scene.selection == {a, b}
    _click(vp, b, Qt.ShiftModifier | Qt.ControlModifier)
    assert scene.selection == {a}
    _click(vp, b, Qt.ShiftModifier | Qt.ControlModifier)   # already out: no-op
    assert scene.selection == {a}


def test_a_plain_click_still_replaces_the_whole_selection():
    scene = _scene()
    vp = _StubViewport(scene)
    a, b = scene.edges[0], scene.edges[1]
    scene.select([a, b])
    _click(vp, a)
    assert scene.selection == {a}


def test_a_modified_click_on_empty_space_keeps_the_selection():
    scene = _scene()
    vp = _StubViewport(scene)
    a = scene.edges[0]
    scene.select([a])
    _click(vp, None, Qt.ShiftModifier)              # missed while carving
    assert scene.selection == {a}
    _click(vp, None, Qt.ControlModifier)
    assert scene.selection == {a}
    _click(vp, None)                                # a bare click does clear
    assert not scene.selection


def test_a_face_pick_takes_its_whole_surface_out():
    scene = _scene()
    vp = _StubViewport(scene)
    face = scene.faces[0]
    _click(vp, face)
    assert face in scene.selection
    _click(vp, face, Qt.ShiftModifier)
    assert face not in scene.selection


RECT = (0.0, 0.0, 5.0, 5.0)


def test_the_box_toggles_with_shift_and_removes_with_shift_ctrl():
    scene = _scene()
    vp = _StubViewport(scene)
    inside, outside = scene.edges[0], scene.edges[1]
    scene.select([inside, outside])
    SelectTool().on_box_select(vp, RECT, crossing=False, mode="toggle")
    assert inside not in scene.selection      # caught → dropped
    assert outside in scene.selection         # untouched by the box
    SelectTool().on_box_select(vp, RECT, crossing=False, mode="toggle")
    assert inside in scene.selection          # back in
    SelectTool().on_box_select(vp, RECT, crossing=False, mode="remove")
    assert inside not in scene.selection and outside in scene.selection


def test_scene_select_modes_are_explicit():
    scene = _scene()
    a, b = scene.edges[0], scene.edges[1]
    scene.select([a])
    scene.select([b], additive=True)            # the old spelling of "add"
    assert scene.selection == {a, b}
    scene.select([a], mode="remove")
    assert scene.selection == {b}
    scene.select([a, b], mode="toggle")
    assert scene.selection == {a}               # b was in, a was out
