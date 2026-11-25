# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The tools on a big lazy group (#1092): passing the cursor over it and the
first gestures read its faces and build nothing — the build is seconds and
gigabytes on a large model. What they answer is what the built faces give, and
an edit still gets the real mesh. Skipped without the engine."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402

from core import mesh as M  # noqa: E402
from tests.test_light_faces import (  # noqa: E402
    _hover, _window, _xyz, big_enough, binary)
from tools.paint import PaintTool  # noqa: E402

import core._native as _native  # noqa: E402

pytestmark = pytest.mark.skipif(
    _native.native is None or _native.qt_hypot() is None,
    reason="engine off or not built")

__all__ = ["big_enough", "binary"]


def _click(vp, x, y):
    vp._dispatch_tool_click(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(x, y),
        vp.mapToGlobal(QPointF(x, y)), Qt.LeftButton, Qt.LeftButton,
        Qt.NoModifier))


@pytest.fixture
def floor(big_enough, tmp_path):
    win, vp = _window(tmp_path)
    mesh = vp.scene.groups[0].mesh
    assert type(mesh) is M.DeferredMesh
    yield win, vp, mesh, vp.width() / 2 + 7, vp.height() / 2 + 3
    win._saved_version = vp.scene.version
    win.close()


@pytest.mark.parametrize("tool", ["rectangle", "pushpull", "move", "rotate",
                                  "tape", "paint", "select", "line"])
def test_passing_over_a_group_builds_nothing(floor, tool):
    win, vp, mesh, x, y = floor
    win._activate_tool(tool)
    for k in range(4):
        _hover(vp, x + 13 * k, y + 5 * k)
    assert type(mesh) is M.DeferredMesh, f"{tool} built the group on a hover"


@pytest.mark.parametrize("tool", ["rectangle", "tape", "rotate", "line"])
def test_the_first_click_builds_nothing(floor, tool):
    win, vp, mesh, x, y = floor
    win._activate_tool(tool)
    _hover(vp, x, y)
    _click(vp, x, y)
    assert type(mesh) is M.DeferredMesh, f"{tool}'s first click built the group"
    assert vp.active_tool.start_point is not None


def test_a_rectangle_on_a_group_is_drawn_on_its_face_unbuilt(floor):
    win, vp, mesh, x, y = floor
    tool = win._activate_tool("rectangle") or vp.active_tool
    _hover(vp, x, y)
    _click(vp, x, y)
    got = tool.work_plane
    _hover(vp, x + 60, y + 40)
    _click(vp, x + 60, y + 40)
    assert type(mesh) is M.DeferredMesh, "the rectangle built the group below"
    assert len(vp.scene.mesh.faces) == 1
    assert {round(v.z(), 6) for v in vp.scene.mesh.faces[0].vertices} == {0.0}
    assert (got[1].x(), got[1].y(), abs(got[1].z())) == (0.0, 0.0, 1.0)


def test_rotate_takes_the_plane_of_the_face_unbuilt(floor):
    win, vp, mesh, x, y = floor
    tool = win._activate_tool("rotate") or vp.active_tool
    _hover(vp, x, y)
    light = _xyz(tool.work_plane[1])
    assert type(mesh) is M.DeferredMesh
    face, _g = vp.pick_face_any(x, y)
    assert type(face) is M.Face
    assert light == _xyz(face.normal().normalized())


def test_push_pull_refuses_a_closed_group_unbuilt(floor):
    win, vp, mesh, x, y = floor
    tool = win._activate_tool("pushpull") or vp.active_tool
    _hover(vp, x, y)
    assert tool._hover_group is vp.scene.groups[0]
    _click(vp, x, y)
    assert not tool.dragging
    assert type(mesh) is M.DeferredMesh, "a refusal built the group"


def test_push_pull_is_handed_the_real_face_of_a_loose_lazy_mesh(floor):
    from views.array_bake import LightFace
    win, vp, mesh, x, y = floor
    tool = win._activate_tool("pushpull") or vp.active_tool
    real = object()

    class Fake(LightFace):
        __slots__ = ()

        def real(self):
            return real
    fake = Fake.__new__(Fake)
    # An answer with no group is what a click would push.
    vp.pick_face_any = lambda sx, sy: (fake, None)
    vp.set_hover = lambda *a, **k: None
    tool.on_hover(SimpleNamespace(viewport=vp, screen=QPointF(x, y)))
    del vp.pick_face_any, vp.set_hover
    assert tool.hovered_face is real


def test_paint_paints_a_closed_group_whole_unbuilt(floor):
    win, vp, mesh, x, y = floor
    win._activate_tool("paint")
    PaintTool.current_is_default = False
    PaintTool.current_material = None
    PaintTool.current_texture = None
    PaintTool.current_color = (0.25, 0.5, 0.75)
    _hover(vp, x, y)
    _click(vp, x, y)
    group = vp.scene.groups[0]
    assert group.material is not None
    assert type(mesh) is M.DeferredMesh, "painting a whole group built it"
    vp.history.undo()
    assert group.material is None
    assert type(mesh) is M.DeferredMesh


@pytest.mark.parametrize("painted", [False, True])
def test_every_face_painted_reads_the_document(big_enough, tmp_path, painted):
    from core.group import Group
    from core.scene import Scene
    from formats import igz
    from PySide6.QtGui import QVector3D as V
    scene = Scene()
    m = M.Mesh()
    for i in range(5):
        f = m.add_face([V(i, 0, 0), V(i + 1, 0, 0), V(i + 1, 1, 0), V(i, 1, 0)])
        if painted or i != 3:          # an unpainted face late in the mesh
            f.attrs["color"] = [0.5, 0.25, 0.125]
    scene.groups.append(Group(m, name="tiles"))
    path = tmp_path / "tiles.igz"
    igz.save_scene(scene, path)
    opened = Scene()
    igz.load_into(opened, path)
    group = opened.groups[0]
    assert type(group.mesh) is M.DeferredMesh
    assert PaintTool._every_face_painted(group) is painted
    assert type(group.mesh) is M.DeferredMesh, "the check built the group"
    group.mesh.faces                     # the built mesh agrees
    assert PaintTool._every_face_painted(group) is painted


@pytest.mark.parametrize("tool", ["move", "rotate"])
def test_grabbing_a_group_builds_nothing_until_a_copy_is_asked(floor, tool):
    win, vp, mesh, x, y = floor
    t = win._activate_tool(tool) or vp.active_tool
    _hover(vp, x, y)
    _click(vp, x, y)
    if tool == "rotate":
        _hover(vp, x + 40, y)
        _click(vp, x + 40, y)
    assert t._groups == [vp.scene.groups[0]]
    _hover(vp, x + 60, y + 30)
    assert type(mesh) is M.DeferredMesh, f"grabbing with {tool} built the group"
    n = len(t.rubber_band_lines())
    assert type(mesh) is M.DeferredMesh
    t._toggle_copy(vp, say=False)
    ghost = t.rubber_band_lines()
    assert len(ghost) == n + len(mesh.edges), \
        "the copy's wireframe: every edge of the group"
    assert len(t.rubber_band_lines()) == len(ghost), "and only once"
    t._toggle_copy(vp, say=False)
    t.on_cancel(vp)


def test_a_centre_on_a_lazy_group_follows_it_unbuilt(big_enough, tmp_path):
    """An edit elsewhere re-checks the acquired centre: the frame after it
    built the group under the centre, whatever the size."""
    import math
    from core.group import Group
    from core.scene import Scene
    from formats import igz
    from views import array_bake
    from views.main_window import MainWindow
    from PySide6.QtGui import QMatrix4x4, QVector3D as V
    scene = Scene()
    m = M.Mesh()
    ring = [V(math.cos(i * math.pi / 12), math.sin(i * math.pi / 12), 0)
            for i in range(24)]
    for i in range(3):
        m.add_face([p + V(4 * i, 0, 0) for p in ring])
    scene.groups.append(Group(m, name="discs"))
    path = tmp_path / "discs.igz"
    igz.save_scene(scene, path)
    win = MainWindow()
    try:
        assert win.open_path(path) is not False
        vp = win.viewport
        group = vp.scene.groups[0]
        mesh = group.mesh
        assert type(mesh) is M.DeferredMesh
        found = vp._center_of_face(array_bake.light_face(mesh, 0), group, mesh,
                                   0.0, 0.0)
        vp._center_ref = found
        vp.scene.version += 1
        fresh = vp._valid_center_ref()
        assert type(mesh) is M.DeferredMesh, "the check built the group"
        assert _xyz(fresh[0]) == _xyz(found[0])
        group.xform = QMatrix4x4()
        group.xform.translate(1, 2, 3)
        vp.scene.version += 1
        moved = vp._valid_center_ref()
        assert type(mesh) is M.DeferredMesh
        assert _xyz(moved[0]) == _xyz(group.xform.map(found[0]))
        mesh.faces                       # built meanwhile: the real face now
        vp.scene.version += 1
        again = vp._valid_center_ref()
        assert type(again[4]) is M.Face
        assert _xyz(again[0]) == _xyz(moved[0])
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_view_moving_into_the_grid_keeps_its_bakes(floor):
    """Its new GL context needs the uploads again, not the bakes: forgetting
    those cost seconds on a big model, and the extra views made next found
    nothing to share."""
    from views import array_bake
    win, vp, mesh, _x, _y = floor
    group = vp.scene.groups[0]
    entry = vp._group_chunk(group)
    vp._proto_draw = {"fake": {}}
    vp._vbo_parts["fake"] = ([], 0, {})
    vp._edges_version = 7
    win._before_viewport_moves(vp)
    assert vp._group_chunks[id(group)] is entry
    assert not vp._proto_draw and not vp._vbo_parts and vp._edges_version == -1
    other = win.viewport.__class__(win)
    try:
        other.set_document(vp.scene, vp.history)
        baked = []
        real_bake = array_bake._bake
        array_bake._bake = lambda *a: baked.append(a) or real_bake(*a)
        try:
            shared = other._group_chunk(group)
        finally:
            array_bake._bake = real_bake
        assert not baked, "the next view baked it again"
        assert shared["faces"] is entry["faces"] or shared["vcol"] is entry["vcol"]
    finally:
        other.setParent(None)
        other.deleteLater()


def _boxed_scene(tmp_path, closed, placed):
    from core.group import Group
    from core.scene import Scene
    from formats import igz
    from PySide6.QtGui import QMatrix4x4, QVector3D as V
    scene = Scene()
    m = M.Mesh()
    a, b, c, d = V(0, 0, 0), V(2, 0, 0), V(2, 3, 0), V(0, 3, 0)
    h = V(0, 0, 4)
    sides = [[d, c, b, a], [a, b, b + h, a + h], [b, c, c + h, b + h],
             [c, d, d + h, c + h], [d, a, a + h, d + h]]
    if closed:
        sides.append([a + h, b + h, c + h, d + h])
    for ring in sides:
        m.add_face(ring)
    g = Group(m, name="box")
    if placed:
        g.xform = QMatrix4x4()
        g.xform.translate(5, 0, 0)
    scene.groups.append(g)
    path = tmp_path / f"box{closed}{placed}.igz"
    igz.save_scene(scene, path)
    opened = Scene()
    igz.load_into(opened, path)
    return opened.groups[0]


@pytest.mark.parametrize("placed", [False, True])
def test_an_open_group_says_no_volume_unbuilt(big_enough, tmp_path, placed):
    from core.solids import solid_volume
    group = _boxed_scene(tmp_path, False, placed)
    mesh = group.mesh
    assert type(mesh) is M.DeferredMesh
    assert solid_volume(group) is None
    assert type(mesh) is M.DeferredMesh, "the panel's question built the group"
    mesh.faces
    assert solid_volume(group) is None, "and the built mesh agrees"


@pytest.mark.parametrize("placed", [False, True])
def test_a_closed_group_still_gets_its_volume(big_enough, tmp_path, placed):
    from core.solids import solid_volume
    group = _boxed_scene(tmp_path, True, placed)
    assert type(group.mesh) is M.DeferredMesh
    assert solid_volume(group) == pytest.approx(24.0)
