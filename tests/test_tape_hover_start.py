# SPDX-License-Identifier: GPL-3.0-or-later
"""T over a line starts a guide without a separate first mouse click."""
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D as V


@pytest.fixture
def setup(monkeypatch):
    from core.mesh import Mesh
    from views.main_window import MainWindow
    win = MainWindow(defer_extensions=True)
    vp = win.viewport
    vp.resize(800, 600)
    vp.scene.mesh = Mesh()
    vp.scene.groups = []
    vp.scene.mesh.add_face([V(0,0,0), V(4,0,0), V(4,3,0), V(0,3,0)])
    vp.scene.version += 1
    vp.camera.set_aspect(800, 600)
    vp.camera.set_view('top')
    vp.camera.perspective = False
    vp.camera.fit_to(V(-2,-2,-.1), V(6,5,.1))
    pointer = [vp._world_to_pixel(V(2,0,0))]
    # Emulate the position read by the shortcut without moving the real mouse.
    monkeypatch.setattr(vp, 'mapFromGlobal',
                        lambda _global: QPoint(round(pointer[0][0]), round(pointer[0][1])))
    yield win, vp, pointer
    win._saved_version = vp.scene.version
    win.close()


def _move(vp, point):
    pixel = vp._world_to_pixel(point)
    ev = QMouseEvent(QMouseEvent.MouseMove, QPointF(*pixel), QPointF(*pixel),
                     Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    vp.mouseMoveEvent(ev)
    vp._run_pending_hover()
    return pixel


def _click(vp, pixel):
    for kind, buttons in ((QMouseEvent.MouseButtonPress, Qt.LeftButton),
                           (QMouseEvent.MouseButtonRelease, Qt.NoButton)):
        vp_event = QMouseEvent(kind, QPointF(*pixel), QPointF(*pixel),
                               Qt.LeftButton, buttons, Qt.NoModifier)
        (vp.mousePressEvent if buttons else vp.mouseReleaseEvent)(vp_event)


@pytest.mark.parametrize('source', ['loose', 'group', 'guide', 'axis'])
def test_T_over_an_edge_starts_the_parallel_preview_and_one_click_places_it(setup, source):
    win, vp, pointer = setup
    if source == 'group':
        from core.group import Group
        from core.mesh import Mesh
        vp.scene.groups = [Group(vp.scene.mesh)]
        vp.scene.mesh = Mesh()
        vp.scene.version += 1
    elif source == 'guide':
        from core.guide import Guide
        from core.mesh import Mesh
        vp.scene.mesh = Mesh()
        vp.scene.guides = [Guide(V(), V(1,0,0))]
        vp.scene.version += 1
    elif source == 'axis':
        from core.mesh import Mesh
        vp.scene.mesh = Mesh()
        vp.scene.version += 1
    count = len(vp.scene.guides)
    win._activate_tool('tape')  # the same route as its shortcut action
    tool = vp.active_tool
    assert tool.start_point is not None
    assert tool._edge is not None
    assert len(vp.scene.guides) == count  # activation only starts a preview
    end = _move(vp, V(2,-1,0))
    assert tool.guide_preview_lines()
    _click(vp, end)
    assert len(vp.scene.guides) == count + 1
    assert tool.start_point is None
    vp.history.undo()
    assert len(vp.scene.guides) == count


def test_hover_start_accepts_a_typed_offset_and_escape_cancels_it(setup):
    win, vp, pointer = setup
    win._activate_tool('tape')
    assert vp.active_tool._edge is not None
    _move(vp, V(2,-1,0))
    assert vp.active_tool.on_value(vp, .75)
    assert abs(vp.scene.guides[-1].point.y()+.75) < 1e-5
    before = len(vp.history.undo_stack)
    win._activate_tool('tape')  # picking T again also starts from the hovered source
    assert vp.active_tool._edge is not None
    vp.active_tool.on_cancel(vp)
    assert vp.active_tool.start_point is None
    assert len(vp.history.undo_stack) == before


@pytest.mark.parametrize('where', ['empty', 'endpoint', 'outside'])
def test_T_elsewhere_keeps_the_normal_first_click_workflow(setup, where):
    win, vp, pointer = setup
    point = V(5,4,0) if where == 'empty' else V(0,0,0)
    pointer[0] = (-20,-20) if where == 'outside' else vp._world_to_pixel(point)
    win._activate_tool('tape')
    assert vp.active_tool.start_point is None
    assert not vp.scene.guides
