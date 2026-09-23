# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SketchUp's Position Camera / Look Around / Walk (tools/walkthrough.py) —
Rafael's «pasitos» for looking at interiors (2026-09-16, 13:00), built to
help.sketchup.com «Walking through a Model» and to Marco's recording of
SketchUp's status bar.
"""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from core.camera import OrbitCamera
from tools.base import ToolContext
from tools import walkthrough as wt
from tools.walkthrough import (LookAroundTool, PositionCameraTool, WalkTool,
                               eye_height)


@pytest.fixture(autouse=True)
def _default_eye_height(monkeypatch):
    monkeypatch.setattr(wt, "eye_height", lambda: 1.68)
    monkeypatch.setattr(wt, "set_eye_height", lambda v: None)


# ---- The camera --------------------------------------------------------------

def test_look_from_puts_the_eye_there_looking_that_way():
    cam = OrbitCamera()
    cam.look_from(QVector3D(3, 4, 1.7), QVector3D(0, 1, 0))
    assert (cam.eye() - QVector3D(3, 4, 1.7)).length() < 1e-5
    assert (cam.forward() - QVector3D(0, 1, 0)).length() < 1e-6


def test_turn_swings_the_look_and_keeps_the_eye():
    cam = OrbitCamera()
    cam.look_from(QVector3D(0, 0, 1.7), QVector3D(0, 1, 0))
    cam.turn(90.0, 0.0)                      # turn right: north → east
    assert (cam.forward() - QVector3D(1, 0, 0)).length() < 1e-6
    assert (cam.eye() - QVector3D(0, 0, 1.7)).length() < 1e-5
    cam.turn(0.0, 30.0)                      # look up
    assert abs(math.degrees(math.asin(cam.forward().z())) - 30.0) < 1e-6


# ---- A room to walk in ---------------------------------------------------------

def _room(vp):
    """A 6 × 6 m room, walls 3 m tall, a 0.3 m step inside, on the ground."""
    mesh = vp.scene.mesh
    floor = [QVector3D(0, 0, 0), QVector3D(6, 0, 0), QVector3D(6, 6, 0),
             QVector3D(0, 6, 0)]
    mesh.add_face(floor)
    for a, b in zip(floor, floor[1:] + floor[:1]):
        mesh.add_face([a, b, QVector3D(b.x(), b.y(), 3.0),
                       QVector3D(a.x(), a.y(), 3.0)])
    # a step: 1 m deep, 0.3 m high, across the room at y = 4..5
    P = [QVector3D(0, 4, 0), QVector3D(6, 4, 0), QVector3D(6, 5, 0),
         QVector3D(0, 5, 0)]
    T = [QVector3D(p.x(), p.y(), 0.3) for p in P]
    mesh.add_face(T)
    for a, b, c, d in zip(P, P[1:] + P[:1], T[1:] + T[:1], T):
        mesh.add_face([a, b, c, d])
    vp.scene.version += 1
    vp.update()
    _app.processEvents()


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.resize(1200, 800)
    _app.processEvents()
    return win


def _ctx(vp, world, screen=None, mods=Qt.NoModifier):
    world = QVector3D(*world) if isinstance(world, tuple) else world
    if screen is None:
        px = vp._world_to_pixel(world)
        screen = QPointF(*px)
    return ToolContext(viewport=vp, world=world, screen=screen,
                       modifiers=mods, snap=None)


def test_position_camera_click_stands_the_eye_above_the_point():
    win = _window()
    vp = win.viewport
    try:
        _room(vp)
        vp.camera.perspective = False            # a plan view…
        win._activate_tool("position_camera")
        tool = vp.active_tool
        assert isinstance(tool, PositionCameraTool)
        tool.on_click(_ctx(vp, (3, 2, 0)))
        tool.on_release(vp)
        eye = vp.camera.eye()
        assert (eye - QVector3D(3, 2, 1.68)).length() < 1e-4
        assert abs(vp.camera.forward().z()) < 1e-6   # looking level
        assert vp.camera.perspective                 # …becomes a walk
        # SketchUp hands over to Look Around.
        assert isinstance(vp.active_tool, LookAroundTool)
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_position_camera_drag_looks_at_the_point_dragged_to():
    win = _window()
    vp = win.viewport
    try:
        _room(vp)
        win._activate_tool("position_camera")
        tool = vp.active_tool
        tool.on_click(_ctx(vp, (3, 1, 0), QPointF(100, 100)))
        tool.on_hover(_ctx(vp, (3, 5, 0), QPointF(160, 140)))   # a real drag
        tool.on_release(vp)
        eye = vp.camera.eye()
        assert (eye - QVector3D(3, 1, 1.68)).length() < 1e-4
        want = (QVector3D(3, 5, 0) - eye).normalized()
        assert (vp.camera.forward() - want).length() < 1e-4
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_typed_height_offset_and_eye_height_move_the_eye():
    win = _window()
    vp = win.viewport
    try:
        _room(vp)
        win._activate_tool("position_camera")
        tool = vp.active_tool
        tool.on_click(_ctx(vp, (3, 2, 0)))
        tool.on_release(vp)
        assert tool.on_value(vp, 2.0)              # «Height offset»
        assert abs(vp.camera.eye().z() - 2.0) < 1e-4
        look = vp.active_tool                      # Look Around now
        assert look.on_value(vp, 1.2)              # «Eye height»
        assert abs(vp.camera.eye().z() - 1.2) < 1e-4
        assert look.value_label()[0] == "1.20 m"
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_look_around_turns_the_head_where_the_drag_goes():
    win = _window()
    vp = win.viewport
    try:
        _room(vp)
        vp.camera.look_from(QVector3D(3, 3, 1.68), QVector3D(0, 1, 0))
        win._activate_tool("look_around")
        tool = vp.active_tool
        w = vp.width()
        tool.on_click(_ctx(vp, (0, 0, 0), QPointF(100, 300)))
        tool.on_hover(_ctx(vp, (0, 0, 0), QPointF(100 + w / 4.0, 300)))
        tool.on_release(vp)
        # a quarter of the width to the right = 45° to the right
        f = vp.camera.forward()
        assert abs(math.degrees(math.atan2(f.x(), f.y())) - 45.0) < 1e-3
        assert (vp.camera.eye() - QVector3D(3, 3, 1.68)).length() < 1e-4
        tool.on_click(_ctx(vp, (0, 0, 0), QPointF(100, 300)))
        tool.on_hover(_ctx(vp, (0, 0, 0), QPointF(100, 300 - vp.height() / 3.0)))
        tool.on_release(vp)
        assert abs(math.degrees(math.asin(vp.camera.forward().z())) - 30.0) < 1e-3
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_walk_forward_stops_at_the_wall_and_alt_goes_through():
    win = _window()
    vp = win.viewport
    try:
        _room(vp)
        vp.camera.look_from(QVector3D(3, 3, 1.68), QVector3D(1, 0, 0))  # toward x = 6
        win._activate_tool("walk")
        tool = vp.active_tool
        assert isinstance(tool, WalkTool)
        for _ in range(200):                         # 200 × 0.1 s at full speed
            tool.step(vp, 0.0, tool.FULL_PX, 0.1)
        eye = vp.camera.eye()
        assert eye.x() < 6.0 - tool.CLEARANCE + 1e-3
        assert eye.x() > 5.0                         # it did walk up to it
        assert abs(eye.z() - 1.68) < 1e-4           # eye height kept
        for _ in range(20):
            tool.step(vp, 0.0, tool.FULL_PX, 0.1, Qt.AltModifier)
        assert vp.camera.eye().x() > 6.0             # through the wall
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_walk_climbs_the_step_and_keeps_the_eye_height_over_it():
    win = _window()
    vp = win.viewport
    try:
        _room(vp)
        vp.camera.look_from(QVector3D(3, 2, 1.68), QVector3D(0, 1, 0))  # toward the step
        win._activate_tool("walk")
        tool = vp.active_tool
        for _ in range(17):                          # 17 × 0.15 m = 2.55 m
            tool.step(vp, 0.0, tool.FULL_PX, 0.1)
        eye = vp.camera.eye()
        assert 4.0 < eye.y() < 5.0                   # standing on the step…
        assert abs(eye.z() - (0.3 + 1.68)) < 1e-3   # …eye height above it
        for _ in range(8):                           # …and off the far side
            tool.step(vp, 0.0, tool.FULL_PX, 0.1)
        eye = vp.camera.eye()
        assert eye.y() > 5.0 and abs(eye.z() - 1.68) < 1e-3   # back down
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_walk_turns_runs_and_shift_moves_vertically():
    win = _window()
    vp = win.viewport
    try:
        _room(vp)
        vp.camera.look_from(QVector3D(3, 3, 1.68), QVector3D(0, 1, 0))
        win._activate_tool("walk")
        tool = vp.active_tool
        tool.step(vp, tool.FULL_PX, 0.0, 0.5)          # right: turn 30°
        f = vp.camera.forward()
        assert abs(math.degrees(math.atan2(f.x(), f.y())) - 30.0) < 1e-3
        vp.camera.look_from(QVector3D(3, 1, 1.68), QVector3D(0, 1, 0))
        tool.step(vp, 0.0, tool.FULL_PX, 0.2)          # walk 0.3 m
        tool.step(vp, 0.0, tool.FULL_PX, 0.2, Qt.ControlModifier)   # run 0.9 m
        assert abs(vp.camera.eye().y() - (1 + 0.3 + 0.9)) < 1e-3
        tool.step(vp, 0.0, tool.FULL_PX, 0.2, Qt.ShiftModifier)     # up 0.3 m
        assert abs(vp.camera.eye().z() - (1.68 + 0.3)) < 1e-3
        tool.step(vp, tool.FULL_PX, 0.0, 0.2, Qt.ShiftModifier)     # sideways 0.3 m
        assert abs(vp.camera.eye().x() - 3.3) < 1e-3
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_walk_stroke_starts_and_stops_the_timer_and_draws_the_crosshair():
    win = _window()
    vp = win.viewport
    try:
        _room(vp)
        win._activate_tool("walk")
        tool = vp.active_tool
        tool.on_click(_ctx(vp, (0, 0, 0), QPointF(400, 300)))
        assert tool.walking and tool._timer is not None and tool._timer.isActive()
        tool.on_release(vp)
        assert not tool.walking and not tool._timer.isActive()
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_the_three_tools_are_in_the_camera_menu_and_the_walkthrough_toolbar():
    win = _window()
    try:
        assert "walkthrough" in win.toolbars
        keys = [a.text() for a in win.toolbars["walkthrough"].actions()]
        assert keys == ["Position Camera", "Walk", "Look Around"]
        camera_menu = [m for m in win.menuBar().findChildren(type(win.menuBar().actions()[0].menu()))
                       if m.title() == "Camera"][0]
        texts = [a.text() for a in camera_menu.actions()]
        assert "Position Camera" in texts and "Walk" in texts and "Look Around" in texts
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_look_around_and_walk_keep_hearing_the_cursor_above_the_horizon():
    """The Push/Pull lesson: the viewport builds no event when the cursor
    ray misses the work plane. These two read pixels, so they hand the
    viewport a plane facing the camera that every ray hits."""
    win = _window()
    vp = win.viewport
    try:
        _room(vp)
        vp.camera.look_from(QVector3D(3, 3, 1.68), QVector3D(0, 1, 0))
        for key in ("look_around", "walk"):
            win._activate_tool(key)
            assert vp._world_from_pixel(vp.width() // 2, 5) is not None   # the sky
        win._activate_tool("position_camera")
        assert vp.active_tool.drag_plane(vp) is None
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_eye_height_readout_goes_to_the_box_and_the_overlay_skips_it():
    """The three tools read the eye height with no world point to hang it
    on — ``value_label`` gives ``(text, None)``. The Measurements box shows
    the text; the floating label has nowhere to go and must say nothing
    (it used to hand ``None`` to ``_world_to_pixel`` and kill every paint)."""
    from PySide6.QtGui import QImage, QPainter
    win = _window()
    vp = win.viewport
    try:
        _room(vp)
        for key in ("position_camera", "look_around", "walk"):
            win._activate_tool(key)
            text, anchor = vp.active_tool.value_label()
            assert anchor is None
            assert vp._measurement_text() == text
            img = QImage(64, 64, QImage.Format_ARGB32)
            painter = QPainter(img)
            try:
                vp._draw_length_label(painter)
            finally:
                painter.end()
    finally:
        win._saved_version = vp.scene.version
        win.close()
