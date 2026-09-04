# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Push/Pull on a component instance edits the shared definition: the push
runs inside a short editing session of that copy and, on commit, every
copy shows it (SketchUp's component semantics). Marco, 2026-09-04: 'hice
copias del componente, edito uno y los demás no cambian'."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group, world_mesh
from core.mesh import Mesh
from core.orient import is_closed, signed_volume
from tools.base import ToolContext
from tools.pushpull import PushPullTool


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _box(mesh, s=1.0):
    pts = [V(0, 0, 0), V(s, 0, 0), V(s, s, 0), V(0, s, 0),
           V(0, 0, s), V(s, 0, s), V(s, s, s), V(0, s, s)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
             (2, 3, 7, 6), (3, 0, 4, 7)]
    faces = [mesh.add_face([pts[i] for i in q]) for q in quads]
    return faces[1]                                   # the top face


def _ctx(vp, mods=Qt.NoModifier):
    return ToolContext(viewport=vp, world=V(0, 0), screen=QPointF(0, 0),
                       modifiers=mods, snap=None)


def _instances(scene):
    proto = Mesh()
    top = _box(proto)
    a, b = Group(proto, name="Pilar"), Group(proto, name="Pilar")
    xb = QMatrix4x4()
    xb.translate(3.0, 0.0, 0.0)
    a.xform, b.xform = QMatrix4x4(), xb
    scene.groups += [a, b]
    scene.version += 1
    return proto, top, a, b


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    return win, win.viewport


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_push_on_an_instance_reaches_every_copy():
    win, vp = _window()
    try:
        scene = vp.scene
        proto, top, a, b = _instances(scene)
        pp = PushPullTool()
        vp.active_tool = pp
        pp.hovered_face = top
        pp._hover_group = b
        pp.on_click(_ctx(vp))
        assert pp.dragging and pp._group is None
        assert scene.edit_group is b and b.xform is None       # session open
        assert pp.base_face in scene.mesh.faces
        assert abs(pp.base_face.centroid().x() - 3.5) < 1e-6    # world copy
        pp.extrusion = 2.0
        pp._commit(vp)
        assert scene.edit_group is None                         # session closed
        assert b.mesh is proto and b.xform is not None           # shared again
        assert a.mesh is proto
        assert is_closed(proto) and abs(signed_volume(proto) - 3.0) < 1e-6
        wa, wb = world_mesh(a), world_mesh(b)
        assert abs(signed_volume(wa) - 3.0) < 1e-6 and abs(signed_volume(wb) - 3.0) < 1e-6
        assert abs(max(v.position.x() for v in wb.vertices) - 4.0) < 1e-6
        assert any("copies" in m or "copias" in m for m in [win.statusBar().currentMessage()])
        # one undo step brings the definition back on both copies
        assert vp.history.undo()
        assert abs(signed_volume(proto) - 1.0) < 1e-6
        assert b.mesh is proto and b.xform is not None
        assert vp.history.redo()
        assert abs(signed_volume(proto) - 3.0) < 1e-6
    finally:
        _close(win)


def test_double_click_repeats_the_distance_on_another_instance():
    win, vp = _window()
    try:
        scene = vp.scene
        proto, top, a, b = _instances(scene)
        pp = PushPullTool()
        vp.active_tool = pp
        PushPullTool.last_distance = 1.5
        try:
            vp.pick_face_any = lambda x, y: (top, b)
            pp.on_double_click(_ctx(vp))
        finally:
            PushPullTool.last_distance = None
            del vp.pick_face_any
        assert scene.edit_group is None
        assert is_closed(proto) and abs(signed_volume(proto) - 2.5) < 1e-6
        assert a.mesh is proto and b.mesh is proto
    finally:
        _close(win)


def test_a_cancelled_push_leaves_the_instance_shared_and_untouched():
    win, vp = _window()
    try:
        scene = vp.scene
        proto, top, a, b = _instances(scene)
        pp = PushPullTool()
        vp.active_tool = pp
        pp.hovered_face = top
        pp._hover_group = b
        pp.on_click(_ctx(vp))
        assert scene.edit_group is b
        pp.on_cancel(vp)
        assert scene.edit_group is None
        assert b.mesh is proto and b.xform is not None
        assert abs(signed_volume(proto) - 1.0) < 1e-6
        assert not vp.history.undo_stack                        # nothing to undo
    finally:
        _close(win)
