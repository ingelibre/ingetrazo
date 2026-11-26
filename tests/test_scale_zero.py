# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Scale 0 typed on some axes flattens loose geometry onto the anchor's
plane (#688): what lands on itself merges, squashed walls and faces that
land on another go. A 0 on every axis, or on a selection with groups, is
refused with a word in the status bar; dragging still stops at 0.0001."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import History, ScaleVerticesCommand
from core.scene import Scene
from tools.scale import ScaleTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _Stub:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.flashed = []

    def flash_status(self, msg, *a):
        self.flashed.append(msg)

    def update(self):
        pass


def _tool(scene, sel):
    vp = _Stub(scene)
    scene.selection.update(sel)
    tool = ScaleTool()
    tool.on_activate(vp)
    return tool, vp


def _grip(tool, params):
    return next(g for g in tool._grips if g.params == params)


def _wavy_quad(scene):
    """A roof quad whose corners sit at four different heights."""
    return scene.mesh.add_face([V(0, 0, 1.0), V(4, 0, 1.3),
                                V(4, 3, 0.8), V(0, 3, 1.1)])


def test_typed_zero_on_the_blue_grip_flattens_a_wavy_face():
    scene = Scene()
    f = _wavy_quad(scene)
    tool, vp = _tool(scene, [f])
    tool._grab(vp, _grip(tool, (0.5, 0.5, 1.0)), (0.0, 0.0))   # top: Z
    assert tool.on_value(vp, 0.0) is True
    zs = {round(v.position.z(), 6) for v in scene.mesh.vertices}
    assert zs == {0.8}                    # on the anchor's plane (the bottom)
    assert len(scene.mesh.faces) == 1
    assert abs(scene.mesh.faces[0].area() - 12.0) < 1e-4
    vp.history.undo()
    assert {round(v.position.z(), 6) for v in scene.mesh.vertices} == {
        1.0, 1.3, 0.8, 1.1}


def test_per_axis_zero_on_an_edge_grip_flattens_only_that_axis():
    scene = Scene()
    f = _wavy_quad(scene)
    tool, vp = _tool(scene, [f])
    grip = _grip(tool, (1.0, 0.5, 1.0))              # red + blue
    assert grip.mask == (0, 2)
    tool._grab(vp, grip, (0.0, 0.0))
    assert tool.on_value(vp, (1.0, 0.0)) is True     # keep red, flatten blue
    xs = sorted(round(v.position.x(), 6) for v in scene.mesh.vertices)
    assert xs == [0.0, 0.0, 4.0, 4.0]
    assert {round(v.position.z(), 6) for v in scene.mesh.vertices} == {0.8}


def test_typed_zero_with_a_unit_flattens_too():
    scene = Scene()
    f = _wavy_quad(scene)
    tool, vp = _tool(scene, [f])
    tool._grab(vp, _grip(tool, (0.5, 0.5, 1.0)), (0.0, 0.0))
    assert tool.on_value(vp, ("abs_len", 0.0)) is True
    assert {round(v.position.z(), 6) for v in scene.mesh.vertices} == {0.8}


def test_flattening_a_box_onto_its_floor_leaves_one_clean_face():
    scene = Scene()
    lo = [V(0, 0, 0), V(4, 0, 0), V(4, 3, 0), V(0, 3, 0)]
    hi = [V(p.x(), p.y(), 2.0) for p in lo]
    faces = [scene.mesh.add_face(lo), scene.mesh.add_face(hi)]
    for i in range(4):
        j = (i + 1) % 4
        faces.append(scene.mesh.add_face([lo[i], lo[j], hi[j], hi[i]]))
    hist = History(scene)
    hist.execute(ScaleVerticesCommand(lo + hi, V(0, 0, 0), (1.0, 1.0, 0.0)))
    assert len(scene.mesh.vertices) == 4
    assert len(scene.mesh.edges) == 4
    assert len(scene.mesh.faces) == 1
    assert all(e.length() > 0 for e in scene.mesh.edges)
    hist.undo()
    assert len(scene.mesh.faces) == 6
    assert len(scene.mesh.vertices) == 8


def test_zero_on_every_axis_is_refused():
    scene = Scene()
    f = _wavy_quad(scene)
    tool, vp = _tool(scene, [f])
    tool._grab(vp, _grip(tool, (1.0, 1.0, 1.0)), (0.0, 0.0))  # corner
    assert tool.on_value(vp, 0.0) is False
    assert vp.flashed[-1] == "Scale 0 on every axis would leave a point"
    assert not vp.history.undo_stack


def test_zero_with_a_group_is_refused():
    from core.group import Group
    from core.mesh import Mesh
    scene = Scene()
    m = Mesh()
    _wavy_quad(type("S", (), {"mesh": m})())
    g = Group(m, name="roof")
    scene.groups.append(g)
    tool, vp = _tool(scene, [g])
    tool._grab(vp, _grip(tool, (0.5, 0.5, 1.0)), (0.0, 0.0))
    assert tool.on_value(vp, 0.0) is False
    assert vp.flashed[-1] == "Scale 0 flattens loose geometry only, not groups"
    assert not vp.history.undo_stack


def test_tiny_nonzero_typed_is_still_refused():
    scene = Scene()
    f = _wavy_quad(scene)
    tool, vp = _tool(scene, [f])
    tool._grab(vp, _grip(tool, (0.5, 0.5, 1.0)), (0.0, 0.0))
    assert tool._typed_factors(0.00005, absolute=False) is None
    assert tool._typed_factors(0.0, absolute=False) == (1.0, 1.0, 0.0)


def test_hot_retype_to_zero_flattens_the_last_scale():
    scene = Scene()
    f = _wavy_quad(scene)
    tool, vp = _tool(scene, [f])
    tool._grab(vp, _grip(tool, (0.5, 0.5, 1.0)), (0.0, 0.0))
    assert tool.on_value(vp, 2.0) is True
    assert tool.on_value(vp, 0.0) is True     # retype: flatten instead
    assert {round(v.position.z(), 6) for v in scene.mesh.vertices} == {0.8}
    assert len(vp.history.undo_stack) == 1
