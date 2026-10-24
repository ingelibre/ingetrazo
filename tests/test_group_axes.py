# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #44 (@pacaeiro), phase 1: every group keeps its OWN axes.

A component instance always had them (its ``xform``). A classic group keeps
its mesh in world coordinates, so every Move/Rotate/Scale baked the turn
into the vertices and the group forgot which way it faced — the reason it
could not draw on its own axes. ``Group.axes`` carries them now, and the
edit stack reads each context's frame as it opens."""
from __future__ import annotations

import math

from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group, copy_group, frame_axes, group_frame
from core.history import (ExplodeGroupCommand, FlipGroupsCommand, History,
                          MoveGroupCommand, RotateGroupCommand,
                          ScaleGroupCommand)
from core.mesh import Mesh
from core.scene import Scene
from formats import igz


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _close(a, b, tol=1e-5):
    return (a - b).length() < tol


def _slab():
    m = Mesh()
    m.add_face([V(0, 0), V(2, 0), V(2, 1), V(0, 1)])
    return Group(m, name="slab")


def _red(g):
    return frame_axes(group_frame(g))[1]


def test_a_new_group_has_the_world_axes():
    g = _slab()
    assert group_frame(g) is None
    o, x, y, z = frame_axes(None)
    assert (x, y, z) == (V(1, 0, 0), V(0, 1, 0), V(0, 0, 1))


def test_rotate_carries_the_axes_and_undo_brings_them_back():
    scene = Scene()
    hist = History(scene)
    g = _slab()
    scene.groups.append(g)
    hist.execute(RotateGroupCommand(g, V(0, 0), V(0, 0, 1), 30.0))
    a = math.radians(30)
    assert _close(_red(g), V(math.cos(a), math.sin(a)))
    hist.undo()
    assert group_frame(g) is None
    hist.redo()
    assert _close(_red(g), V(math.cos(a), math.sin(a)))


def test_move_carries_the_origin():
    scene = Scene()
    hist = History(scene)
    g = _slab()
    scene.groups.append(g)
    hist.execute(RotateGroupCommand(g, V(0, 0), V(0, 0, 1), 90.0))
    hist.execute(MoveGroupCommand(g, V(5, 0, 1)))
    o, x, _y, _z = frame_axes(group_frame(g))
    assert _close(o, V(5, 0, 1)) and _close(x, V(0, 1))


def test_scale_keeps_the_directions_unit():
    scene = Scene()
    hist = History(scene)
    g = _slab()
    scene.groups.append(g)
    hist.execute(RotateGroupCommand(g, V(0, 0), V(0, 0, 1), 45.0))
    hist.execute(ScaleGroupCommand(g, V(0, 0), (3.0, 1.0, 1.0)))
    _o, x, y, z = frame_axes(group_frame(g))
    for a in (x, y, z):
        assert math.isclose(a.length(), 1.0, abs_tol=1e-6)
    assert abs(QVector3D.dotProduct(x, y)) < 1e-6


def test_flip_mirrors_the_axes_and_flips_back():
    scene = Scene()
    hist = History(scene)
    g = _slab()
    scene.groups.append(g)
    hist.execute(FlipGroupsCommand([g], V(0, 0), V(1, 0, 0)))
    assert _close(_red(g), V(-1, 0))
    hist.undo()
    assert _close(_red(g), V(1, 0))


def test_a_copy_takes_the_axes_along():
    g = _slab()
    turn = QMatrix4x4()
    turn.rotate(30.0, 0, 0, 1)
    g.axes = turn
    c = copy_group(g, V(10, 0))
    o, x, _y, _z = frame_axes(group_frame(c))
    assert _close(o, V(10, 0)) and _close(x, _red(g))
    assert c.axes is not g.axes


def test_the_axes_survive_the_igz(tmp_path):
    scene = Scene()
    g = _slab()
    turn = QMatrix4x4()
    turn.translate(1, 2, 3)
    turn.rotate(30.0, 0, 0, 1)
    g.axes = turn
    scene.groups.append(g)
    path = tmp_path / "ejes.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.groups[0].axes == turn


def test_make_unique_keeps_where_a_component_faced():
    proto = _slab().mesh
    inst = Group(proto, name="comp")
    turn = QMatrix4x4()
    turn.translate(4, 0, 0)
    turn.rotate(60.0, 0, 0, 1)
    inst.xform = QMatrix4x4(turn)
    inst.materialize()
    assert inst.xform is None and inst.axes == turn


def test_explode_lifts_a_child_with_its_axes_composed():
    scene = Scene()
    hist = History(scene)
    child = _slab()
    turn = QMatrix4x4()
    turn.rotate(30.0, 0, 0, 1)
    child.axes = QMatrix4x4(turn)
    box = Group(Mesh(), name="box")
    box.adopt([child])
    shift = QMatrix4x4()
    shift.translate(0, 5, 0)
    box.xform = shift
    scene.groups.append(box)
    hist.execute(ExplodeGroupCommand(box))
    o, x, _y, _z = frame_axes(group_frame(child))
    assert _close(o, V(0, 5)) and _close(x, _red_of(turn))
    hist.undo()
    assert child.axes == turn


def _red_of(m):
    return frame_axes(m)[1]


# ---- The edit stack reads each context's frame -------------------------------

def test_editing_a_turned_group_draws_on_its_axes():
    scene = Scene()
    g = _slab()
    turn = QMatrix4x4()
    turn.rotate(30.0, 0, 0, 1)
    g.axes = turn
    scene.groups.append(g)
    assert scene.drawing_frame is None
    scene.begin_group_edit(g)
    assert scene.drawing_frame == turn
    scene.end_group_edit()
    assert scene.drawing_frame is None


def test_editing_a_component_uses_its_placement_even_mid_edit():
    scene = Scene()
    inst = Group(_slab().mesh, name="comp")
    turn = QMatrix4x4()
    turn.translate(3, 0, 0)
    turn.rotate(45.0, 0, 0, 1)
    inst.xform = QMatrix4x4(turn)
    scene.groups.append(inst)
    scene.begin_group_edit(inst)
    assert inst.xform is None                 # the session edits a world copy
    assert scene.drawing_frame == turn        # …the axes are still its own


def test_nested_contexts_each_have_their_own_frame():
    scene = Scene()
    child = _slab()
    inner = QMatrix4x4()
    inner.rotate(30.0, 0, 0, 1)
    child.axes = QMatrix4x4(inner)
    box = Group(Mesh(), name="box")
    box.adopt([child])
    outer = QMatrix4x4()
    outer.translate(0, 5, 0)
    outer.rotate(90.0, 0, 0, 1)
    box.xform = QMatrix4x4(outer)
    scene.groups.append(box)
    scene.begin_group_edit(box)
    o, x, _y, _z = frame_axes(scene.drawing_frame)
    assert _close(o, V(0, 5)) and _close(x, V(0, 1))
    scene.begin_group_edit(child)             # one level down
    _o, x2, _y2, _z2 = frame_axes(scene.drawing_frame)
    assert _close(x2, _red_of(outer * inner))
    scene.end_one_group_edit()
    _o, x3, _y3, _z3 = frame_axes(scene.drawing_frame)
    assert _close(x3, V(0, 1))                # back to the container's
    scene.end_group_edit()
    assert scene.drawing_frame is None
    # the container kept its axes after its matrix went down to the child
    assert _close(frame_axes(group_frame(box))[1], V(0, 1))


# ---- Phase 3: the Scale box sits on the object's axes --------------------------

class _SelVP:
    def __init__(self, scene):
        self.scene = scene


def test_the_scale_box_of_a_turned_group_is_its_own_size():
    from tools.scale import ScaleTool
    scene = Scene()
    hist = History(scene)
    g = _slab()                                   # 2 x 1
    scene.groups.append(g)
    hist.execute(RotateGroupCommand(g, V(0, 0), V(0, 0, 1), 30.0))
    scene.selection = {g}
    tool = ScaleTool()
    lo, hi = tool._selection_bounds(_SelVP(scene))
    ext = hi - lo
    assert math.isclose(ext.x(), 2.0, abs_tol=1e-5)   # not the world AABB
    assert math.isclose(ext.y(), 1.0, abs_tol=1e-5)


def test_scaling_along_a_turned_red_stretches_only_that_way():
    from core.history import scale_matrix
    a = math.radians(30)
    x = V(math.cos(a), math.sin(a))
    y = V(-math.sin(a), math.cos(a))
    z = V(0, 0, 1)
    m = scale_matrix(V(0, 0), (2.0, 1.0, 1.0), (x, y, z))
    assert _close(m.map(x), x * 2.0)              # along red: doubled
    assert _close(m.map(y), y)                    # along green: untouched


def test_scale_group_command_along_its_axes_keeps_the_width():
    scene = Scene()
    hist = History(scene)
    g = _slab()                                   # 2 along x, 1 along y
    scene.groups.append(g)
    hist.execute(RotateGroupCommand(g, V(0, 0), V(0, 0, 1), 30.0))
    _o, x, y, z = frame_axes(group_frame(g))
    hist.execute(ScaleGroupCommand(g, V(0, 0), (3.0, 1.0, 1.0), (x, y, z)))

    def extent(axis):
        vals = [QVector3D.dotProduct(v.position, axis) for v in g.mesh.vertices]
        return max(vals) - min(vals)
    assert math.isclose(extent(x), 6.0, abs_tol=1e-4)
    assert math.isclose(extent(y), 1.0, abs_tol=1e-4)
    hist.undo()
    assert math.isclose(extent(x), 2.0, abs_tol=1e-4)


# ---- Phase 4: Change Axes ---------------------------------------------------------

def _world_pts(g):
    from core.group import world_mesh
    return sorted((round(v.position.x(), 5), round(v.position.y(), 5),
                   round(v.position.z(), 5)) for v in world_mesh(g).vertices)


def _frame_at(o, deg):
    m = QMatrix4x4()
    m.translate(o)
    m.rotate(deg, 0, 0, 1)
    return m


def test_change_axes_on_a_group_moves_nothing():
    from core.history import ChangeAxesCommand
    scene = Scene()
    hist = History(scene)
    g = _slab()
    scene.groups.append(g)
    before = _world_pts(g)
    new = _frame_at(V(2, 1), 45.0)
    hist.execute(ChangeAxesCommand(g, new))
    assert group_frame(g) == new and _world_pts(g) == before
    hist.undo()
    assert group_frame(g) is None


def test_change_axes_on_a_component_keeps_every_copy_in_place():
    from core.history import ChangeAxesCommand
    scene = Scene()
    hist = History(scene)
    proto = _slab().mesh
    a = Group(proto, name="a")
    a.xform = _frame_at(V(0, 0), 0.0)
    b = Group(proto, name="b")
    b.xform = _frame_at(V(10, 0), 90.0)
    scene.groups += [a, b]
    before_a, before_b = _world_pts(a), _world_pts(b)
    new = _frame_at(V(1, 0.5), 30.0)
    hist.execute(ChangeAxesCommand(a, new))
    assert _world_pts(a) == before_a and _world_pts(b) == before_b
    assert a.mesh is b.mesh is proto                  # still one definition
    assert _close(frame_axes(group_frame(a))[1], frame_axes(new)[1])
    # the copy's axes turned with the definition (30° on top of its 90°)
    assert _close(frame_axes(group_frame(b))[1],
                  frame_axes(_frame_at(V(0, 0), 120.0))[1])
    hist.undo()
    assert _world_pts(a) == before_a and _world_pts(b) == before_b
    assert _close(frame_axes(group_frame(a))[1], V(1, 0))


def test_change_axes_on_a_component_that_kept_its_group_axes_484():
    """A classic group with turned axes that became a component keeps
    those axes on top of its placement; Change Axes left them there, so the
    frame came out turned again — 180° on @jonson7777's chair, which read as
    «nothing changed»."""
    from core.history import ChangeAxesCommand
    scene = Scene()
    hist = History(scene)
    proto = _slab().mesh
    a = Group(proto, name="a")
    a.xform = _frame_at(V(0, 0), 0.0)
    a.axes = _frame_at(V(0, 0), 180.0)
    b = Group(proto, name="b")
    b.xform = _frame_at(V(10, 0), 90.0)
    b.axes = QMatrix4x4(a.axes)
    scene.groups += [a, b]
    before_a, before_b = _world_pts(a), _world_pts(b)
    old_a, old_b = group_frame(a), group_frame(b)
    new = _frame_at(V(1, 0.5), 30.0)
    hist.execute(ChangeAxesCommand(a, new))
    assert _world_pts(a) == before_a and _world_pts(b) == before_b
    for got, want in zip(frame_axes(group_frame(a)), frame_axes(new)):
        assert _close(got, want)
    hist.undo()
    assert _world_pts(a) == before_a and _world_pts(b) == before_b
    assert group_frame(a) == old_a and group_frame(b) == old_b


def test_the_tool_takes_origin_red_and_green():
    from PySide6.QtCore import QPointF, Qt
    from tools.base import ToolContext
    from tools.change_axes import ChangeAxesTool

    class _VP:
        def __init__(self, scene):
            self.scene = scene
            self.history = History(scene)

        def flash_status(self, *a, **k):
            pass

        def update(self):
            pass

    scene = Scene()
    g = _slab()
    scene.groups.append(g)
    vp = _VP(scene)
    tool = ChangeAxesTool()
    tool.target = g
    tool.on_activate(vp)
    for p in (V(2, 0), V(2, 5), V(0, 3)):         # origin, red, green
        tool.on_click(ToolContext(viewport=vp, world=p, screen=QPointF(0, 0),
                                  modifiers=Qt.NoModifier, snap=None))
    o, x, y, z = frame_axes(group_frame(g))
    assert _close(o, V(2, 0)) and _close(x, V(0, 1))
    assert _close(y, V(-1, 0)) and _close(z, V(0, 0, 1))


# ---- Phase 5: the .skp keeps a group turned -------------------------------------

def test_a_turned_group_survives_the_skp_round_trip(tmp_path):
    __import__("pytest").importorskip("openskp")
    from formats.skp import load_skp
    from formats.skp_out import save_skp
    scene = Scene()
    hist = History(scene)
    g = _slab()
    scene.groups.append(g)
    hist.execute(RotateGroupCommand(g, V(0, 0), V(0, 0, 1), 30.0))
    hist.execute(MoveGroupCommand(g, V(4, 1, 0)))
    before = _world_pts(g)
    path = tmp_path / "girado.skp"
    save_skp(scene, str(path))
    back = Scene()
    load_skp(back, str(path))
    assert len(back.groups) == 1
    h = back.groups[0]
    assert _world_pts(h) == before                       # same place
    a = math.radians(30)
    o, x, _y, _z = frame_axes(group_frame(h))
    assert _close(x, V(math.cos(a), math.sin(a)), 1e-4)  # same axes
    assert _close(o, frame_axes(group_frame(g))[0], 1e-4)


def test_a_flattened_skp_group_keeps_its_instance_axes():
    """The groups the .skp import flattens into world coordinates (tagged
    subtrees, containers of shared children) still face the way their
    .skp instance did."""
    from formats import skp as skp_format
    turn = _frame_at(V(3, 0), 30.0)
    square = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    pts = [tuple(turn.map(V(*p)).toTuple()) for p in square]
    payload = {"groups": [{"name": "girado", "faces": [(pts, [], {})],
                           "soft_edges": [],
                           "axes": [float(x) for x in turn.data()]}]}
    scene = Scene()
    skp_format.apply_payload(scene, payload)
    g = scene.groups[0]
    assert g.axes == turn and g.xform is None


def test_a_pasted_rotated_group_keeps_its_axes():
    """Issue #78 (@pacaeiro): Copy turns a classic group into an instance
    snapshot and Paste copies that — the instance copy dropped the local
    axes, so a pasted rotated group came back with the world's axes."""
    from PySide6.QtGui import QMatrix4x4, QVector3D as V
    from core.group import Group, copy_group, group_frame
    from core.history import RotateGroupCommand
    from core.mesh import Mesh
    from core.scene import Scene
    m = Mesh()
    m.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 1, 0), V(0, 1, 0)])
    g = Group(m)
    sc = Scene()
    sc.groups.append(g)
    RotateGroupCommand(g, V(0, 0, 0), V(0, 0, 1), 30.0).do(sc)
    tpl = copy_group(g)                       # what Copy snapshots
    if tpl.xform is None:
        tpl.xform = QMatrix4x4()
    pasted = copy_group(tpl, V(5, 0, 0))      # what Paste stamps
    red = group_frame(pasted).column(0).toVector3D()
    assert abs(red.x() - 0.866025) < 1e-4 and abs(red.y() - 0.5) < 1e-4
    assert group_frame(pasted).column(3).toVector3D() == V(5, 0, 0)
