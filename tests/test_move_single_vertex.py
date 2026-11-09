# SPDX-License-Identifier: GPL-3.0-or-later
"""Move, with nothing selected, takes the ONE vertex under an Endpoint snap
— and the drag no longer shakes.

Testing the join guard, the user found two things: grabbing a corner of a
box dragged the whole edge (the pick under the cursor is the edge), and the
geometry trembled while dragging. The tremble was a loop: the cursor landed
on the plane of a face the drag itself was bending, the vertex followed
the cursor, the face tilted, and the next hover read a different plane."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.history import History
from core.scene import Scene
from core.snap import SnapResult
from tools.base import ToolContext
from tools.move import MoveTool

_app = QApplication.instance() or QApplication([])

P = [V(0, 0, 0), V(3, 0, 0), V(3, 4, 0), V(0, 4, 0),
     V(0, 0, 2.6), V(3, 0, 2.6), V(3, 4, 2.6), V(0, 4, 2.6)]
_FACES = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
          (2, 3, 7, 6), (3, 0, 4, 7))


def _box(scene):
    for idx in _FACES:
        scene.mesh.add_face([P[i] for i in idx])


# ---- the grab, without a window -------------------------------------------

class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.said = []

    def update(self):
        pass

    def flash_status(self, text, *ms):
        self.said.append(text)

    def pick_edge(self, x, y):
        # The pick under the cursor: the vertical edge at the corner.
        return self.scene.mesh.find_edge(self.scene.mesh.vertex_at(P[6]),
                                         self.scene.mesh.vertex_at(P[2]))

    def pick_face(self, x, y):
        return None

    def pick_group(self, x, y):
        return None


def _ctx(vp, world, kind="endpoint", context=None):
    snap = SnapResult(V(world), kind)
    snap.context = context
    return ToolContext(viewport=vp, world=V(world), screen=QPointF(0, 0),
                       modifiers=Qt.NoModifier, snap=snap)


def _grabbed(tool):
    return sorted((round(p.x(), 4), round(p.y(), 4), round(p.z(), 4))
                  for p in tool._positions)


def test_a_corner_grabs_only_its_vertex():
    sc = Scene()
    _box(sc)
    vp = _Vp(sc)
    tool = MoveTool()
    tool.on_click(_ctx(vp, P[6]))
    assert _grabbed(tool) == [(3.0, 4.0, 2.6)]
    assert len(tool._verts) == 1


def test_off_a_corner_it_still_grabs_the_edge():
    sc = Scene()
    _box(sc)
    vp = _Vp(sc)
    tool = MoveTool()
    tool.on_click(_ctx(vp, V(3, 4, 1.0), kind="on_edge"))
    assert _grabbed(tool) == [(3.0, 4.0, 0.0), (3.0, 4.0, 2.6)]


def test_a_selection_wins_over_the_corner():
    sc = Scene()
    _box(sc)
    top = next(f for f in sc.mesh.faces
               if all(abs(p.z() - 2.6) < 1e-6 for p in f.vertices))
    sc.selection = [top]
    vp = _Vp(sc)
    tool = MoveTool()
    tool.on_click(_ctx(vp, P[6]))
    assert len(tool._positions) == 4


def test_a_corner_of_a_group_is_not_a_loose_vertex():
    sc = Scene()
    _box(sc)
    vp = _Vp(sc)
    assert MoveTool._hovered_vertex(_ctx(vp, P[6], context="group")) is None


def test_the_single_vertex_moves_and_joins():
    sc = Scene()
    _box(sc)
    vp = _Vp(sc)
    tool = MoveTool()
    tool.on_click(_ctx(vp, P[6]))
    tool.on_click(_ctx(vp, P[7]))            # onto its neighbour on top
    assert vp.history.last_rejected is None
    assert len(sc.mesh.vertices) == 7
    assert vp.said == ["Vertices joined"]


def test_the_single_vertex_moves_alone():
    sc = Scene()
    _box(sc)
    vp = _Vp(sc)
    tool = MoveTool()
    tool.on_click(_ctx(vp, P[6]))
    tool.on_click(_ctx(vp, V(3, 4, 3.6), kind="none"))
    zs = sorted(round(v.position.z(), 4) for v in sc.mesh.vertices)
    assert zs == [0.0, 0.0, 0.0, 0.0, 2.6, 2.6, 2.6, 3.6]
    assert vp.said == []


def test_the_faces_in_motion_are_the_ones_on_the_grabbed_corner():
    sc = Scene()
    _box(sc)
    vp = _Vp(sc)
    tool = MoveTool()
    assert tool.moving_face_ids() == set()        # nothing grabbed yet
    tool.on_click(_ctx(vp, P[6]))
    corner = sc.mesh.vertex_at(P[6])
    assert tool.moving_face_ids() == {id(f) for f in corner.faces()}
    assert len(tool.moving_face_ids()) == 3


# ---- the drag, in a real viewport -----------------------------------------

def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    _app.processEvents()
    vp = win.viewport
    _box(vp.scene)
    vp.scene.version += 1
    _app.processEvents()
    win._activate_tool("move")
    return win, vp


def _close(win, vp):
    win._saved_version = vp.scene.version
    win.close()


def _hover(vp, x, y):
    vp._last_mouse_pos = QPointF(x, y)
    vp._refresh_snap()
    s = vp.last_snap
    return s.kind, (round(s.point.x(), 4), round(s.point.y(), 4),
                    round(s.point.z(), 4))


def _click(vp, x, y):
    _hover(vp, x, y)
    vp._dispatch_tool_click(QMouseEvent(
        QMouseEvent.MouseButtonPress, QPointF(x, y), Qt.LeftButton,
        Qt.LeftButton, Qt.NoModifier))


def test_in_the_viewport_a_corner_grabs_one_vertex():
    win, vp = _window()
    try:
        x, y = vp._world_to_pixel(P[6])
        assert _hover(vp, x, y)[0] == "endpoint"
        _click(vp, x, y)
        assert _grabbed(vp.active_tool) == [(3.0, 4.0, 2.6)]
    finally:
        _close(win, vp)


def test_the_drag_reads_the_same_point_coming_and_going():
    """The tremble: the point under a pixel depended on where the bent
    face stood after the previous hover. Now each pixel gives one point,
    whichever way the mouse came."""
    win, vp = _window()
    try:
        x, y = vp._world_to_pixel(P[6])
        _click(vp, x, y)
        path = [(x + 3 * i, y - 4 * i) for i in range(12)]
        going = [_hover(vp, *p) for p in path]
        coming = [_hover(vp, *p) for p in reversed(path)][::-1]
        assert going == coming
        assert not any(kind == "on_face" for kind, _p in going + coming)
        still = {_hover(vp, x + 25, y - 30) for _ in range(5)}
        assert len(still) == 1
    finally:
        _close(win, vp)
