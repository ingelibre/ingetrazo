# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #1272: a window or a door marked «Cut opening» opens its own hole
in the wall it sits on — through the wall when its other side stands
behind — and the hole follows it: moved, the old hole closes and a new one
opens; erased, the wall is whole again. Every step undoes as one."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402

from core import openings  # noqa: E402
from core.group import Group, copy_group  # noqa: E402
from core.history import (DeleteFaceCommand, DeleteGroupCommand,  # noqa: E402
                          History, InsertGroupCommand, MoveGroupCommand,
                          RotateGroupCommand, ScaleGroupCommand)
from core.orient import orient_outward  # noqa: E402
from core.scene import Scene  # noqa: E402

#: Local axes of a window on the wall's front (y = 0, facing -y): red along
#: the wall, green up, blue out of the wall.
_ON_FRONT = QMatrix4x4(1, 0, 0, 0,
                       0, 0, -1, 0,
                       0, 1, 0, 0,
                       0, 0, 0, 1)


def _wall(mesh, length=3.0, thick=0.2, height=2.5):
    p = [V(0, 0, 0), V(length, 0, 0), V(length, thick, 0), V(0, thick, 0)]
    q = [V(0, 0, height), V(length, 0, height), V(length, thick, height),
         V(0, thick, height)]
    mesh.add_face(p)
    mesh.add_face(q)
    for i in range(4):
        j = (i + 1) % 4
        mesh.add_face([p[i], p[j], q[j], q[i]])
    orient_outward(mesh)
    for f in mesh.faces:
        f.attrs["color"] = (0.8, 0.7, 0.6)


def _window(w=1.0, h=1.2, x=1.0, z=0.9, frame_face=True, mark=True):
    g = Group(name="Window")
    m = g.mesh
    outer = [V(0, 0, 0), V(w, 0, 0), V(w, h, 0), V(0, h, 0)]
    if frame_face:
        inner = [V(.05, .05, 0), V(w - .05, .05, 0), V(w - .05, h - .05, 0),
                 V(.05, h - .05, 0)]
        m.add_face(outer, [inner])
    else:
        # Only a sash set back from the base plane: the footprint is the
        # rectangle the window covers.
        back = [V(p.x(), p.y(), -0.05) for p in outer]
        m.add_face(back)
    t = QMatrix4x4()
    t.translate(x, 0, z)
    g.xform = t * _ON_FRONT
    if mark:
        openings.set_ext_entry(g, {"on": True})
    return g


def _closed(mesh) -> bool:
    return all(len(e.faces) == 2 for e in mesh.edges)


def _state(mesh):
    """The model as positions: comparable across undo and redo."""
    r = lambda p: (round(p.x(), 4), round(p.y(), 4), round(p.z(), 4))  # noqa: E731
    return sorted((tuple(sorted(r(p) for p in f.vertices)), len(f.hole_loops))
                  for f in mesh.faces)


@pytest.fixture
def model():
    scene = Scene()
    _wall(scene.mesh)
    return scene, History(scene)


# ---- The footprint ----------------------------------------------------------
def test_the_footprint_is_the_face_on_the_base_plane():
    fp = openings.footprint(_window())
    xs = sorted({round(p.x(), 4) for p in fp})
    zs = sorted({round(p.z(), 4) for p in fp})
    assert xs == [1.0, 2.0] and zs == [0.9, 2.1]
    assert all(abs(p.y()) < 1e-6 for p in fp)          # on the wall's face


def test_without_a_face_there_it_is_the_covered_rectangle():
    fp = openings.footprint(_window(frame_face=False))
    assert len(fp) == 4
    assert {round(p.x(), 4) for p in fp} == {1.0, 2.0}
    assert all(abs(p.y()) < 1e-6 for p in fp)


# ---- Cutting and healing ----------------------------------------------------
def test_a_window_opens_the_wall_through(model):
    scene, history = model
    history.execute(InsertGroupCommand(_window()))
    mesh = scene.mesh
    assert len(mesh.faces) == 10                   # 6 + 4 reveals
    assert sum(len(f.hole_loops) for f in mesh.faces) == 2
    assert _closed(mesh)
    centre = V(1.5, 0.1, 1.5)
    reveals = [f for f in mesh.faces
               if 0.0 < f.centroid().y() < 0.2
               and 1.0 - 1e-4 <= f.centroid().x() <= 2.0 + 1e-4
               and 0.9 - 1e-4 <= f.centroid().z() <= 2.1 + 1e-4]
    assert len(reveals) == 4
    for f in reveals:                              # they face the hole
        assert V.dotProduct(f.normal(), centre - f.centroid()) > 0
        assert f.attrs.get("color") == (0.8, 0.7, 0.6)   # the wall's paint


def test_a_door_on_the_foot_opens_the_bottom_too(model):
    scene, history = model
    history.execute(InsertGroupCommand(_window(w=0.9, h=2.1, x=0.5, z=0.0)))
    mesh = scene.mesh
    assert _closed(mesh)
    assert len(mesh.faces) == 10                   # 3 reveals, foot in two
    bottoms = [f for f in mesh.faces if abs(f.centroid().z()) < 1e-6]
    assert len(bottoms) == 2


def test_erasing_it_makes_the_wall_whole_again(model):
    scene, history = model
    before = _state(scene.mesh)
    g = _window()
    history.execute(InsertGroupCommand(g))
    history.execute(DeleteGroupCommand(g))
    assert _state(scene.mesh) == before
    assert len(scene.mesh.edges) == 12
    history.undo()
    assert len(scene.mesh.faces) == 10
    history.redo()
    assert _state(scene.mesh) == before


def test_a_door_erased_leaves_no_split_edge(model):
    scene, history = model
    g = _window(w=0.9, h=2.1, x=0.5, z=0.0)
    history.execute(InsertGroupCommand(g))
    history.execute(DeleteGroupCommand(g))
    assert len(scene.mesh.faces) == 6 and len(scene.mesh.edges) == 12
    assert _closed(scene.mesh)


def test_a_single_face_gets_a_hole_only():
    scene = Scene()
    scene.mesh.add_face([V(0, 0, 0), V(3, 0, 0), V(3, 0, 2.5), V(0, 0, 2.5)])
    history = History(scene)
    history.execute(InsertGroupCommand(_window()))
    assert len(scene.mesh.faces) == 1
    assert len(scene.mesh.faces[0].hole_loops) == 1


def test_a_face_further_than_the_limit_is_another_wall():
    scene = Scene()
    _wall(scene.mesh, thick=openings.MAX_THICKNESS + 0.2)
    history = History(scene)
    history.execute(InsertGroupCommand(_window()))
    assert sum(len(f.hole_loops) for f in scene.mesh.faces) == 1


def test_a_window_running_off_the_wall_cuts_nothing(model):
    scene, history = model
    before = _state(scene.mesh)
    history.execute(InsertGroupCommand(_window(x=2.5)))     # 0.5 m outside
    assert _state(scene.mesh) == before


def test_an_unmarked_component_cuts_nothing(model):
    scene, history = model
    before = _state(scene.mesh)
    history.execute(InsertGroupCommand(_window(mark=False)))
    assert _state(scene.mesh) == before


# ---- Following it -----------------------------------------------------------
def test_the_hole_follows_a_move(model):
    scene, history = model
    g = _window()
    history.execute(InsertGroupCommand(g))
    history.execute(MoveGroupCommand(g, V(0.8, 0, 0)))
    mesh = scene.mesh
    assert _closed(mesh) and len(mesh.faces) == 10
    xs = {round(v.position.x(), 4) for v in mesh.vertices}
    assert {1.8, 2.8} <= xs and 1.0 not in xs and 2.0 not in xs


def test_moved_off_the_wall_the_wall_closes(model):
    scene, history = model
    before = _state(scene.mesh)
    g = _window()
    history.execute(InsertGroupCommand(g))
    history.execute(MoveGroupCommand(g, V(0, -2, 0)))
    assert _state(scene.mesh) == before
    history.execute(MoveGroupCommand(g, V(0, 2, 0)))       # back on it
    assert len(scene.mesh.faces) == 10


def test_rotate_and_scale_follow_too(model):
    scene, history = model
    g = _window()
    history.execute(InsertGroupCommand(g))
    history.execute(RotateGroupCommand(g, V(1.5, 0, 1.5), V(0, 1, 0), 90))
    assert len(scene.mesh.faces) == 10 and _closed(scene.mesh)
    history.execute(ScaleGroupCommand(g, V(1.5, 0, 1.5), 0.5))
    assert len(scene.mesh.faces) == 10 and _closed(scene.mesh)


def test_every_step_undoes_and_redoes_exactly(model):
    scene, history = model
    g = _window()
    states = [_state(scene.mesh)]
    for cmd in (InsertGroupCommand(g), MoveGroupCommand(g, V(0.6, 0, 0)),
                MoveGroupCommand(g, V(0, 0, -0.9)),
                RotateGroupCommand(g, V(2, 0, 1), V(0, 1, 0), 30),
                DeleteGroupCommand(g)):
        history.execute(cmd)
        assert history.last_error is None
        states.append(_state(scene.mesh))
    for k in range(len(states) - 1, 0, -1):
        history.undo()
        assert _state(scene.mesh) == states[k - 1]
    for k in range(1, len(states)):
        history.redo()
        assert _state(scene.mesh) == states[k]


def test_the_command_stays_on_top_of_the_stack(model):
    # A hot retype looks for its own command there.
    scene, history = model
    g = _window()
    history.execute(InsertGroupCommand(g))
    move = MoveGroupCommand(g, V(0.3, 0, 0))
    history.execute(move)
    assert history.undo_stack[-1] is move


def test_a_copy_cuts_its_own_hole(model):
    scene, history = model
    g = _window(x=0.2)
    history.execute(InsertGroupCommand(g))
    history.execute(InsertGroupCommand(copy_group(g, V(1.5, 0, 0))))
    mesh = scene.mesh
    assert sum(len(f.hole_loops) for f in mesh.faces) == 4
    assert len(mesh.faces) == 14 and _closed(mesh)


def test_unmarking_closes_and_marking_opens(model):
    scene, history = model
    before = _state(scene.mesh)
    g = _window(mark=False)
    history.execute(InsertGroupCommand(g))
    history.execute(openings.SetCutOpeningCommand([g], True))
    assert len(scene.mesh.faces) == 10
    history.execute(openings.SetCutOpeningCommand([g], False))
    assert _state(scene.mesh) == before
    history.undo()
    assert len(scene.mesh.faces) == 10
    history.undo()
    assert _state(scene.mesh) == before and not openings.wants_opening(g)


def test_a_hole_edited_by_hand_is_left_alone(model):
    scene, history = model
    notices = []
    history.on_notice = notices.append
    g = _window()
    history.execute(InsertGroupCommand(g))
    jamb = next(f for f in scene.mesh.faces
                if abs(f.centroid().x() - 1.0) < 1e-6
                and 0 < f.centroid().y() < 0.2)
    history.execute(DeleteFaceCommand(jamb))
    faces = len(scene.mesh.faces)
    history.execute(MoveGroupCommand(g, V(0, -2, 0)))      # off the wall
    assert len(scene.mesh.faces) == faces                 # nothing healed
    assert notices and "Window" in notices[0]


def test_the_component_carries_its_mark_and_record_through_a_save(tmp_path):
    from formats.igz import load_into, save_scene
    scene = Scene()
    _wall(scene.mesh)
    history = History(scene)
    g = _window()
    history.execute(InsertGroupCommand(g))
    path = tmp_path / "wall.igz"
    save_scene(scene, path)
    again = Scene()
    load_into(again, path)
    h2 = History(again)
    w = next(x for x in again.groups if x.name == "Window")
    assert openings.wants_opening(w) and openings.made(w) is not None
    h2.execute(DeleteGroupCommand(w))                      # heals after loading
    assert len(again.mesh.faces) == 6 and _closed(again.mesh)


# ---- Placing it -------------------------------------------------------------
class _Viewport:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def flash_status(self, *_a, **_k):
        pass

    def window(self):
        return None

    def update(self):
        pass


def test_placing_glues_the_blue_axis_to_the_face():
    from tools.place_group import PlaceGroupTool
    scene = Scene()
    _wall(scene.mesh)
    vp = _Viewport(scene)
    g = _window()
    g.xform = QMatrix4x4()                    # drawn lying in the world axes
    tool = PlaceGroupTool(g)
    tool._face_normal = V(0, -1, 0)           # hovering the wall's front
    tool.place_at(vp, V(1.0, 0.0, 0.9))
    m = g.xform
    z = m.mapVector(V(0, 0, 1))
    y = m.mapVector(V(0, 1, 0))
    assert (z - V(0, -1, 0)).length() < 1e-6         # blue out of the wall
    assert (y - V(0, 0, 1)).length() < 1e-6          # green up
    assert (m.map(V(0, 0, 0)) - V(1.0, 0.0, 0.9)).length() < 1e-6
    assert len(scene.mesh.faces) == 10               # and it cut


def test_the_floor_under_a_door_stays(model):
    # The wall drawn on a floor: the floor is split round the wall's foot,
    # which is a piece of that same plane. The door opens the wall, not the
    # floor.
    scene = Scene()
    outer = [V(-2, -2, 0), V(5, -2, 0), V(5, 2, 0), V(-2, 2, 0)]
    foot = [V(0, 0, 0), V(0, 0.2, 0), V(3, 0.2, 0), V(3, 0, 0)]
    scene.mesh.add_face(outer, [foot])
    _wall(scene.mesh)
    history = History(scene)
    before = _state(scene.mesh)
    floor_area = sum(f.net_area() for f in scene.mesh.faces
                     if abs(f.centroid().z()) < 1e-6)
    g = _window(w=0.9, h=2.1, x=0.5, z=0.0)
    history.execute(InsertGroupCommand(g))
    assert history.last_error is None
    after = sum(f.net_area() for f in scene.mesh.faces
                if abs(f.centroid().z()) < 1e-6)
    assert after == pytest.approx(floor_area)          # no hole in the floor
    assert openings.made(g)["keep"] == [2]             # the sill side
    history.execute(DeleteGroupCommand(g))
    assert _state(scene.mesh) == before
