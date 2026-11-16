# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Every copy of a component follows what is done inside one of them —
not only the geometry of its parts, also WHERE its parts are and WHICH parts
it has (#1339, #894, #508, #1328).

A component's definition used to be its mesh alone: each copy kept its own
list of nested groups, each with its own matrix. Editing the geometry of a
part reached every copy (the part's mesh is shared, #97), but moving,
scaling or rotating a part, adding one (a copy, a paste) or taking one out
stayed in the copy that was open. And opening a moved copy that holds
groups pushed its matrix down into its parts for good, so the loose faces
drawn inside it went into the shared mesh in the wrong frame."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group, copy_group, iter_placements
from core.history import (AddFaceCommand, InsertGroupCommand,
                          MakeComponentOfCommand, MoveGroupCommand,
                          RotateGroupCommand, ScaleGroupCommand)
from core.mesh import Mesh


def _app():
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication(sys.argv[:1])


@pytest.fixture
def win():
    _app()
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _square(x, y=0.0, name=None):
    m = Mesh()
    m.add_face([V(x, y, 0), V(x + 1, y, 0), V(x + 1, y + 1, 0),
                V(x, y + 1, 0)])
    return Group(m, name=name) if name else m


def _bench(vp, offset=V(0, 5, 0)):
    """Two groups → Make Component → a copy moved by ``offset``."""
    scene = vp.scene
    a, b = _square(0, name="A"), _square(3, name="B")
    scene.groups.extend([a, b])
    vp.history.execute(MakeComponentOfCommand([], [], [a, b], name="Banca"))
    comp = scene.groups[-1]
    dup = copy_group(comp, offset)
    scene.groups.append(dup)
    return comp, dup


def _local(group):
    """The component's geometry in its OWN frame, as rounded points: what
    every copy of one definition must agree on."""
    inv = (group.xform.inverted()[0] if group.xform is not None
           else QMatrix4x4())
    out = set()
    for pg, m in iter_placements(group):
        for f in pg.mesh.faces:
            for p in f.vertices:
                w = m.map(p) if m is not None else p
                q = inv.map(w)
                out.add((round(q.x(), 4), round(q.y(), 4), round(q.z(), 4)))
    return sorted(out)


def _leave(vp):
    while vp.scene.edit_group is not None:
        vp.escape()


def test_moving_a_group_inside_one_copy_moves_it_in_every_copy(win):
    """#1339 / #894: «changes to the position or size of a group within a
    component are not reflected in the component's duplicates»."""
    vp = win.viewport
    comp, dup = _bench(vp)
    vp.begin_group_edit(dup)
    vp.history.execute(MoveGroupCommand(dup.children[0], V(0, 0, 2)))
    _leave(vp)
    assert _local(comp) == _local(dup)
    assert any(p[2] == 2.0 for p in _local(comp))
    assert dup.mesh is comp.mesh                 # still copies of ONE thing


def test_scaling_a_group_inside_one_copy_scales_it_in_every_copy(win):
    vp = win.viewport
    comp, dup = _bench(vp)
    vp.begin_group_edit(dup)
    child = dup.children[1]
    vp.history.execute(ScaleGroupCommand(child, V(3, 5, 0), 2.0))
    _leave(vp)
    assert _local(comp) == _local(dup)
    assert (5.0, 2.0, 0.0) in _local(comp)


def test_the_edit_of_a_moved_copy_undoes_in_one_step(win):
    vp = win.viewport
    comp, dup = _bench(vp)
    before = _local(comp)
    vp.begin_group_edit(dup)
    vp.history.execute(MoveGroupCommand(dup.children[0], V(0, 0, 2)))
    vp.history.execute(MoveGroupCommand(dup.children[1], V(1, 0, 0)))
    _leave(vp)
    assert vp.history.undo() is True
    assert _local(comp) == before == _local(dup)
    assert vp.history.redo() is True
    assert _local(comp) == _local(dup) != before


def test_loose_faces_drawn_in_a_moved_copy_land_in_every_copy(win):
    """#894: the loose geometry of a component that holds groups. Opening
    the copy at y = 5 pushed its matrix into its groups and left the shared
    mesh in two frames at once."""
    vp = win.viewport
    comp, dup = _bench(vp)
    vp.begin_group_edit(dup)
    vp.history.execute(AddFaceCommand(
        [V(10, 5, 0), V(11, 5, 0), V(11, 6, 0), V(10, 6, 0)]))
    _leave(vp)
    assert _local(comp) == _local(dup)
    assert (10.0, 0.0, 0.0) in _local(comp)      # in the definition's frame
    t = QMatrix4x4()
    t.translate(0, 5, 0)
    assert dup.xform == t                        # the copy kept its place


def test_a_group_copied_inside_a_copy_appears_in_every_copy(win):
    """#508: component #1 holds two copies of component #2; inside a copy
    of #1, duplicating one #2 and rotating it must reach the other #1."""
    vp = win.viewport
    scene = vp.scene
    inner = _square(0, name="Leg")
    scene.groups.append(inner)
    from core.history import GroupToComponentCommand
    vp.history.execute(GroupToComponentCommand(inner))
    inner2 = copy_group(inner, V(3, 0, 0))
    scene.groups.append(inner2)
    vp.history.execute(MakeComponentOfCommand([], [], [inner, inner2],
                                              name="Table"))
    outer = scene.groups[-1]
    outer2 = copy_group(outer, V(0, 8, 0))
    scene.groups.append(outer2)
    vp.begin_group_edit(outer2)
    extra = copy_group(outer2.children[0], V(0, 2, 0))
    vp.history.execute(InsertGroupCommand(extra))
    vp.history.execute(RotateGroupCommand(extra, V(0, 10, 0), V(0, 0, 1),
                                          90.0))
    _leave(vp)
    assert len(outer.children) == 3
    assert _local(outer) == _local(outer2)
    assert all(c.mesh is inner.mesh for c in outer.children)


def test_the_sharing_survives_the_igz_after_an_edit(win, tmp_path):
    from core.scene import Scene
    from formats import igz
    vp = win.viewport
    comp, dup = _bench(vp)
    vp.begin_group_edit(dup)
    vp.history.execute(MoveGroupCommand(dup.children[0], V(0, 0, 2)))
    _leave(vp)
    path = tmp_path / "banca.igz"
    igz.save_scene(vp.scene, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    c1, c2 = loaded.groups[-2:]
    assert _local(c1) == _local(c2)
    assert all(x.mesh is y.mesh for x, y in zip(c1.children, c2.children))


def test_headless_leave_shares_the_parts_too():
    """The scene alone (tests, the AI bridge) shares back on leaving."""
    _app()
    from core.history import History
    from core.scene import Scene
    scene = Scene()
    hist = History(scene)
    a, b = _square(0, name="A"), _square(3, name="B")
    scene.groups.extend([a, b])
    hist.execute(MakeComponentOfCommand([], [], [a, b], name="Banca"))
    comp = scene.groups[0]
    dup = copy_group(comp, V(0, 5, 0))
    scene.groups.append(dup)
    scene.begin_group_edit(dup)
    MoveGroupCommand(dup.children[0], V(0, 0, 2)).do(scene)
    scene.end_group_edit()
    assert _local(comp) == _local(dup)


def test_untouched_copies_keep_their_parts_as_they_were(win):
    """Opening and leaving without changing anything rebuilds nothing:
    the other copy keeps its very part objects (ids the draw caches and
    the scenes' hidden lists hold)."""
    vp = win.viewport
    comp, dup = _bench(vp, offset=V(1234.567, 89.1, 0))
    t = QMatrix4x4()
    t.rotate(33.3, 0, 0, 1)
    dup.xform = dup.xform * t                    # an awkward placement
    for c in dup.children:
        lean = QMatrix4x4()
        lean.translate(0.3, 0.7, 0.1)
        lean.rotate(17, 0, 1, 0)
        c.xform = lean * c.xform
    kids = list(comp.children)
    xforms = [list(c.xform.data()) for c in dup.children]
    vp.begin_group_edit(dup)
    _leave(vp)
    assert comp.children == kids
    assert [list(c.xform.data()) for c in dup.children] == xforms   # bit-exact


def test_two_levels_deep_the_whole_edit_is_one_undo_step(win):
    """Inside a copy, open one of its groups and raise its face, step up,
    move the other group before and after, leave: every copy follows, and one undo takes the
    whole session back in every copy."""
    vp = win.viewport
    comp, dup = _bench(vp)
    before = _local(comp)
    vp.begin_group_edit(dup)
    vp.history.execute(MoveGroupCommand(dup.children[1], V(0, 0, 1)))
    child = dup.children[0]
    vp.begin_group_edit(child)
    for v in {id(v): v for f in child.mesh.faces for v in f.loop}.values():
        v.position = v.position + V(0, 0, 0.5)
    vp.scene.version += 1
    vp.escape()                                  # up to the copy
    assert vp.scene.edit_group is dup
    vp.history.execute(MoveGroupCommand(dup.children[1], V(0, 0, 2)))
    _leave(vp)
    assert _local(comp) == _local(dup)
    assert {p[2] for p in _local(comp)} == {0.5, 3.0}
    assert vp.history.undo() is True
    assert _local(comp) == _local(dup) == before
    assert vp.history.redo() is True
    assert {p[2] for p in _local(comp)} == {0.5, 3.0}
    assert _local(comp) == _local(dup)


def test_a_group_pasted_into_a_plain_component_reaches_its_copies(win):
    """A component with no groups yet: what is pasted in while one copy is
    open is a part of the definition, placed in its frame — it used to
    stay in that copy, and land moved by the copy's matrix a second time."""
    vp = win.viewport
    scene = vp.scene
    g = _square(0, name="Box")
    scene.groups.append(g)
    from core.history import GroupToComponentCommand
    vp.history.execute(GroupToComponentCommand(g))
    dup = copy_group(g, V(0, 5, 0))
    scene.groups.append(dup)
    vp.begin_group_edit(dup)
    vp.history.execute(InsertGroupCommand(_square(0, 7, name="Lid")))
    _leave(vp)
    assert len(g.children) == 1 and len(dup.children) == 1
    assert _local(g) == _local(dup)
    assert (0.0, 2.0, 0.0) in _local(dup)        # y 7 in the world, 2 inside
    assert g.is_component() and dup.is_component()


@pytest.mark.xfail(strict=True, reason="#930: the other copies follow when "
                   "the edit is left, not live while it happens")
def test_the_other_copies_follow_live_while_editing(win):
    vp = win.viewport
    comp, dup = _bench(vp)
    vp.begin_group_edit(dup)
    vp.history.execute(MoveGroupCommand(dup.children[0], V(0, 0, 2)))
    try:
        assert any(p[2] == 2.0 for p in _local(comp))
    finally:
        _leave(vp)
