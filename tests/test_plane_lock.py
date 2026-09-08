# SPDX-License-Identifier: GPL-3.0-or-later
"""Arrow keys before the first click lock a planar tool's drawing plane
(SketchUp; Marco, 2026-09-08: «quiero dibujar un círculo en el plano ZX…
me restringe a qué plano quiero dibujar apretando las teclas de
desplazamiento»)."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.history import History
from core.scene import Scene
from tools.arc import CenterArcTool
from tools.base import ToolContext
from tools.circle import CircleTool, PolygonTool
from tools.rectangle import RectangleTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _Stub:
    def __init__(self):
        self.scene = Scene()
        self.history = History(self.scene)
        self.flashed = []

    def update(self):
        pass

    def flash_status(self, text, msec=2500):
        self.flashed.append(text)


def _ctx(vp, p):
    return ToolContext(viewport=vp, world=p, screen=QPointF(),
                       modifiers=Qt.NoModifier, snap=None)


def test_left_arrow_locks_a_circle_to_the_xz_plane_and_the_shape_spends_it():
    vp = _Stub()
    tool = CircleTool()
    tool.on_activate(vp)
    assert tool.on_key(vp, int(Qt.Key_Left), Qt.NoModifier)
    assert tool.plane_lock == "y" and "XZ" in vp.flashed[-1]
    tool.on_click(_ctx(vp, V(1, 2, 3)))                 # the centre
    assert tool.work_plane[1] == V(0, 1, 0)
    # after the first click the arrows are not the tool's business
    assert not tool.on_key(vp, int(Qt.Key_Up), Qt.NoModifier)
    tool.on_click(_ctx(vp, V(2.5, 2, 3)))               # the rim
    faces = vp.scene.mesh.faces
    assert len(faces) == 1
    assert all(abs(v.y() - 2.0) < 1e-9 for v in faces[0].vertices)
    assert {round(v.z(), 6) for v in faces[0].vertices} != {3.0}
    assert tool.plane_lock is None and tool.work_plane is None   # spent


def test_same_arrow_again_frees_and_right_up_pick_the_other_planes():
    vp = _Stub()
    tool = PolygonTool()
    tool.on_activate(vp)
    tool.on_key(vp, int(Qt.Key_Right), Qt.NoModifier)
    assert tool.plane_lock == "x"
    tool.on_key(vp, int(Qt.Key_Right), Qt.NoModifier)
    assert tool.plane_lock is None and "free" in vp.flashed[-1].lower() \
        or "libre" in vp.flashed[-1].lower()
    tool.on_key(vp, int(Qt.Key_Up), Qt.NoModifier)
    assert tool.plane_lock == "z"
    assert not tool.on_key(vp, int(Qt.Key_Down), Qt.NoModifier)   # not ours
    tool.on_cancel(vp)
    assert tool.plane_lock is None                       # Esc releases it


def test_rectangle_and_centre_arc_lock_too():
    vp = _Stub()
    rect = RectangleTool()
    rect.on_activate(vp)
    rect.on_key(vp, int(Qt.Key_Right), Qt.NoModifier)   # normal X → YZ
    rect.on_click(_ctx(vp, V(0, 0, 0)))
    rect.on_click(_ctx(vp, V(0, 3, 2)))
    face = vp.scene.mesh.faces[-1]
    assert all(abs(v.x()) < 1e-9 for v in face.vertices)
    assert len({round(v.z(), 6) for v in face.vertices}) == 2
    arc = CenterArcTool()
    arc.on_activate(vp)
    arc.on_key(vp, int(Qt.Key_Left), Qt.NoModifier)
    arc.on_click(_ctx(vp, V(5, 5, 5)))
    assert arc.work_plane == (V(5, 5, 5), V(0, 1, 0))
