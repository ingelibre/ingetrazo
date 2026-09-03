# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Push/Pull on a component instance: the copy is made unique and pushed;
its siblings keep the shared prototype (Marco, 2026-09-03: after turning
the bench's repeated slats into components, Push/Pull on another slat
'did nothing')."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group
from core.history import History
from core.mesh import Mesh
from core.orient import is_closed, signed_volume
from core.scene import Scene
from tools.base import ToolContext
from tools.pushpull import PushPullTool


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.messages = []
        self._hit = None

    def update(self):
        pass

    def set_hover(self, *_):
        pass

    def set_suppressed_faces(self, *_):
        pass

    def flash_status(self, text, *a, **k):
        self.messages.append(text)

    def pick_face_any(self, x, y):
        return self._hit


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _box(mesh, size=1.0):
    s = size
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
    a, b = Group(proto, name="Listón"), Group(proto, name="Listón")
    xa, xb = QMatrix4x4(), QMatrix4x4()
    xb.translate(3.0, 0.0, 0.0)
    a.xform, b.xform = xa, xb
    scene.groups += [a, b]
    return proto, top, a, b


def test_push_on_an_instance_makes_that_copy_unique_and_pushes_it():
    scene = Scene()
    vp = _Vp(scene)
    proto, top, a, b = _instances(scene)
    pp = PushPullTool()
    pp.hovered_face = top
    pp._hover_group = b
    pp.on_click(_ctx(vp))
    assert pp.dragging and pp._group is b
    assert b.xform is None and b.mesh is not proto          # made unique
    assert pp.base_face in b.mesh.faces
    assert abs(pp.base_face.centroid().x() - 3.5) < 1e-6    # the world face
    assert any("unique" in m for m in vp.messages)
    pp.extrusion = 2.0
    pp._commit(vp)
    assert is_closed(b.mesh) and abs(signed_volume(b.mesh) - 3.0) < 1e-6
    assert a.mesh is proto and a.xform is not None            # sibling intact
    assert len(proto.faces) == 6 and abs(signed_volume(proto) - 1.0) < 1e-6
    # undo: the push, then the make-unique
    assert vp.history.undo()
    assert abs(signed_volume(b.mesh) - 1.0) < 1e-6
    assert vp.history.undo()
    assert b.mesh is proto and b.xform is not None


def test_double_click_repeats_the_distance_on_another_instance():
    scene = Scene()
    vp = _Vp(scene)
    proto, top, a, b = _instances(scene)
    pp = PushPullTool()
    PushPullTool.last_distance = 1.5
    vp._hit = (top, b)
    pp.on_double_click(_ctx(vp))
    assert b.xform is None and is_closed(b.mesh)
    assert abs(signed_volume(b.mesh) - 2.5) < 1e-6
    assert a.mesh is proto and abs(signed_volume(proto) - 1.0) < 1e-6
    PushPullTool.last_distance = None
