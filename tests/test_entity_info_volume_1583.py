# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Entity Info's volume is worked out once per shape, a big one in slices
between events (#1583), and what it shows is never of an earlier shape."""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core import solids
from core.group import Group, copy_group
from core.history import (DeleteFaceCommand, FlipFacesCommand,
                          MoveVerticesCommand, ScaleGroupCommand)
from tests.test_light_faces import big_enough, binary
from core.mesh import Mesh, turn_face_over


__all__ = ["big_enough", "binary"]


def _box(mesh, w=2.0, d=3.0, h=4.0, x=0.0, hole=False):
    a, b, c, e = V(x, 0, 0), V(x + w, 0, 0), V(x + w, d, 0), V(x, d, 0)
    up = V(0, 0, h)
    inner = [V(x + .5, .5, 0), V(x + 1.5, .5, 0), V(x + 1.5, 2, 0), V(x + .5, 2, 0)]
    mesh.add_face([e, c, b, a], [inner] if hole else None)
    for p, q in ((a, b), (b, c), (c, e), (e, a)):
        mesh.add_face([p, q, q + up, p + up])
    mesh.add_face([a + up, b + up, c + up, e + up],
                  [[p + up for p in inner]] if hole else None)
    if hole:
        for k in range(4):
            p, q = inner[k], inner[(k + 1) % 4]
            mesh.add_face([q, p, p + up, q + up])
    return mesh


@pytest.fixture(params=[False, True], ids=["at once", "in slices"])
def panel(request, monkeypatch):
    from views.main_window import MainWindow
    if request.param:
        monkeypatch.setattr(solids, "SLICED_FROM", 1)
    win = MainWindow()
    yield win.tray.entity_info, win.viewport
    win._saved_version = win.viewport.scene.version
    win.close()


def _shown(info, group):
    """The settled volume the panel shows, checked against a fresh one."""
    end = time.monotonic() + 10
    info.refresh()
    while info._solid_volume(group) is info.PENDING:
        assert time.monotonic() < end
        assert "…" in info._label.text()
        QCoreApplication.processEvents()
    got, fresh = info._solid_volume(group), solids.solid_volume(group)
    assert (got is None) == (fresh is None)
    if got is not None:
        assert got == pytest.approx(fresh, rel=1e-5)
        from core.units import fmt_volume
        assert fmt_volume(got) in info._label.text()
    assert "…" not in info._label.text()
    return got


def _add(vp, group):
    scene = vp.scene
    scene.groups.append(group)
    _select(scene, group)
    return group


def _select(scene, group):
    scene.selection.clear()
    scene.selection.add(group)
    scene.version += 1


def _placed(mesh, x=5.0):
    g = Group(mesh)
    g.xform = QMatrix4x4()
    g.xform.translate(x, 0, 0)
    return g


@pytest.mark.parametrize("place", [False, True])
@pytest.mark.parametrize("hole, volume", [(False, 24.0), (True, 18.0)])
def test_edits_undo_and_flips(panel, place, hole, volume):
    info, vp = panel
    scene, history = vp.scene, vp.history
    mesh = _box(Mesh(), hole=hole)
    g = _add(vp, _placed(mesh) if place else Group(mesh))
    assert _shown(info, g) == pytest.approx(volume)

    vp.begin_group_edit(g)
    mesh = scene.mesh
    top = [v.position for v in mesh.vertices if v.position.z() > 3]
    history.execute(MoveVerticesCommand(top, V(0, 0, 1)))
    _select(scene, g)
    assert _shown(info, g) == pytest.approx(volume * 1.25)
    history.undo()
    _select(scene, g)
    assert _shown(info, g) == pytest.approx(volume)
    history.redo()
    _select(scene, g)
    assert _shown(info, g) == pytest.approx(volume * 1.25)
    history.execute(FlipFacesCommand([mesh.faces[-1]]))
    _select(scene, g)
    assert _shown(info, g) != pytest.approx(volume * 1.25)
    history.undo()
    _select(scene, g)
    assert _shown(info, g) == pytest.approx(volume * 1.25)
    history.execute(DeleteFaceCommand(mesh.faces[1]))
    _select(scene, g)
    assert _shown(info, g) is None
    history.undo()
    _select(scene, g)
    assert _shown(info, g) == pytest.approx(volume * 1.25)


@pytest.mark.parametrize("change", ["turned over", "partition"])
def test_a_change_that_bumps_no_serial(panel, change):
    info, vp = panel
    g = _add(vp, Group(_box(Mesh())))
    _shown(info, g)
    serial = g.mesh._mut_serial
    if change == "turned over":
        turn_face_over(g.mesh.faces[-1])
    else:
        g.mesh.faces[0].interior = True
    vp.scene.version += 1
    assert g.mesh._mut_serial == serial
    assert _shown(info, g) != pytest.approx(24.0)


@pytest.mark.parametrize("place", [False, True])
def test_scaling(panel, place):
    info, vp = panel
    mesh = _box(Mesh())
    g = _add(vp, _placed(mesh) if place else Group(mesh))
    assert _shown(info, g) == pytest.approx(24.0)
    vp.history.execute(ScaleGroupCommand(g, V(0, 0, 0), 2.0))
    assert _shown(info, g) == pytest.approx(192.0)
    vp.history.undo()
    assert _shown(info, g) == pytest.approx(24.0)


def test_a_shared_component(panel):
    info, vp = panel
    mesh = _box(Mesh())
    a, b = _add(vp, _placed(mesh)), _add(vp, _placed(mesh, 20))
    twice = _add(vp, _placed(mesh, 40))
    twice.xform.scale(1, 1, 2)
    assert _shown(info, twice) == pytest.approx(48.0)
    _select(vp.scene, b)
    assert _shown(info, b) == pytest.approx(24.0)
    vp.begin_group_edit(a)
    top = [v.position for v in vp.scene.mesh.vertices if v.position.z() > 3]
    vp.history.execute(MoveVerticesCommand(top, V(0, 0, 4)))
    vp.end_group_edit()
    _select(vp.scene, b)
    assert _shown(info, b) == pytest.approx(48.0)
    _select(vp.scene, twice)
    assert _shown(info, twice) == pytest.approx(96.0)


def test_nested_pieces(panel):
    info, vp = panel
    outer = Group(_box(Mesh()))
    child = _placed(_box(Mesh(), h=1), 10)
    _add(vp, outer)
    assert _shown(info, outer) == pytest.approx(24.0)
    outer.children = [child]
    vp.scene.version += 1
    assert _shown(info, outer) is None            # nested: no solid
    vp.begin_group_edit(outer)
    _select(vp.scene, child)
    assert _shown(info, child) == pytest.approx(6.0)
    vp.begin_group_edit(child)
    top = [v.position for v in vp.scene.mesh.vertices if v.position.z() > .5]
    vp.history.execute(MoveVerticesCommand(top, V(0, 0, 1)))
    vp.end_group_edit()
    _select(vp.scene, child)
    assert _shown(info, child) == pytest.approx(12.0)
    outer.children = None
    _select(vp.scene, outer)
    assert _shown(info, outer) == pytest.approx(24.0)


def test_another_mesh_in_the_group(panel):
    info, vp = panel
    g = _add(vp, Group(_box(Mesh())))
    assert _shown(info, g) == pytest.approx(24.0)
    g.mesh = _box(Mesh(), h=1)
    vp.scene.version += 1
    assert _shown(info, g) == pytest.approx(6.0)


def test_a_copy_selected_half_way(panel):
    info, vp = panel
    g = _add(vp, _placed(_box(Mesh())))
    info.refresh()
    other = copy_group(g)
    _add(vp, other)
    assert _shown(info, other) == pytest.approx(24.0)


def test_an_edit_half_way_starts_again(panel):
    info, vp = panel
    g = _add(vp, Group(_box(Mesh())))
    info.refresh()
    for v in list(g.mesh.vertices):
        if v.position.z() > 3:
            g.mesh.place_vertex(v, v.position + V(0, 0, 4))
    QCoreApplication.processEvents()              # no refresh in between
    assert _shown(info, g) == pytest.approx(48.0)


def test_the_same_shape_is_measured_once(panel, monkeypatch):
    info, vp = panel
    calls = []
    for name in ("solid_volume", "volume_steps"):
        real = getattr(solids, name)
        monkeypatch.setattr(solids, name, lambda g, real=real:
                            calls.append(1) or real(g))
    g = _add(vp, _placed(_box(Mesh())))
    end = time.monotonic() + 10
    for k in range(5):
        m = QMatrix4x4(g.xform)
        m.translate(1, 0, 0)
        g.xform = m                               # a move keeps the volume
        vp.scene.version += 1
        info.refresh()
        while info._solid_volume(g) is info.PENDING:
            assert time.monotonic() < end
            QCoreApplication.processEvents()
    assert len(calls) == 1


def _steps(g):
    it = solids.volume_steps(g)
    while True:
        try:
            next(it)
        except StopIteration as done:
            return done.value


@pytest.mark.parametrize("closed", [True, False])
@pytest.mark.parametrize("place", [False, True])
def test_slices_agree_with_the_walk_lazy_or_built(tmp_path, big_enough,
                                                  closed, place):
    from core.mesh import DeferredMesh
    from core.scene import Scene
    from formats import igz
    mesh = _box(_box(Mesh()), x=10, hole=True)
    if not closed:
        mesh.remove_face(mesh.faces[-1])
    scene = Scene()
    g = _placed(mesh) if place else Group(mesh)
    scene.groups.append(g)
    expected = solids.solid_volume(g)
    assert (expected is not None) is closed
    igz.save_scene(scene, tmp_path / "a.igz")
    back = Scene()
    igz.load_into(back, tmp_path / "a.igz")
    read = back.groups[0]
    lazy = type(read.mesh) is DeferredMesh
    for _ in range(2):
        got = _steps(read)
        assert got == (None if expected is None
                       else pytest.approx(expected, rel=1e-6))
        assert (type(read.mesh) is DeferredMesh) == lazy
        read.mesh.faces
        lazy = False


def test_a_lazy_group_is_measured_unbuilt(panel, tmp_path, request):
    import core._native as _native
    from core.mesh import DeferredMesh
    if _native.native is None:
        pytest.skip("engine off")
    if solids.SLICED_FROM != 1:
        pytest.skip("only big groups")
    request.getfixturevalue("big_enough")
    from tests.test_tools_keep_lazy import _boxed_scene
    info, vp = panel
    g = _add(vp, _boxed_scene(tmp_path, True, True))
    assert type(g.mesh) is DeferredMesh
    end = time.monotonic() + 10
    info.refresh()
    while info._solid_volume(g) is info.PENDING:
        assert time.monotonic() < end
        QCoreApplication.processEvents()
    assert info._solid_volume(g) == pytest.approx(24.0)
    assert type(g.mesh) is DeferredMesh, "the panel built the group"
    g.mesh.faces
    vp.scene.version += 1
    assert _shown(info, g) == pytest.approx(24.0)
