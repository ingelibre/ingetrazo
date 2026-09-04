# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Editing INTO a component instance edits its shared definition: the
session works on a world copy, and leaving shares it back so every copy
shows the edit — one undo step for the whole session (SketchUp)."""
from __future__ import annotations

from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group, world_mesh
from core.history import History, ReshareInstanceCommand, SnapshotMutation
from core.mesh import Mesh
from core.scene import Scene


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _square(mesh, z=0.0):
    return mesh.add_face([V(0, 0, z), V(1, 0, z), V(1, 1, z), V(0, 1, z)])


def _two_instances():
    scene = Scene()
    proto = Mesh()
    _square(proto)
    a, b = Group(proto, name="a"), Group(proto, name="b")
    m = QMatrix4x4()
    m.translate(10.0, 0.0, 0.0)
    a.xform, b.xform = QMatrix4x4(), m
    scene.groups.extend([a, b])
    return scene, proto, a, b


def test_entering_edits_a_world_copy_and_leaving_shares_it_back():
    scene, proto, a, b = _two_instances()
    scene.begin_group_edit(b)
    assert scene.mesh is b.mesh and b.mesh is not proto and b.xform is None
    assert {round(v.position.x(), 3) for v in b.mesh.vertices} == {10.0, 11.0}
    assert len(proto.faces) == 1                       # definition untouched
    scene.mesh.add_face([V(10, 0, 1), V(11, 0, 1), V(11, 1, 1), V(10, 1, 1)])
    scene.end_group_edit()
    assert b.mesh is proto and b.xform is not None      # shared again
    assert len(proto.faces) == 2                        # …and edited
    zs = sorted({round(v.position.z(), 3) for v in proto.vertices})
    xs = sorted({round(v.position.x(), 3) for v in proto.vertices})
    assert zs == [0.0, 1.0] and xs == [0.0, 1.0]        # LOCAL coordinates
    assert len(world_mesh(a).faces) == 2                # the sibling shows it
    assert max(v.position.x() for v in world_mesh(b).vertices) == 11.0


def test_looking_without_editing_keeps_the_sharing_silently():
    scene, proto, a, b = _two_instances()
    scene.begin_group_edit(b)
    scene.end_group_edit()
    assert b.mesh is proto and b.xform is not None and len(proto.faces) == 1


def test_reshare_command_undoes_the_whole_session_in_one_step():
    scene, proto, a, b = _two_instances()
    hist = History(scene)
    scene.begin_group_edit(b)
    mark = len(hist.undo_stack)
    hist.execute(SnapshotMutation(lambda s: s.mesh.add_face(
        [V(10, 0, 1), V(11, 0, 1), V(11, 1, 1), V(10, 1, 1)])))
    hist.execute(SnapshotMutation(lambda s: s.mesh.add_face(
        [V(10, 0, 2), V(11, 0, 2), V(11, 1, 2), V(10, 1, 2)])))
    assert len(scene.mesh.faces) == 3
    share = scene.take_edit_share()
    group, proto2, xform, state0 = share
    assert group is b and proto2 is proto
    edited = b.mesh
    scene.end_group_edit()                              # share taken: no-op back
    inner = hist.undo_stack[mark:]
    del hist.undo_stack[mark:]
    hist.execute(ReshareInstanceCommand(b, proto, xform, edited, inner))
    assert len(proto.faces) == 3 and b.mesh is proto and b.xform is not None
    assert len(hist.undo_stack) == 1                    # the session = one step
    assert hist.undo()
    assert len(proto.faces) == 1 and b.mesh is proto and b.xform is not None
    assert len(world_mesh(a).faces) == 1
    assert hist.redo()
    assert len(proto.faces) == 3 and len(world_mesh(a).faces) == 3


def test_a_group_with_nested_placements_still_goes_unique():
    scene, proto, a, b = _two_instances()
    child = Group(Mesh(), name="child")
    _square(child.mesh, z=5.0)
    child.xform = QMatrix4x4()
    b.adopt([child])
    scene.begin_group_edit(b)
    assert scene._edit_share is None and b.xform is None
    scene.end_group_edit()
    assert b.mesh is not proto                          # unique, as before
    assert a.mesh is proto and len(proto.faces) == 1
