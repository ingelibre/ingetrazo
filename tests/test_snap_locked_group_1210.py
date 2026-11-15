# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Locking a group protects edits without removing its inference points (#1210)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group
from core.history import History, LockCommand
from core.mesh import Mesh
from tools.line import LineTool
from views.viewport import Viewport


@pytest.fixture(params=["group", "component", "nested", "lazy", "native_lazy"])
def box(request):
    vp = Viewport(None)
    vp.flash_status = lambda *args, **kwargs: None
    vp.resize(900, 600)
    vp.camera.set_aspect(900, 600)
    vp.camera.target = V(0.5, 0.5, 0.5)
    vp.camera.distance = 5.0
    vp.active_tool = LineTool()
    mesh = Mesh()
    p = [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0),
         V(0, 0, 1), V(1, 0, 1), V(1, 1, 1), V(0, 1, 1)]
    for ids in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([p[i] for i in ids])
    group = Group(mesh, "box")
    if request.param != "group":
        group.xform = QMatrix4x4()
        group.xform.translate(2, 3, 1)
        group.xform.rotate(25, 0, 0, 1)
    transform = QMatrix4x4(group.xform) if group.xform is not None else QMatrix4x4()
    if request.param == "nested":
        parent = Group(Mesh(), "parent")
        parent.xform = QMatrix4x4()
        parent.xform.translate(-1, 2, 0)
        parent.children = [group]
        transform = parent.xform * transform
        group = parent
    if request.param == "native_lazy":
        from core._native import native
        if native is None or not hasattr(native, "InstanceSet"):
            vp.close()
            pytest.skip("native module not built")
    vp._PICK_LAZY_MIN_FACES = 1 if "lazy" in request.param else 10 ** 9
    vp.camera.target = transform.map(V(0.5, 0.5, 0.5))
    vp.scene.groups.append(group)
    vp.scene.version += 1
    yield vp, group, transform
    vp.close()


@pytest.mark.parametrize("point, kind", [
    ((1, 0, 1), "endpoint"),
    ((0.5, 0, 1), "midpoint"),
    ((0.25, 0, 1), "on_edge"),
])
def test_lock_keeps_the_same_snap_and_undo_redo_keeps_it(box, point, kind):
    vp, group, transform = box
    target = transform.map(V(*point))
    px = vp._world_to_pixel(target)
    history = History(vp.scene)

    def check():
        snap = vp._snap_at(*px, Qt.NoModifier)
        assert snap.kind == kind
        assert (snap.point - target).length() < 1e-5

    check()  # Build the caches before the lock changes.
    history.execute(LockCommand([group], True))
    check()
    assert vp.pick_group(*px) is None
    assert not vp.scene.entity_selectable(group)
    vp.begin_group_edit(group)
    assert vp.scene.edit_group is None
    history.undo()
    check()
    history.redo()
    check()


def test_hidden_locked_group_does_not_offer_edges(box):
    vp, group, transform = box
    group.locked = True
    vp.scene.version += 1
    px = vp._world_to_pixel(transform.map(V(1, 0, 1)))
    assert vp._nearby_group_edges(*px)
    group.hidden = True
    vp.scene.version += 1
    assert vp._nearby_group_edges(*px) == []


def test_a_locked_layer_keeps_its_existing_snap_policy(box):
    from core.layers import Layer
    vp, group, transform = box
    vp.scene.layers.append(Layer("reference", locked=True))
    group.layer = "reference"
    group.locked = True
    vp.scene.version += 1
    px = vp._world_to_pixel(transform.map(V(1, 0, 1)))
    assert vp._nearby_group_edges(*px) == []


def test_native_candidates_keep_locked_references_out_of_editable_picks(monkeypatch):
    """Exercise the native masks even on CI without the compiled engine."""
    from types import SimpleNamespace
    from core.layers import Layer
    from core.scene import Scene
    from views import viewport as viewport_module

    scene = Scene()
    groups = [Group(Mesh(), name) for name in
              ("editable", "locked", "hidden", "locked layer", "outside context")]
    groups[1].locked = True
    groups[2].hidden = True
    groups[3].layer = "reference"
    scene.layers.append(Layer("reference", locked=True))
    table = (groups,)
    iset = SimpleNamespace(corners_near=lambda: None)
    key = (1, id(scene.edit_group), False, id(table))
    candidates = (key, {id(g) for g in groups[:4]}, [],
                  {id(g): (i, g) for i, g in enumerate(groups)})
    stub = SimpleNamespace(
        scene=scene, _pick_lazy_table=lambda: table,
        _pick_instance_set=lambda _: iset, _placements_epoch=lambda: 1,
        _pick_cands_memo=candidates,
    )
    monkeypatch.setattr(viewport_module, "_LAZY_NATIVE", True)
    native = Viewport._lazy_native(stub)
    assert native[1].tolist() == [0, 1, 4]
    assert native[2].tolist() == [0, 1, 3, 4]
    assert Viewport._lazy_sel_rows(stub, native).tolist() == [0]


def test_locked_billboard_keeps_its_feet_reference():
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    try:
        figure = next(g for g in vp.scene.groups if g.billboard)
        before = vp._billboard_snap_edges()
        assert len(before) == 1
        figure.locked = True
        vp.scene.version += 1
        after = vp._billboard_snap_edges()
        assert len(after) == 1
        assert after[0].a == before[0].a
        figure.hidden = True
        vp.scene.version += 1
        assert vp._billboard_snap_edges() == []
    finally:
        win._saved_version = vp.scene.version
        win.close()
