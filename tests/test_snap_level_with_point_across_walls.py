# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A window on the NEXT wall, level with the one already drawn.

Rafael, 2026-09-16 (02:20), second review: the corner of the first window
gives its dotted line along its own wall «estupendamente», but to start a
window on another wall at the same height there was nothing — «que la
línea guía se extendiera por aquí y yo pudiera fijar la ventana aquí…
tampoco eso lo hace el programa clásico». It does not: 'from point' is the axis LINE
through the corner, which meets a perpendicular wall in one point and the
opposite wall never. The horizontal PLANE through the corner meets both
walls in a line, and that line is what the cursor now snaps to (rule 8e,
``"aligned"``, tip «A la altura del punto»).

And the rule it sits under stays on the face: an axis line running past a
wall in the air used to hand its foot back as a 'from point' — a point
off the wall the cursor was on.
"""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D
from PySide6.QtWidgets import QApplication

from core.scene import Scene
from core.snap import AXIS_COLORS, COLOR_ENDPOINT, compute_snap

_app = QApplication.instance() or QApplication([])


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


# ---- The engine in a vacuum ------------------------------------------------

def _w2p_plan(p):                 # looking down: x → right, y → up
    return (p.x() * 100.0, -p.y() * 100.0)


def _w2p_side(p):                 # from -y: x → right, z → up
    return (p.x() * 100.0, -p.z() * 100.0)


def _w2p_iso(p):                  # an isometric: no wall seen edge-on
    return ((p.x() - p.y()) * 86.6, -(p.z() + (p.x() + p.y()) * 0.5) * 100.0)


def _snap(scene, cand, w2p, **kw):
    return compute_snap(cand, w2p(cand), scene, w2p, threshold_px=9.0,
                        edge_threshold_px=14.0, face_under_cursor=True, **kw)


def test_level_with_the_corner_across_the_perpendicular_wall():
    # The corner sits on the front wall (y = 0); the cursor is on the right
    # wall (x = 8), 2 m along it, 3 cm above the corner's height.
    scene = Scene()
    ref = V(3.5, 0, 2.2)
    r = _snap(scene, V(8, 2.0, 2.23), _w2p_iso, acquired_point=ref,
              work_plane_normal=V(1, 0, 0))
    assert r.kind == "aligned" and r.axis == "z"
    assert (r.point - V(8, 2.0, 2.2)).length() < 1e-6      # on the wall, at the height
    assert r.color == COLOR_ENDPOINT
    # Two dotted guides walk the eye from the corner to the cursor: along
    # the front wall (red) to the junction, then along the right wall
    # (green) to the foot.
    elbow = V(8, 0, 2.2)
    assert (r.guide[0] - elbow).length() < 1e-6 and (r.guide[1] - r.point).length() < 1e-6
    assert r.guide_color == AXIS_COLORS["y"]
    (a, b, colour), = r.guides
    assert (a - ref).length() < 1e-6 and (b - elbow).length() < 1e-6
    assert colour == AXIS_COLORS["x"]


def test_level_with_the_corner_across_the_opposite_wall():
    # The far wall (y = 5) faces the corner's wall: no axis line through
    # the corner ever touches it, but the level line does.
    scene = Scene()
    ref = V(3.5, 0, 2.2)
    r = _snap(scene, V(6.0, 5, 2.17), _w2p_iso, acquired_point=ref,
              work_plane_normal=V(0, 1, 0))
    assert r.kind == "aligned" and r.axis == "z"
    assert (r.point - V(6.0, 5, 2.2)).length() < 1e-6
    (a, b, colour), = r.guides
    assert (a - ref).length() < 1e-6 and (b - V(3.5, 5, 2.2)).length() < 1e-6
    assert colour == AXIS_COLORS["y"]                      # straight across the room
    assert r.guide_color == AXIS_COLORS["x"]               # then along the far wall


def test_in_line_with_the_corner_on_the_floor_below_it():
    # A corner up on a wall and the cursor on the slab: the vertical axis
    # planes through it cut the slab in two lines, "in line with" it.
    scene = Scene()
    ref = V(3.5, 0, 2.2)
    r = _snap(scene, V(3.53, 2.0, 0), _w2p_plan, acquired_point=ref,
              work_plane_normal=V(0, 0, 1))
    assert r.kind == "aligned" and r.axis == "x"
    assert (r.point - V(3.5, 2.0, 0)).length() < 1e-6


def test_quiet_away_from_the_line_and_on_the_bare_ground():
    scene = Scene()
    ref = V(3.5, 0, 2.2)
    assert _snap(scene, V(8, 2.0, 2.5), _w2p_iso, acquired_point=ref,
                 work_plane_normal=V(1, 0, 0)).kind != "aligned"
    # Not a face under the cursor: the ground offers no line to run along.
    r = compute_snap(V(3.53, 2.0, 0), _w2p_plan(V(3.53, 2.0, 0)), scene,
                     _w2p_plan, threshold_px=9.0, acquired_point=ref,
                     work_plane_normal=V(0, 0, 1), face_under_cursor=False)
    assert r.kind != "aligned"


def test_on_the_corners_own_wall_the_axis_line_still_wins_unchanged():
    scene = Scene()
    ref = V(3.5, 0, 2.2)
    r = _snap(scene, V(6.0, 0, 2.23), _w2p_iso, acquired_point=ref,
              work_plane_normal=V(0, -1, 0))
    assert r.kind == "from_point"
    assert (r.point - V(6.0, 0, 2.2)).length() < 1e-6
    assert r.guide_color == AXIS_COLORS["x"]


def test_the_from_point_no_longer_leaves_the_wall_the_cursor_is_on():
    # The corner's red axis line runs on past its wall through the air,
    # parallel to a wall further back (y = 5). Seen from the front the two
    # overlap on screen, and the foot on that line is a point 5 m in
    # front of the wall the cursor is pointing at.
    scene = Scene()
    ref = V(3.5, 0, 2.2)
    cand = V(9.0, 5, 2.23)
    before = compute_snap(cand, _w2p_side(cand), scene, _w2p_side,
                          threshold_px=9.0, acquired_point=ref)
    assert before.kind == "from_point" and abs(before.point.y()) < 1e-9   # off the wall
    after = _snap(scene, cand, _w2p_side, acquired_point=ref,
                  work_plane_normal=V(0, 1, 0))
    assert after.kind == "aligned"                                       # on it, level
    assert abs(after.point.y() - 5.0) < 1e-6 and abs(after.point.z() - 2.2) < 1e-6


def test_a_line_piercing_the_face_offers_its_piercing_point():
    # The blue line through a corner in the air above a slab: on the slab
    # the only point of it is where it lands.
    scene = Scene()
    ref = V(3.5, 1.0, 2.2)
    r = _snap(scene, V(3.52, 1.03, 0), _w2p_plan, acquired_point=ref,
              work_plane_normal=V(0, 0, 1))
    assert r.kind == "from_point"
    assert (r.point - V(3.5, 1.0, 0)).length() < 1e-6
    assert r.guide_color == AXIS_COLORS["z"]


# ---- Rafael's room, through the real viewport ---------------------------------

def _room(win_on_front=True):
    """An 8 × 5 × 3 room open above, a 1.5 × 1.2 window on the front wall."""
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.resize(1600, 900)
    _app.processEvents()
    vp = win.viewport
    m = vp.scene.mesh
    W, D, H = 8.0, 5.0, 3.0
    m.add_face([V(0, 0, 0), V(W, 0, 0), V(W, D, 0), V(0, D, 0)])
    m.add_face([V(0, 0, 0), V(W, 0, 0), V(W, 0, H), V(0, 0, H)])       # front, y = 0
    m.add_face([V(W, 0, 0), V(W, D, 0), V(W, D, H), V(W, 0, H)])       # right, x = 8
    m.add_face([V(W, D, 0), V(0, D, 0), V(0, D, H), V(W, D, H)])       # far, y = 5
    m.add_face([V(0, D, 0), V(0, 0, 0), V(0, 0, H), V(0, D, H)])       # left, x = 0
    if win_on_front:
        m.add_face([V(2, 0, 1), V(3.5, 0, 1), V(3.5, 0, 2.2), V(2, 0, 2.2)])
    vp.scene.version += 1
    return win, vp


def _hover(vp, world):
    px = vp._world_to_pixel(world)
    assert px is not None
    vp._last_mouse_pos = QPointF(*px)
    vp._process_hover(QPointF(*px), Qt.NoModifier)
    return px


def _click(vp, px):
    vp._last_mouse_pos = QPointF(*px)
    vp._dispatch_tool_click(QMouseEvent(
        QMouseEvent.MouseButtonPress, QPointF(*px),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))


def test_the_window_on_the_next_wall_starts_level_with_the_first_one():
    win, vp = _room()
    try:
        cam = vp.camera
        cam.target = V(6, 2.5, 1.5)
        cam.distance = 16.0
        cam.pitch = math.radians(18.0)
        cam.yaw = math.radians(-55.0)                  # front and right walls in view
        vp.update()
        _app.processEvents()
        win._activate_tool("rectangle")
        vp.encourage_point(V(3.5, 0, 2.2))             # the first window's top corner
        faces_before = len(vp.scene.mesh.faces)
        # Along the right wall, 3 cm above the height: the tip says level.
        px = _hover(vp, V(8, 2.5, 2.23))
        s = vp.last_snap
        assert s.kind == "aligned" and s.axis == "z", s.kind
        assert abs(s.point.x() - 8.0) < 1e-6 and abs(s.point.z() - 2.2) < 1e-6
        _click(vp, px)
        far = _hover(vp, V(8, 4.0, 1.0))
        _click(vp, far)
        assert len(vp.scene.mesh.faces) == faces_before + 1
        # The window, not the wall it was cut out of: the wall's plane is
        # rebuilt after a rectangle (#538), so the list order says nothing.
        new = next(f for f in vp.scene.mesh.faces
                   if not f.holes and len(f.vertices) == 4
                   and {round(v.x(), 6) for v in f.vertices} == {8.0}
                   and max(v.y() for v in f.vertices) < 5.0 - 1e-6)
        zs = sorted({round(v.z(), 6) for v in new.vertices})
        xs = {round(v.x(), 6) for v in new.vertices}
        assert xs == {8.0}, xs                          # on the right wall
        assert zs[-1] == 2.2, zs                        # its top level with the first
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_the_opposite_wall_too_where_no_axis_line_reaches():
    win, vp = _room()
    try:
        cam = vp.camera
        cam.target = V(4, 2.5, 1.5)
        cam.distance = 14.0
        cam.pitch = math.radians(35.0)
        cam.yaw = math.radians(-100.0)                 # looking in over the front wall
        vp.update()
        _app.processEvents()
        win._activate_tool("rectangle")
        vp.encourage_point(V(3.5, 0, 2.2))
        for x in (1.2, 4.0, 6.8):
            _hover(vp, V(x, 5, 2.22))
            s = vp.last_snap
            assert s.kind == "aligned", (x, s.kind)
            assert abs(s.point.y() - 5.0) < 1e-6 and abs(s.point.z() - 2.2) < 1e-6
        # Well off the height: nothing but the wall.
        _hover(vp, V(4.0, 5, 1.5))
        assert vp.last_snap.kind == "on_face"
    finally:
        win._saved_version = vp.scene.version
        win.close()
