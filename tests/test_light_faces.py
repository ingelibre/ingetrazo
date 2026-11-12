# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Reading a face of a lazy mesh builds nothing (#1092): a hover over a big
group cost seconds and gigabytes because the snap's questions and Select's
«which object?» built the whole group. views.array_bake.LightFace answers
from the plan what the built face would, value for value; outside a hover's
read-only pass, a pick still gets the mesh's own face. Skipped without the
engine."""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QVector3D as V  # noqa: E402

import core._native as _native  # noqa: E402
from core import mesh as M  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats import igz  # noqa: E402
from tests.test_deferred_mesh import _meshes, _random_scene  # noqa: E402
from views import array_bake  # noqa: E402

_app = QApplication.instance() or QApplication([])
pytestmark = pytest.mark.skipif(
    _native.native is None or _native.qt_hypot() is None,
    reason="engine off or not built")


@pytest.fixture
def binary(monkeypatch):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)


def _opened(tmp_path, seed):
    rng = random.Random(seed)
    scene = _random_scene(rng)
    for m in _meshes(scene):
        for k, e in enumerate(m.edges):
            if k % 3 == 0:
                e.soft = True
            if k % 7 == 0:
                e.curve = 40 + k % 2
            if k % 11 == 0:
                e.hidden = True
    path = tmp_path / f"d{seed}.igz"
    igz.save_scene(scene, path)
    opened = Scene()
    igz.load_into(opened, path)
    return opened


def _xyz(p):
    return (p.x(), p.y(), p.z())


def _ring_sig(ring):
    out = []
    n = len(ring)
    for i, v in enumerate(ring):
        w = ring[(i + 1) % n]
        e = next((e for e in v.edges if e.other(v) is w), None)
        out.append((_xyz(v.position), None if e is None else (
            e.soft, e.hidden, e.curve, e.layer)))
    return out


def _sig(f):
    return (_ring_sig(f.loop), [_ring_sig(h) for h in f.hole_loops], f.attrs,
            f.interior, _xyz(f.normal()), _xyz(f.centroid()), f.area())


@pytest.mark.parametrize("seed", range(5))
def test_a_light_face_reads_as_the_built_face(binary, tmp_path, seed):
    from core.snap import curve_centers_of_face
    opened = _opened(tmp_path, seed)
    seen = 0
    for m in _meshes(opened):
        if type(m) is not M.DeferredMesh:
            continue
        n = M.face_count(m)
        light = [array_bake.light_face(m, i) for i in range(n)]
        assert type(m) is M.DeferredMesh, "reading builds nothing"
        assert light == [array_bake.light_face(m, i) for i in range(n)], \
            "the same object while it is lazy: identity tells faces apart"
        centers = [curve_centers_of_face(f) for f in light]
        tris = [[tuple(map(_xyz, t)) for t in f.triangulate()] for f in light]
        want = m.faces                   # built now
        assert type(m) is M.Mesh
        for a, b, c, t in zip(light, want, centers, tris):
            assert _sig(a) == _sig(b)
            assert a.real() is b
            assert [(_xyz(x), r, k) for x, r, k in c] == [
                (_xyz(x), r, k) for x, r, k in curve_centers_of_face(b)]
            assert t == [tuple(map(_xyz, q)) for q in b.triangulate()]
            seen += 1
    assert seen


def test_deferred_faces_answer_light_only_while_reading(binary, tmp_path):
    opened = _opened(tmp_path, 1)
    m = next(x for x in _meshes(opened) if type(x) is M.DeferredMesh)
    faces = array_bake.DeferredFaces(m, __import__("numpy").arange(
        M.face_count(m)))
    with array_bake.reading_only():
        f = faces[0]
        assert isinstance(f, array_bake.LightFace)
        assert type(m) is M.DeferredMesh
    real = faces[0]                     # no longer reading: builds, as always
    assert type(m) is M.Mesh and type(real) is M.Face
    with array_bake.reading_only():
        assert faces[0] is real, "once built, the real face"


def _window(tmp_path):
    from views.main_window import MainWindow
    from core.group import Group
    scene = Scene()
    m = M.Mesh()
    for i in range(30):                  # a floor of tiles, one group
        for j in range(30):
            m.add_face([V(i, j, 0), V(i + 1, j, 0), V(i + 1, j + 1, 0),
                        V(i, j + 1, 0)])
    scene.groups.append(Group(m, name="floor"))
    path = tmp_path / "floor.igz"
    igz.save_scene(scene, path)
    win = MainWindow()
    win.resize(900, 640)
    assert win.open_path(path) is not False
    vp = win.viewport
    vp.camera.set_view("top")
    vp.camera.fit_to(*vp.scene.bounds())
    return win, vp


def _hover(vp, x, y):
    vp._process_hover(QPointF(x, y), Qt.NoModifier)


@pytest.fixture
def big_enough(binary, monkeypatch):
    # The floor's mesh goes through the array bake whatever its size.
    monkeypatch.setattr(igz, "_BULK_MIN", 1)


def test_hovering_with_line_builds_no_mesh_and_a_click_gets_the_real_face(
        big_enough, tmp_path):
    win, vp = _window(tmp_path)
    try:
        mesh = vp.scene.groups[0].mesh
        assert type(mesh) is M.DeferredMesh
        win._activate_tool("line")
        x, y = vp.width() / 2 + 7, vp.height() / 2 + 3
        for k in (3, 2, 1, 0):           # the last one where the click comes
            _hover(vp, x + 13 * k, y)
        assert type(mesh) is M.DeferredMesh, "a Line hover built the group"
        assert vp.last_snap is not None
        face, group = vp.pick_face_any(x, y)
        assert type(face) is M.Face, "the memo of a hover's light face leaked"
        assert face in mesh.faces and group is vp.scene.groups[0]
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_hovering_with_select_builds_no_mesh(big_enough, tmp_path):
    win, vp = _window(tmp_path)
    try:
        mesh = vp.scene.groups[0].mesh
        win._activate_tool("select")
        x, y = vp.width() / 2 + 7, vp.height() / 2 + 3
        assert vp.pick_group(x, y) is vp.scene.groups[0]
        _hover(vp, x, y)
        assert type(mesh) is M.DeferredMesh, "«which object?» built the group"
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_a_centre_found_on_a_light_face_survives_an_edit(big_enough, tmp_path):
    """_valid_center_ref re-checks its source against the mesh's own faces:
    a light face is not one of them, and the centre would go at any edit."""
    from core.mesh import Mesh
    from core.group import Group
    from views.main_window import MainWindow
    import math
    scene = Scene()
    m = Mesh()
    ring = [V(math.cos(i * math.pi / 12), math.sin(i * math.pi / 12), 0)
            for i in range(24)]
    for i in range(3):                   # enough for the array bake
        m.add_face([p + V(4 * i, 0, 0) for p in ring])
    scene.groups.append(Group(m, name="discs"))
    path = tmp_path / "discs.igz"
    igz.save_scene(scene, path)
    win = MainWindow()
    try:
        assert win.open_path(path) is not False
        vp = win.viewport
        mesh = vp.scene.groups[0].mesh
        assert type(mesh) is M.DeferredMesh
        light = array_bake.light_face(mesh, 0)
        found = vp._center_of_face(light, vp.scene.groups[0], mesh, 0.0, 0.0)
        assert found is not None
        assert type(mesh) is M.DeferredMesh
        vp._center_ref = found
        vp.scene.version += 1
        fresh = vp._valid_center_ref()
        assert fresh is not None, "the centre went with the edit"
        assert (fresh[0].x(), fresh[0].y()) == (found[0].x(), found[0].y())
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def _click(vp, x, y):
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y),
                        vp.mapToGlobal(QPointF(x, y)), Qt.LeftButton,
                        Qt.LeftButton, Qt.NoModifier)
    vp._dispatch_tool_click(press)


def test_a_click_with_line_builds_nothing_and_takes_the_same_plane(
        big_enough, tmp_path):
    from core.snap import face_plane_world
    win, vp = _window(tmp_path)
    try:
        mesh = vp.scene.groups[0].mesh
        tool = win._activate_tool("line") or vp.active_tool
        x, y = vp.width() / 2 + 7, vp.height() / 2 + 3
        _hover(vp, x, y)
        _click(vp, x, y)
        assert tool.start_point is not None and tool.work_plane is not None
        assert type(mesh) is M.DeferredMesh, "the first click built the group"
        got = tool.work_plane
        _hover(vp, x + 40, y)
        _click(vp, x + 40, y + 11)
        assert type(mesh) is M.DeferredMesh, "the second click built the group"
        assert len(vp.scene.mesh.edges) == 1, "no edge drawn"
        # The face that click would otherwise have built: the very same plane.
        real, placed = vp.pick_face_placement(x, y)
        assert type(real) is not array_bake.LightFace
        want = face_plane_world(real, getattr(placed, "xform", None))
        assert _xyz(got[0]) == _xyz(want[0]) and _xyz(got[1]) == _xyz(want[1])
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
