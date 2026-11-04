# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Two objects sharing a plane: the smaller one takes the click (#982,
@DecDumplings).

A circle drawn on a wall group and then grouped lies at the wall's depth to
the last float, and pick_group took whichever came out nearest: the same
disc selected the disc from one pixel or camera and the wall from the next.
pick_face settled that tie long ago (the smallest of the overlapping faces
wins), so the two now answer alike, for faces and objects, loose or not.
"""
from __future__ import annotations

import math
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.group import Group  # noqa: E402
from core.history import MakeGroupCommand  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from tools.select import SelectTool  # noqa: E402
from views.viewport import Viewport  # noqa: E402

CENTER = (1.5, 1.2)                     # of the disc, on the wall's face
RADIUS = 0.3


def _box(p):
    m = Mesh()
    for i in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
              (2, 3, 7, 6), (3, 0, 4, 7)):
        m.add_face([p[k] for k in i])
    return m


def _corners(P):
    return [P(0, 0, 0), P(3, 0, 0), P(3, .2, 0), P(0, .2, 0),
            P(0, 0, 2.5), P(3, 0, 2.5), P(3, .2, 2.5), P(0, .2, 2.5)]


def _placed(rot):
    """Wall coordinates → world: turned ``rot`` degrees about Z, off every
    round number, so no depth comes out equal by luck."""
    x = QMatrix4x4()
    x.translate(1.3, 0.7, 0.11)
    x.rotate(rot, 0, 0, 1)
    return x


def _vp():
    vp = Viewport(None)
    vp.resize(1000, 600)
    vp.camera.set_aspect(1000, 600)
    vp.flash_status = lambda *a, **k: None
    vp.scene.guides.clear()
    return vp


def _wall(vp, kind, rot):
    x = _placed(rot)
    if kind == "component":
        wall = Group(_box(_corners(V)), "muro")
        wall.xform = x
    else:
        wall = Group(_box(_corners(lambda *a: x.map(V(*a)))), "muro")
    vp.scene.groups.append(wall)
    vp.scene.version += 1
    return wall, (lambda a, b, c: x.map(V(a, b, c)))


def _loose_disc(vp, P, y=0.0, r=RADIUS):
    cx, cz = CENTER
    return vp.scene.mesh.add_face(
        [P(cx + r * math.cos(2 * math.pi * i / 24), y,
           cz + r * math.sin(2 * math.pi * i / 24)) for i in range(24)])


def _group_it(vp, face, component=False):
    """As Make Group / Make Component do it."""
    edges = [e for e in vp.scene.mesh.edges if face in e.faces]
    before = list(vp.scene.groups)
    vp.history.execute(MakeGroupCommand([face], edges, component=component))
    new = [g for g in vp.scene.groups if not any(g is b for b in before)]
    assert len(new) == 1
    return new[0]


def _scene(kind="group", rot=33.3, disc="group", lazy=False):
    vp = _vp()
    wall, P = _wall(vp, kind, rot)
    d = _group_it(vp, _loose_disc(vp, P), component=disc == "component")
    vp._PICK_LAZY_MIN_FACES = 1 if lazy else 10 ** 9
    return vp, wall, d, P


def _look(vp, P, rot, yaw, pitch, dist, parallel=False):
    cam = vp.camera
    cam.target = P(CENTER[0], 0, CENTER[1])
    cam.distance = dist
    cam.yaw = math.radians(yaw + rot)
    cam.pitch = math.radians(pitch)
    cam.perspective = not parallel


def _inner_pixels(vp, P, r=RADIUS * 0.8, n=20):
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n
        rr = r * ((i % 4) + 1) / 4
        out.append(vp._world_to_pixel(P(CENTER[0] + rr * math.cos(a), 0,
                                        CENTER[1] + rr * math.sin(a))))
    return [p for p in out if p is not None]


CAMERAS = [(yaw, pitch, dist)
           for yaw in (-90, -70, -125, -83.3)
           for pitch in (0, 17, -12)
           for dist in (2.5, 15, 40)]


def _ctx(vp, px, modifiers=Qt.NoModifier):
    return SimpleNamespace(viewport=vp, modifiers=modifiers,
                           screen=QPoint(round(px[0]), round(px[1])))


@pytest.mark.parametrize("lazy", [False, True], ids=["baked", "lazy"])
@pytest.mark.parametrize("disc", ["group", "component"])
@pytest.mark.parametrize("kind", ["group", "component"])
@pytest.mark.parametrize("rot", [0.0, 33.3])
def test_the_disc_takes_the_click_from_every_camera(rot, kind, disc, lazy):
    vp, wall, d, P = _scene(kind, rot, disc, lazy)
    tool = SelectTool()
    for yaw, pitch, dist in CAMERAS:
        _look(vp, P, rot, yaw, pitch, dist)
        for px in _inner_pixels(vp, P):
            assert vp.pick_group(*px) is d, (yaw, pitch, dist, px)
            assert tool._pick(vp, *px) is d, (yaw, pitch, dist, px)
        # beside the disc the wall is still the pick
        beside = vp._world_to_pixel(P(0.5, 0, 0.5))
        if beside is not None:
            assert tool._pick(vp, *beside) is wall, (yaw, pitch, dist)


def test_the_parallel_camera_too():
    vp, wall, d, P = _scene()
    for yaw, pitch, dist in CAMERAS:
        _look(vp, P, 33.3, yaw, pitch, dist, parallel=True)
        for px in _inner_pixels(vp, P):
            assert vp.pick_group(*px) is d, (yaw, pitch, dist)


def test_double_click_opens_the_disc_and_a_click_selects_it():
    vp, wall, d, P = _scene()
    tool = SelectTool()
    for yaw, pitch, dist in CAMERAS[:12]:
        _look(vp, P, 33.3, yaw, pitch, dist)
        px = _inner_pixels(vp, P)[3]
        tool.on_click(_ctx(vp, px))
        assert list(vp.scene.selection) == [d]
        vp.scene.clear_selection()
        tool.on_double_click(_ctx(vp, px))
        assert vp.scene.edit_group is d, "the double click opened the wall"
        vp.end_one_group_edit()
        assert vp.scene.edit_group is None


def test_hover_marks_what_the_click_will_take():
    vp, wall, d, P = _scene()
    tool = SelectTool()
    for yaw, pitch, dist in CAMERAS[:12]:
        _look(vp, P, 33.3, yaw, pitch, dist)
        for px in _inner_pixels(vp, P):
            tool.on_hover(_ctx(vp, px))
            assert vp._hover_entity is d


def test_face_and_object_picks_agree_on_the_disc():
    """Paint and the drawing tools read the face through pick_face_any."""
    vp, wall, d, P = _scene()
    _look(vp, P, 33.3, -83.3, 17, 6)
    for px in _inner_pixels(vp, P):
        face, owner = vp.pick_face_any(*px)
        assert owner is d and face in d.mesh.faces
        assert vp.pick_group(*px) is owner


def test_right_click_selects_the_disc():
    vp, wall, d, P = _scene()
    _look(vp, P, 33.3, -83.3, 17, 6)
    for px in _inner_pixels(vp, P):
        vp.scene.clear_selection()
        assert vp._context_pick(*px) is d
        assert list(vp.scene.selection) == [d]


def test_inside_the_open_disc_or_wall_the_context_decides():
    vp, wall, d, P = _scene()
    _look(vp, P, 33.3, -83.3, 17, 6)
    tool = SelectTool()
    px = _inner_pixels(vp, P)[0]
    vp.begin_group_edit(d)
    assert vp.pick_group(*px) is None
    assert tool._pick(vp, *px) in vp.scene.mesh.faces
    vp.end_one_group_edit()
    vp.begin_group_edit(wall)
    assert vp.pick_group(*px) is None, "the disc is outside the open wall"
    assert tool._pick(vp, *px) in vp.scene.mesh.faces
    vp.end_one_group_edit()


def test_a_grouped_disc_on_a_loose_face():
    """The wall itself not grouped: the disc must still be reachable."""
    vp = _vp()
    P = lambda a, b, c: _placed(33.3).map(V(a, b, c))  # noqa: E731
    vp.scene.mesh.add_face([P(0, 0, 0), P(3, 0, 0), P(3, 0, 2.5),
                            P(0, 0, 2.5)])
    d = _group_it(vp, _loose_disc(vp, P, r=RADIUS))
    _look(vp, P, 33.3, -83.3, 17, 6)
    tool = SelectTool()
    for px in _inner_pixels(vp, P):
        assert tool._pick(vp, *px) is d
    beside = vp._world_to_pixel(P(0.5, 0, 0.5))
    assert vp.pick_group(*beside) is None
    assert tool._pick(vp, *beside) in vp.scene.mesh.faces


def test_a_child_on_its_open_parents_face_is_reachable():
    """Same plane inside an open group: its own face is the loose part."""
    vp = _vp()
    P = lambda a, b, c: _placed(33.3).map(V(a, b, c))  # noqa: E731
    m = Mesh()
    m.add_face([P(0, 0, 0), P(3, 0, 0), P(3, 0, 2.5), P(0, 0, 2.5)])
    parent = Group(m, "panel")
    cx, cz = CENTER
    cm = Mesh()
    cm.add_face([P(cx + RADIUS * math.cos(2 * math.pi * i / 24), 0,
                   cz + RADIUS * math.sin(2 * math.pi * i / 24))
                 for i in range(24)])
    child = Group(cm, "hijo")
    parent.children = [child]
    vp.scene.groups.append(parent)
    vp.scene.version += 1
    _look(vp, P, 33.3, -83.3, 17, 6)
    px = _inner_pixels(vp, P)[2]
    # From outside the parent is the one object there.
    assert vp.pick_group(*px) is parent
    vp.begin_group_edit(parent)
    assert vp.pick_group(*px) is child
    assert SelectTool()._pick(vp, *px) is child
    vp.end_one_group_edit()


def test_a_scaled_component_compares_by_its_placed_area():
    """A disc modelled huge and placed small is still the small one."""
    vp = _vp()
    wall, P = _wall(vp, "group", 33.3)
    big = Mesh()
    r = 30.0
    big.add_face([V(r * math.cos(2 * math.pi * i / 24), 0,
                    r * math.sin(2 * math.pi * i / 24)) for i in range(24)])
    d = Group(big, "escalado")
    x = _placed(33.3)
    x.translate(CENTER[0], 0, CENTER[1])
    x.scale(0.01)
    d.xform = x
    vp.scene.groups.append(d)
    vp.scene.version += 1
    _look(vp, P, 33.3, -83.3, 17, 6)
    for px in _inner_pixels(vp, P):
        assert vp.pick_group(*px) is d


def test_depth_still_decides_when_they_do_not_share_a_plane():
    """The tiebreak is for ties: a small disc 2 cm in front wins from the
    front and a small disc 2 cm inside the wall never does."""
    vp = _vp()
    wall, P = _wall(vp, "group", 33.3)
    inside = _group_it(vp, _loose_disc(vp, P, y=0.02))
    _look(vp, P, 33.3, -83.3, 17, 6)
    for px in _inner_pixels(vp, P):
        assert vp.pick_group(*px) is wall, "picked through the wall"
    vp.history.undo()
    front = _group_it(vp, _loose_disc(vp, P, y=-0.02))
    for px in _inner_pixels(vp, P):
        assert vp.pick_group(*px) is front
    # And from behind the wall, the disc on the far side stays hidden.
    _look(vp, P, 33.3, 90, 17, 6)
    assert all(vp.pick_group(*px) is wall for px in _inner_pixels(vp, P))


def test_a_small_face_behind_the_front_one_stays_behind_in_parallel():
    """#37's tolerance is by distance from the eye: the parallel camera's
    ray starts km behind it and must not reach through the wall."""
    vp = _vp()
    wall, P = _wall(vp, "group", 33.3)
    _group_it(vp, _loose_disc(vp, P, y=0.05))
    _look(vp, P, 33.3, -83.3, 17, 6, parallel=True)
    for px in _inner_pixels(vp, P):
        assert vp.pick_group(*px) is wall


def test_a_locked_disc_is_offered_for_unlock_over_the_wall():
    """The right-click's way back to a locked object (#782) follows the
    same rule: the wall must not hide it by a float."""
    vp, wall, d, P = _scene()
    d.locked = True
    vp.scene.version += 1
    for yaw, pitch, dist in CAMERAS:
        _look(vp, P, 33.3, yaw, pitch, dist)
        for px in _inner_pixels(vp, P):
            assert vp.pick_locked_group(*px) is d, (yaw, pitch, dist)
