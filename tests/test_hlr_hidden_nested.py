# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""``collect_geometry`` leaves out the nested placements the viewport does
not draw.

It only asked ``entity_visible`` of the groups in ``scene.groups``, then
``world_mesh`` folded in every child: a group hidden one level down (Edit ▸
Hide on it, or its tag turned off) was gone from the viewport and from
``Viewport.hlr_geometry``, but drew in a sheet whenever the hidden-line
pass collected the geometry itself (``hlr_drawing`` / ``hlr_perspective``
without ``geometry``, the composer without a viewport, extensions). A face
hidden inside a group drew there the same way.
"""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from core.group import Group
from core.history import HideCommand, History
from core.hlr import collect_circles, collect_geometry
from core.layers import Layer
from core.mesh import Mesh
from core.scene import Scene


def _box(x0: float, name: str) -> Group:
    m = Mesh()
    b = [V(x0, 0, 0), V(x0 + 2, 0, 0), V(x0 + 2, 2, 0), V(x0, 2, 0)]
    t = [V(p.x(), p.y(), 3) for p in b]
    m.add_face(list(reversed(b)))
    m.add_face(t)
    for i in range(4):
        m.add_face([b[i], b[(i + 1) % 4], t[(i + 1) % 4], t[i]])
    return Group(m, name)


BOX = 12                                    # triangles in one box


def _nest(parent: Group, child: Group) -> Group:
    parent.children.append(child)
    child.owner = parent
    return child


def _tris(scene) -> int:
    return len(collect_geometry(scene)[0])


def _scene_with_child():
    scene = Scene()
    history = History(scene)
    top = _box(0, "top")
    child = _nest(top, _box(5, "child"))
    scene.groups.append(top)
    return scene, history, top, child


def test_a_hidden_child_is_left_out_and_undo_brings_it_back():
    scene, history, _top, child = _scene_with_child()
    assert _tris(scene) == 2 * BOX
    history.execute(HideCommand([child], hidden=True))
    assert _tris(scene) == BOX
    history.undo()
    assert _tris(scene) == 2 * BOX


def test_a_hidden_middle_group_takes_its_subtree_along():
    scene, history, _top, child = _scene_with_child()
    _nest(child, _box(10, "grandchild"))
    assert _tris(scene) == 3 * BOX
    history.execute(HideCommand([child], hidden=True))
    assert _tris(scene) == BOX


def test_a_child_on_a_hidden_tag_is_left_out():
    scene, _history, _top, child = _scene_with_child()
    scene.layers.append(Layer("furniture", visible=False))
    child.layer = "furniture"
    assert _tris(scene) == BOX


def test_an_untagged_grandchild_follows_its_parents_hidden_tag():
    scene, _history, _top, child = _scene_with_child()
    _nest(child, _box(10, "grandchild"))
    scene.layers.append(Layer("furniture", visible=False))
    child.layer = "furniture"
    assert _tris(scene) == BOX


def test_a_tagged_grandchild_under_a_hidden_tag_stays_hidden():
    """A hidden tag above puts the whole instance on it, whatever its
    children are tagged: the viewport's rule."""
    scene, _history, _top, child = _scene_with_child()
    grandchild = _nest(child, _box(10, "grandchild"))
    scene.layers.append(Layer("furniture", visible=False))
    scene.layers.append(Layer("detail", visible=True))
    child.layer = "furniture"
    grandchild.layer = "detail"
    assert _tris(scene) == BOX


def test_nothing_hidden_keeps_every_placement_through_its_transform():
    scene, _history, top, child = _scene_with_child()
    xf = QMatrix4x4()
    xf.translate(0, 0, 10)
    child.xform = xf
    tris = collect_geometry(scene)[0]
    assert len(tris) == 2 * BOX
    assert max(p[2] for t in tris for p in t) == pytest.approx(13.0)
    from core.group import visible_placements
    assert [g for g, _m in visible_placements(scene, top)] == [top, child]


def test_a_hidden_childs_circles_are_not_offered():
    scene = Scene()
    history = History(scene)
    top = Group(Mesh(), "top")
    ring = Mesh()
    ring.add_face([V(math.cos(a), math.sin(a), 0)
                   for a in (2 * math.pi * i / 24 for i in range(24))])
    child = _nest(top, Group(ring, "disc"))
    scene.groups.append(top)
    assert collect_circles(scene)
    history.execute(HideCommand([child], hidden=True))
    assert collect_circles(scene) == []


def test_a_face_hidden_inside_a_group_is_left_out():
    scene, history, top, child = _scene_with_child()
    history.execute(HideCommand([top.mesh.faces[0]], hidden=True))
    assert _tris(scene) == 2 * BOX - 2
    xf = QMatrix4x4()
    xf.translate(0, 0, 10)
    child.xform = xf                        # through a nested placement too
    history.execute(HideCommand([child.mesh.faces[0]], hidden=True))
    assert _tris(scene) == 2 * BOX - 4


def test_collect_geometry_agrees_with_the_viewport():
    """The two ways a sheet gets the model see the same thing."""
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(800, 600)
    win.show()
    _app.processEvents()
    try:
        vp = win.viewport
        top = _box(0, "top")
        child = _nest(top, _box(5, "child"))
        vp.scene.groups.append(top)
        vp.notify_scene_changed()
        _app.processEvents()

        def both():
            return len(vp.hlr_geometry()[0]), _tris(vp.scene)

        assert both() == (2 * BOX, 2 * BOX)
        vp.history.execute(HideCommand([child], hidden=True))
        _app.processEvents()
        assert both() == (BOX, BOX)
        vp.history.undo()
        _app.processEvents()
        assert both() == (2 * BOX, 2 * BOX)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
