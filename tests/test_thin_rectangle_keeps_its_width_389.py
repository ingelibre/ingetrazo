# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A long thin rectangle keeps its width (issue #389).

@jonson7777: «making long thin rectangles are imposible, because curser
snaps to some purpel line and turns it into a line». The Rectangle's second
click is the OPPOSITE corner, so the span from the first corner to the
cursor is the rectangle's DIAGONAL. The snap engine read it as a line being
drawn: on a thin rectangle the diagonal runs a fraction of a degree off an
axis, and every inference that locks a line's direction or length — the
perpendicular off the wall it started on (magenta), 'from point', the
extension, parallel, through point, the Shift axis lock — pulled the far
corner onto a line through the first one. Width zero, nothing drawn.

The rectangle's sides run along the drawing plane's own axes by
construction, so per side the direction inferences are always met and
cannot move the corner. What can move it per side is a side's LENGTH lined
up with a point — the far corner level with an acquired corner — and those
inferences start at the cursor, not at the diagonal, so they stay. So do
the point snaps and the square.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D
from PySide6.QtWidgets import QApplication

from core.snap import compute_snap

_app = QApplication.instance() or QApplication([])

#: The kinds that hold the point on a line through the first corner.
_LINE_KINDS = {"axis", "axis_inference", "reference", "through_point",
               "extension", "perp_face", "from_point"}


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


# ---- The engine: each rule that read the diagonal as a line ---------------

def _w2p(p):
    return (p.x() * 100.0, -p.y() * 100.0)


def _edge(a, b):
    return SimpleNamespace(a=a, b=b)


START = V(0.0, 0.0)
CURSOR = V(4.0, 0.05)              # a 4 m x 5 cm rectangle, 0.7° off X


def _call(cursor=CURSOR, edges=(), **kw):
    return dict(
        candidate_world=cursor, candidate_pixel=_w2p(cursor),
        scene=SimpleNamespace(edges=list(edges)), world_to_pixel=_w2p,
        threshold_px=9.0, edge_threshold_px=14.0, start_point=START,
        project_onto_line=lambda s, d: s + d * QVector3D.dotProduct(
            cursor - s, d) / QVector3D.dotProduct(d, d),
        work_plane_normal=V(0, 0, 1), **kw)


RULES = {
    # 3: Shift held with the diagonal near an axis locks it to the axis.
    "shift_axis": (_call(shift_held=True), "axis"),
    # 4b: started on a wall, heading square to it — the purple line.
    "perpendicular_to_start_edge": (
        _call(edges=[_edge(V(0, -2), V(0, 3))]), "reference"),
    # 4e: heading through an acquired point far away along the diagonal.
    "through_point": (_call(acquired_point=V(80.0, 1.2)), "through_point"),
    # 5: the diagonal collinear with an edge, the cursor on its extension.
    "extension": (_call(edges=[_edge(V(-3, 0), V(-1, 0))]), "extension"),
    # 5b: the diagonal along an axis lines up with a corner's foot.
    "from_point": (_call(edges=[_edge(V(4, 2), V(4, 3))]), "from_point"),
    # 8b: parallel to an acquired off-axis edge.
    "parallel_to_acquired_edge": (
        _call(cursor=V(4.0, 0.4),
              acquired_edge=_edge(V(10, 10), V(20, 11.228))), "reference"),
    # 8c: square out of an acquired face.
    "perpendicular_to_face": (
        _call(acquired_face_normal=V(1, 0, 0)), "perp_face"),
    # 8d (two points): the first corner was encouraged before the click,
    # and the axis line through it crosses the one through another point.
    "two_points_through_the_start": (
        _call(acquired_points=[START, V(4.0, 2.0)]), "from_point"),
    # 9: the soft cue says «on red» about the diagonal — and Shift
    #    captures whatever cue is showing.
    "soft_axis_cue": (_call(), "axis_inference"),
}


@pytest.mark.parametrize("rule", list(RULES))
def test_the_diagonal_is_not_a_line(rule):
    call, kind = RULES[rule]
    line = compute_snap(**call)
    assert line.kind == kind, "the setup no longer fires the rule"
    cursor = call["candidate_world"]
    if kind != "axis_inference":       # the cue moves nothing; Shift does
        assert (line.point - cursor).length() > 1e-3, (
            "the rule is expected to move the point")

    corner = compute_snap(**call, diagonal_span=True)
    assert corner.kind not in _LINE_KINDS, corner.kind
    assert (corner.point - cursor).length() < 1e-9


def test_point_snaps_still_win_on_the_far_corner():
    call = _call(cursor=V(4.0, 0.03), edges=[_edge(V(4, 0), V(4, 3))])
    snap = compute_snap(**call, diagonal_span=True)
    assert snap.kind == "endpoint"
    assert (snap.point - V(4, 0)).length() < 1e-9


def test_the_far_corner_still_lines_up_with_an_acquired_point():
    """Per side: the far corner level with / in line with a corner the
    cursor visited — the length of one side taken from it, the other side
    left as the cursor has it."""
    call = _call(cursor=V(5.03, 0.05), acquired_point=V(5.0, 3.0))
    snap = compute_snap(**call, diagonal_span=True)
    assert snap.kind == "from_point"
    assert (snap.point - V(5.0, 0.05)).length() < 1e-6


# ---- The viewport: the Rectangle tool end to end ---------------------------

WALL = (V(0, -2), V(0, 5))         # the first corner goes on this line
POST = (V(5, 2), V(5, 4))          # a corner the far corner lines up with
FIRST = V(0, 1)
#: Half a screen pixel at this zoom, in metres (a pixel is ~9.4 mm).
_HALF_PX = 0.005


def _scene():
    from core.edits import build_add_edges
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.resize(1200, 800)
    _app.processEvents()
    vp = win.viewport
    vp.history.execute(build_add_edges(vp.scene, [WALL, POST]))
    vp.camera.set_view("top")
    vp.camera.target = V(2.5, 1.0, 0.0)
    vp.camera.distance = 8.0
    vp.scene.version += 1
    _app.processEvents()
    return win, vp


def _hover(vp, world):
    px, py = vp._world_to_pixel(world)
    vp._last_mouse_pos = QPointF(px, py)
    vp._refresh_snap()
    return px, py


def _press(vp, px, py):
    vp._dispatch_tool_click(QMouseEvent(
        QMouseEvent.MouseButtonPress, QPointF(px, py),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    _app.processEvents()


def _off_axis_px(vp, cursor):
    """How far the 5 cm width is on screen: under the snap radius, or the
    test proves nothing."""
    a = vp._world_to_pixel(V(cursor.x(), FIRST.y()))
    b = vp._world_to_pixel(cursor)
    return abs(b[1] - a[1])


@pytest.mark.parametrize("far, rule", [
    (V(4.0, 1.05), "reference"),       # square off the wall: the purple line
    (V(5.0, 1.05), "from_point"),      # the post's corner, foot on the diagonal
])
def test_a_thin_rectangle_keeps_its_width(far, rule, monkeypatch):
    # The hover reads the live modifiers: a Shift left over from another
    # test's last key event would lock the axis under this one.
    from PySide6.QtGui import QGuiApplication
    monkeypatch.setattr(QGuiApplication, "keyboardModifiers",
                        staticmethod(lambda: Qt.NoModifier))
    win, vp = _scene()
    try:
        assert _off_axis_px(vp, far) < vp.snap_threshold_px

        win._activate_tool("rectangle")
        _app.processEvents()
        _press(vp, *_hover(vp, FIRST))
        tool = vp.active_tool
        first = tool.start_point
        assert first is not None

        # Read as a line, the diagonal really is pulled onto the first
        # corner's row here: the bug as it was.
        tool.diagonal_span = False
        _hover(vp, far)
        assert vp.last_snap.kind == rule
        assert abs(tool.hover_point.y() - first.y()) < 1e-6
        del tool.diagonal_span

        # The cursor sits on a whole pixel, so the corner is the cursor's
        # own point within half a pixel (5 mm here) — and not on the row.
        px, py = _hover(vp, far)
        assert vp.last_snap.kind not in _LINE_KINDS, vp.last_snap.kind
        corner = QVector3D(tool.hover_point)
        assert abs(corner.y() - far.y()) < _HALF_PX
        assert abs(corner.x() - far.x()) < _HALF_PX

        before = len(vp.scene.mesh.faces)
        _press(vp, px, py)
        built = vp.scene.mesh.faces[before:]
        assert len(built) == 1
        assert built[0].area() == pytest.approx(
            abs((corner.x() - first.x()) * (corner.y() - first.y())),
            rel=1e-4)
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_the_far_corner_lines_up_with_a_visited_corner():
    """The cursor visits the post's top corner, then comes back down to
    give the strip its length: the far corner is held level with that
    corner along X — and the width stays the cursor's."""
    win, vp = _scene()
    try:
        win._activate_tool("rectangle")
        _app.processEvents()
        _press(vp, *_hover(vp, FIRST))
        vp.inference.acquire(*vp._world_to_pixel(POST[1]))
        assert vp.inference._acquired_point is not None

        _hover(vp, V(5.02, 1.05))
        assert vp.last_snap.kind == "from_point"
        point = vp.active_tool.hover_point
        assert abs(point.x() - 5.0) < 1e-6
        assert abs(point.y() - 1.05) < _HALF_PX
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_the_rotated_rectangle_reads_its_width_off_the_diagonal_too():
    """The Rotated Rectangle's base edge IS a line from the first corner
    (its inferences stay); its width is not. The snap still runs from the
    first corner, and where the second protractor is seen edge-on — a flat
    rectangle drawn from the top view — the tool takes the snapped point
    as it comes: square off the wall, the width came out zero."""
    win, vp = _scene()
    try:
        win._activate_tool("rotated_rect")
        _app.processEvents()
        tool = vp.active_tool
        _press(vp, *_hover(vp, FIRST))
        _press(vp, *_hover(vp, V(4.0, FIRST.y())))
        assert tool.base_point is not None

        _hover(vp, V(2.0, 1.05))
        assert vp.last_snap.kind not in _LINE_KINDS, vp.last_snap.kind
        width, _angle = tool._width_and_angle(tool.hover_point, tool._locked)
        # Both clicks sit on whole pixels: within a pixel of 5 cm.
        assert abs(width - 0.05) < 2 * _HALF_PX
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_the_rotated_rectangle_base_edge_keeps_its_line_inferences():
    """Only the width is a diagonal: the base edge is a line drawn from
    the first corner, and its axis and parallel inferences stay."""
    from tools.rotated_rectangle import RotatedRectangleTool
    tool = RotatedRectangleTool()
    assert not tool.diagonal_span
    tool.start_point = V(0, 0)
    assert not tool.diagonal_span
    tool.base_point = V(4, 0)
    assert tool.diagonal_span


def test_an_image_with_a_free_aspect_keeps_its_height():
    """The Image tool's second click is the opposite corner as well; with
    Shift's free aspect a thin strip lost its height the same way."""
    from tools.image import ImageTool
    win, vp = _scene()
    try:
        tool = ImageTool()
        tool.load("plan.png", 1.0)
        vp.set_active_tool(tool)
        _press(vp, *_hover(vp, FIRST))
        _hover(vp, V(4.0, 1.05))
        assert vp.last_snap.kind not in _LINE_KINDS, vp.last_snap.kind
        tool._free_aspect = True        # Shift, as the hover reads it
        _u, v = tool._frame(tool.start_point, tool.hover_point)
        assert abs(v.length() - 0.05) < 2 * _HALF_PX
    finally:
        win._saved_version = vp.scene.version
        win.close()
