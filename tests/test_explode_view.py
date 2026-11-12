# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Exploded view: a component's parts pulled apart, and put back exactly."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

from core import explode
from core.group import Group, copy_group, world_mesh
from core.history import (ExplodeGroupCommand, ExplodeViewCommand,
                          MoveGroupCommand, SplitIntoPiecesCommand)
from core.mesh import Mesh
from core.parts import part_points
from core.scene import Scene

_app = QApplication.instance() or QApplication([])

_QUADS = ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
          (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5))


def _cube(at) -> Group:
    mesh = Mesh()
    x0, y0, z0 = at
    c = [QVector3D(x0 + dx, y0 + dy, z0 + dz) for dz in (0, 1)
         for dy in (0, 1) for dx in (0, 1)]
    for q in _QUADS:
        mesh.add_face([c[k] for k in q])
    g = Group(mesh)
    g.xform = QMatrix4x4()
    return g


def _assembly(placed=True):
    """A centre cube and one on each side of it along red, and one above."""
    kids = [_cube((0, 0, 0)), _cube((-3, 0, 0)), _cube((3, 0, 0)),
            _cube((0, 0, 3))]
    box = Group(name="box")
    box.adopt(kids)
    if placed:
        m = QMatrix4x4()
        m.translate(QVector3D(10, 5, 0))
        m.rotate(35, 0, 0, 1)
        box.xform = m
    scene = Scene()
    scene.groups.append(box)
    return scene, box


def _world(group) -> list:
    return sorted((round(v.position.x(), 5), round(v.position.y(), 5),
                   round(v.position.z(), 5))
                  for v in world_mesh(group).vertices)


def _centre(part):
    pts = part_points(part)
    return tuple(round(float(x), 5) for x in (pts.min(0) + pts.max(0)) / 2)


def test_parts_move_away_from_the_centre_in_proportion():
    scene, box = _assembly(placed=False)
    ExplodeViewCommand(box, 1.0).do(scene)
    # The centre of the parts' centres is (0.5, 0.5, 2.0); each part ends
    # twice as far from it as it was.
    assert [_centre(k) for k in box.children] == [
        (0.5, 0.5, -1.0), (-5.5, 0.5, -1.0), (6.5, 0.5, -1.0),
        (0.5, 0.5, 5.0)]


def test_along_one_axis_only_that_axis_moves():
    scene, box = _assembly(placed=False)
    ExplodeViewCommand(box, 1.0, "z").do(scene)
    assert [_centre(k)[:2] for k in box.children] == [
        (0.5, 0.5), (-2.5, 0.5), (3.5, 0.5), (0.5, 0.5)]
    assert _centre(box.children[3])[2] == pytest.approx(5.0)


def test_reassemble_and_undo_are_exact():
    scene, box = _assembly()
    assembled = _world(box)
    first = ExplodeViewCommand(box, 1.5)
    first.do(scene)
    assert _world(box) != assembled
    second = ExplodeViewCommand(box, 0.4, "y")   # amount and way changed
    second.do(scene)
    ExplodeViewCommand(box, 0).do(scene)
    assert _world(box) == assembled and box.exploded is None
    assert all(k.explode_offset is None for k in box.children)
    second.do(scene)
    second.undo(scene)
    first.undo(scene)
    assert _world(box) == assembled


def test_a_part_moved_by_hand_keeps_that_move():
    scene, box = _assembly(placed=False)
    ExplodeViewCommand(box, 1.0).do(scene)
    part = box.children[1]
    MoveGroupCommand(part, QVector3D(0, 2, 0)).do(scene)
    ExplodeViewCommand(box, 0).do(scene)
    assert _centre(part) == (-2.5, 2.5, 0.5)       # assembled + the hand move


def test_reassembling_after_opening_the_placed_component():
    """Entering a container pushes its matrix down into the parts; the
    offsets turn with it, so reassembling afterwards is still exact."""
    scene, box = _assembly()
    assembled = _world(box)
    ExplodeViewCommand(box, 1.0).do(scene)
    scene.begin_group_edit(box)
    scene.end_group_edit()
    ExplodeViewCommand(box, 0).do(scene)
    assert _world(box) == assembled


def test_the_document_remembers_the_exploded_view(tmp_path):
    from formats import igz
    scene, box = _assembly()
    assembled = _world(box)
    ExplodeViewCommand(box, 0.8, "z").do(scene)
    igz.save_scene(scene, tmp_path / "e.igz")
    again = Scene()
    igz.load_into(again, tmp_path / "e.igz")
    box2 = again.groups[0]
    assert box2.exploded == {"factor": 0.8, "mode": "z"}
    ExplodeViewCommand(box2, 0).do(again)
    assert _world(box2) == assembled


def test_a_copy_reassembles_on_its_own():
    scene, box = _assembly(placed=False)
    assembled = _world(box)
    ExplodeViewCommand(box, 1.0).do(scene)
    twin = copy_group(box)
    scene.groups.append(twin)
    ExplodeViewCommand(twin, 0).do(scene)
    assert _world(twin) == assembled
    assert box.exploded is not None                # the original stays apart


def test_split_starts_a_fresh_assembly():
    from core.pieces import split_into_pieces
    scene, box = _assembly(placed=False)
    ExplodeViewCommand(box, 1.0).do(scene)
    cmd = SplitIntoPiecesCommand(box, split_into_pieces(box))
    cmd.do(scene)
    assert box.exploded is None
    cmd.undo(scene)
    assert box.exploded == {"factor": 1.0, "mode": "outward"}


def test_exploding_the_group_frees_the_parts_where_they_stand():
    scene, box = _assembly(placed=False)
    ExplodeViewCommand(box, 1.0).do(scene)
    spread = _world(box)
    cmd = ExplodeGroupCommand(box)
    cmd.do(scene)
    assert all(g.explode_offset is None for g in scene.groups)
    freed = sorted(p for g in scene.groups for p in _world(g))
    assert freed == sorted(spread)
    cmd.undo(scene)
    assert all(k.explode_offset is not None for k in box.children[1:])


def test_the_tray_slider_is_one_undo_step_per_drag():
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    _s, box = _assembly()
    scene.groups.append(box)
    scene.selection.clear()
    scene.selection.add(box)
    scene.version += 1
    assembled = _world(box)
    panel = win.tray.parts
    panel.refresh()
    history = win.viewport.history
    before = len(history.undo_stack)
    panel._on_explode_press()
    for v in (10, 40, 90, 120):
        panel._explode_slider.setValue(v)
    panel._on_explode_release()
    assert len(history.undo_stack) == before + 1
    assert box.exploded == {"factor": 1.2, "mode": "outward"}
    panel._on_reassemble()
    assert _world(box) == assembled
    history.undo()
    history.undo()
    assert _world(box) == assembled and box.exploded is None
    win._saved_version = scene.version


def test_offsets_turn_with_a_pushed_down_matrix():
    part = _cube((0, 0, 0))
    part.explode_offset = (1.0, 0.0, 0.0)
    holder = Group()
    holder.adopt([part])
    turn = QMatrix4x4()
    turn.rotate(90, 0, 0, 1)
    explode.rotate_offsets(holder, turn)
    assert part.explode_offset == pytest.approx((0.0, 1.0, 0.0), abs=1e-6)


def test_plain_groups_pulled_apart_stay_groups():
    """#1375: the parts of a group of groups are plain groups, with no
    matrix; the explosion gives each one, and a group with a matrix read
    as a component — the walls of a building came back components, whose
    parts could no longer be grouped or exploded."""
    from core.outliner import in_component
    kids = [_cube((0, 0, 0)), _cube((3, 0, 0))]
    for k in kids:
        k.mesh = world_mesh(k)          # classic groups: world mesh, no matrix
        k.xform = None
    real = _cube((0, 0, 3))             # a component part stays a component
    box = Group(name="building")
    box.adopt(kids + [real])
    box.component = False
    scene = Scene()
    scene.groups.append(box)
    assert not any(k.is_component() for k in kids) and real.is_component()
    ExplodeViewCommand(box, 0.5).do(scene)
    assert not any(k.is_component() for k in kids)
    assert not any(in_component(scene.groups, k) for k in kids)
    assert real.is_component()
    ExplodeViewCommand(box, 0.0).do(scene)          # reassembled: still groups
    assert not any(k.is_component() for k in kids)
