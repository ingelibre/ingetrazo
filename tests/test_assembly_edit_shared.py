# SPDX-License-Identifier: GPL-3.0-or-later
"""Drawing inside an assembly: a component that holds other components.

Its own geometry is the definition its copies share, like a component with no
parts. What is drawn inside reaches every copy, each at its own place, and
undo takes it all back with the assembly's matrix where it was."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.edits import build_add_edge
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene

_app = QApplication.instance() or QApplication([])
Z = 9.0


def _box():
    m = Mesh()
    c = [V(x, y, z) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    for q in ([0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4],
              [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]):
        m.add_face([c[i] for i in q])
    return m


def _at(x, turn=0.0):
    m = QMatrix4x4()
    m.translate(x, 0, 0)
    m.rotate(turn, 0, 0, 1)
    return m


def _assembly(own_faces, turn=0.0):
    """Two copies of one definition, each holding a copy of one part."""
    part, mesh = _box(), _box() if own_faces else Mesh()
    copies = []
    for name, x in (("A", 10.0), ("B", 20.0)):
        kid = Group(part, name="part")
        kid.xform = QMatrix4x4()
        g = Group(mesh, name=name)
        g.adopt([kid])
        g.xform = _at(x, turn)
        copies.append(g)
    return copies


def _drawn(scene):
    """World x of what was drawn, by copy (the boxes stand below Z)."""
    seen = {}
    for g, m in scene.placements():
        for v in g.mesh.vertices:
            w = m.map(v.position) if m is not None else v.position
            if abs(w.z() - Z) < 0.5:
                seen.setdefault(g.name, set()).add(round(w.x(), 3))
    return seen


def _window(*groups):
    from views.main_window import MainWindow
    win = MainWindow()
    win.viewport.scene.groups.extend(groups)
    win.viewport.scene.version += 1
    return win, win.viewport, win.viewport.scene


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _draw(vp, a, b):
    vp.history.execute(build_add_edge(vp.scene, a, b, detect_faces=True))


@pytest.mark.parametrize("own_faces", [True, False])
def test_a_line_drawn_in_an_assembly_reaches_every_copy(own_faces):
    a, b = _assembly(own_faces)
    win, vp, scene = _window(a, b)
    try:
        vp.begin_group_edit(a)
        _draw(vp, V(10, 0, Z), V(11, 0, Z))
        vp.end_group_edit()
        assert _drawn(scene) == {"A": {10.0, 11.0}, "B": {20.0, 21.0}}
        assert a.mesh is b.mesh
        assert a.xform == _at(10.0) and b.xform == _at(20.0)
    finally:
        _close(win)


def test_a_turned_assembly_keeps_its_parts_where_they_are():
    a, b = _assembly(True, turn=90.0)
    win, vp, scene = _window(a, b)
    corners = sorted((round(p.x(), 3), round(p.y(), 3)) for g, m in
                     scene.placements() if g.name == "part"
                     for p in (m.map(v.position) for v in g.mesh.vertices))
    try:
        vp.begin_group_edit(a)
        _draw(vp, V(10, 0, Z), V(10, 1, Z))
        vp.end_group_edit()
        after = sorted((round(p.x(), 3), round(p.y(), 3)) for g, m in
                       scene.placements() if g.name == "part"
                       for p in (m.map(v.position) for v in g.mesh.vertices))
        assert after == corners
        assert a.mesh is b.mesh and a.xform == _at(10.0, 90.0)
    finally:
        _close(win)


@pytest.mark.parametrize("own_faces", [True, False])
def test_undo_and_redo_are_one_step_and_keep_the_copies_shared(own_faces):
    a, b = _assembly(own_faces)
    win, vp, scene = _window(a, b)
    steps = len(vp.history.undo_stack)
    try:
        vp.begin_group_edit(a)
        _draw(vp, V(10, 0, Z), V(11, 0, Z))
        vp.end_group_edit()
        assert len(vp.history.undo_stack) == steps + 1
        vp.history.undo()
        assert _drawn(scene) == {}
        assert a.mesh is b.mesh and a.xform == _at(10.0)
        assert a.children[0].xform == QMatrix4x4()
        vp.history.redo()
        assert _drawn(scene) == {"A": {10.0, 11.0}, "B": {20.0, 21.0}}
        assert a.xform == _at(10.0)
        assert a.children[0].xform == QMatrix4x4()
    finally:
        _close(win)


def test_opening_an_assembly_and_leaving_changes_nothing():
    a, b = _assembly(False)
    win, vp, _scene = _window(a, b)
    mesh = a.mesh
    steps = len(vp.history.undo_stack)
    try:
        vp.begin_group_edit(a)
        vp.end_group_edit()
        assert a.mesh is mesh and a.xform == _at(10.0) and a.axes is None
        assert a.children[0].xform == QMatrix4x4()
        assert len(vp.history.undo_stack) == steps
    finally:
        _close(win)


def test_a_shared_part_opened_inside_an_assembly_still_shares():
    a, b = _assembly(True)
    win, vp, scene = _window(a, b)
    try:
        vp.begin_group_edit(a)
        vp.begin_group_edit(a.children[0])
        _draw(vp, V(10, 0, Z), V(11, 0, Z))
        vp.end_group_edit()
        assert _drawn(scene)["part"] == {10.0, 11.0, 20.0, 21.0}
        assert a.xform == _at(10.0) and a.children[0].xform == QMatrix4x4()
        assert a.children[0].mesh is b.children[0].mesh
    finally:
        _close(win)


def test_a_part_and_its_assembly_edited_together_undo_as_one_step():
    a, b = _assembly(True)
    win, vp, scene = _window(a, b)
    steps = len(vp.history.undo_stack)
    try:
        vp.begin_group_edit(a)
        _draw(vp, V(10, 0, Z), V(11, 0, Z))
        vp.begin_group_edit(a.children[0])
        _draw(vp, V(12, 0, Z), V(13, 0, Z))
        vp.end_group_edit()
        full = {"A": {10.0, 11.0}, "B": {20.0, 21.0},
                "part": {12.0, 13.0, 22.0, 23.0}}
        assert _drawn(scene) == full
        assert len(vp.history.undo_stack) == steps + 1
        vp.history.undo()
        assert _drawn(scene) == {}
        assert a.xform == _at(10.0) and a.children[0].xform == QMatrix4x4()
        vp.history.redo()
        assert _drawn(scene) == full
        assert a.xform == _at(10.0) and a.children[0].xform == QMatrix4x4()
    finally:
        _close(win)


def test_a_copied_group_of_parts_is_made_unique_on_the_way_in():
    a, b = _assembly(True)
    a.component = b.component = False
    win, vp, scene = _window(a, b)
    try:
        vp.begin_group_edit(a)
        _draw(vp, V(10, 0, Z), V(11, 0, Z))
        vp.end_group_edit()
        assert _drawn(scene) == {"A": {10.0, 11.0}}
        assert a.mesh is not b.mesh
    finally:
        _close(win)


def test_an_assembly_placed_once_has_nothing_to_share_back():
    a, _b = _assembly(True)
    scene = Scene()
    scene.groups.append(a)
    scene.begin_group_edit(a)
    assert scene._edit_share is None
    scene.end_group_edit()


def test_a_plain_group_of_parts_keeps_baking_on_the_way_in():
    kid = Group(_box(), name="part")
    kid.xform = QMatrix4x4()
    g = Group(Mesh(), name="G")
    g.component = False
    g.adopt([kid])
    g.xform = _at(5.0, 90.0)
    scene = Scene()
    scene.groups.append(g)
    scene.begin_group_edit(g)
    assert scene._edit_share is None
    scene.end_group_edit()
    assert g.xform == QMatrix4x4()
