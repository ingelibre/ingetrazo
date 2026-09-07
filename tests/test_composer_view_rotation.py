# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Turning a model view on the sheet (Marco, 2026-09-07: «en compositor de
láminas, debería poder rotar un model view»).

The frame does not move: the DRAWING inside it turns, clockwise on paper like
the north arrow's angle, because ``rot_deg`` is a roll of the frame's camera.
Everything projected through that camera — the render, the hidden-line pass,
snap points, anchored cotas — turns with it by construction.
"""
from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QVector3D

from core.composition import (Composicion, MarcoVista, apply_frame_camera,
                              roll_camera)


class _Cam:
    def __init__(self):
        self.fov_deg = 45.0
        self.perspective = True
        self.distance = 7.0
        self.aspect = 1.6
        self.yaw = 0.0
        self.pitch = 0.0
        self.up = QVector3D(0, 0, 1)
        self.target = QVector3D(0, 0, 0)

    def set_view(self, key):
        self.yaw, self.pitch = {"front": (math.radians(-90.0), 0.0),
                                "top": (math.radians(-90.0),
                                        math.radians(89.0))}[key]


class _Scene:
    def bounds(self):
        return QVector3D(0, 0, 0), QVector3D(4, 4, 2)


def test_a_frame_without_a_turn_leaves_the_camera_exactly_as_it_was():
    cam = _Cam()
    apply_frame_camera(cam, MarcoVista(view_key="std:top"), scene=_Scene())
    assert (cam.up.x(), cam.up.y(), cam.up.z()) == (0.0, 1.0, 0.0)


def test_a_quarter_turn_on_a_plan_swaps_the_up_vector():
    cam = _Cam()
    f = MarcoVista(view_key="std:top", rot_deg=90.0)
    apply_frame_camera(cam, f, scene=_Scene())
    # Plan: forward −Z, up +Y, right +X. A clockwise quarter turn of the
    # DRAWING points the camera's up at −X, so east lands at the bottom.
    assert cam.up.x() == pytest.approx(-1.0, abs=1e-6)
    assert cam.up.y() == pytest.approx(0.0, abs=1e-6)
    assert cam.up.z() == pytest.approx(0.0, abs=1e-6)


def test_the_roll_keeps_the_up_vector_square_to_the_sight_line():
    cam = _Cam()
    cam.yaw, cam.pitch = math.radians(37.0), math.radians(21.0)
    roll_camera(cam, 33.0)
    cp, sp = math.cos(cam.pitch), math.sin(cam.pitch)
    cy, sy = math.cos(cam.yaw), math.sin(cam.yaw)
    fwd = (-cp * cy, -cp * sy, -sp)
    up = (cam.up.x(), cam.up.y(), cam.up.z())
    # QVector3D stores single precision, hence the 1e-6.
    assert sum(f * u for f, u in zip(fwd, up)) == pytest.approx(0.0, abs=1e-6)
    assert math.sqrt(sum(u * u for u in up)) == pytest.approx(1.0, abs=1e-6)


def test_the_turn_survives_the_igz_round_trip():
    c = Composicion()
    c.frames = [MarcoVista(rot_deg=-37.5)]
    back = Composicion.from_dict(c.to_dict())
    assert back.frames[0].rot_deg == -37.5
    # a sheet written before this version simply has no turn
    d = c.to_dict()
    d["frames"][0].pop("rot_deg")
    assert Composicion.from_dict(d).frames[0].rot_deg == 0.0


# ---- In the composer, on a real model ---------------------------------------

def _composer_with_model(monkeypatch):
    from views.composer import ComposerWindow, FrameItem
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    scene = win.viewport.scene
    scene.mesh.add_face([QVector3D(-2, -2, 0), QVector3D(2, -2, 0),
                         QVector3D(2, 2, 0), QVector3D(-2, 2, 0)])
    scene.mesh.add_face([QVector3D(-2, -2, 0), QVector3D(2, -2, 0),
                         QVector3D(2, -2, 3), QVector3D(-2, -2, 3)])
    scene.version += 1
    comp = ComposerWindow(win)
    comp.show()
    frame = comp.comp.frames[0]
    frame.view_key = "std:top"          # a plan: the view you turn on a sheet
    frame.scale_n = 100.0
    frame.w_mm, frame.h_mm = 200.0, 200.0
    comp._rebuild_canvas()
    item = next(it for it in comp.canvas.items() if isinstance(it, FrameItem))
    return win, comp, item


def _centre(frame):
    return (frame.x_mm + frame.w_mm / 2.0, frame.y_mm + frame.h_mm / 2.0)


def test_the_drawing_turns_clockwise_around_the_frame_centre(monkeypatch):
    win, comp, item = _composer_with_model(monkeypatch)
    try:
        frame = item.model
        east = [(2.0, 0.0, 0.0)]                   # +X, to the right on a plan
        cx, cy = _centre(frame)
        (x0, y0), = comp._frame_world_to_page(frame, east)
        assert x0 > cx + 1.0 and y0 == pytest.approx(cy, abs=1e-6)
        frame.rot_deg = 90.0
        (x1, y1), = comp._frame_world_to_page(frame, east)
        assert x1 == pytest.approx(cx, abs=1e-6)   # east swung to the bottom
        assert y1 == pytest.approx(cy + (x0 - cx), abs=1e-6)
        frame.rot_deg = -90.0                      # the other way: to the top
        (x2, y2), = comp._frame_world_to_page(frame, east)
        assert x2 == pytest.approx(cx, abs=1e-6)
        assert y2 == pytest.approx(cy - (x0 - cx), abs=1e-6)
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_turning_does_not_move_the_frame_or_the_scale(monkeypatch):
    win, comp, item = _composer_with_model(monkeypatch)
    try:
        frame = item.model
        box = (frame.x_mm, frame.y_mm, frame.w_mm, frame.h_mm, frame.scale_n)
        comp.set_view_rotation(item, 30.0)
        assert (frame.x_mm, frame.y_mm, frame.w_mm, frame.h_mm,
                frame.scale_n) == box
        # …and what the frame shows keeps its size: a turn is not a zoom.
        # 4 m at 1:100 is 40 mm of paper, turned or not.
        pts = [(2.0, 0.0, 0.0), (-2.0, 0.0, 0.0)]
        (ax, ay), (bx, by) = comp._frame_world_to_page(frame, pts)
        assert math.hypot(bx - ax, by - ay) == pytest.approx(40.0, abs=1e-4)
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_hand_turn_snaps_to_15_and_is_one_undo_step(monkeypatch):
    win, comp, item = _composer_with_model(monkeypatch)
    try:
        frame = item.model
        comp.begin_view_edit(item)
        cx, cy = _centre(frame)
        start = QPointF(cx + 50.0, cy)                    # 3 o'clock
        comp.start_view_drag(item, start, start.toPoint(), mode="rotate")
        assert comp.view_drag_active()
        # sweep to ~44°: the magnet pulls it onto 45°
        ang = math.radians(44.0)
        now = QPointF(cx + 50.0 * math.cos(ang), cy + 50.0 * math.sin(ang))
        comp.move_view_drag(now, now.toPoint())
        assert frame.rot_deg == pytest.approx(45.0)
        comp.finish_view_drag()
        assert frame.rot_deg == pytest.approx(45.0)
        comp.history.undo()
        assert frame.rot_deg == 0.0
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_panel_spin_turns_the_view_and_can_be_undone(monkeypatch):
    win, comp, item = _composer_with_model(monkeypatch)
    try:
        frame = item.model
        item.setSelected(True)
        comp.on_selection_changed()
        assert comp.rot_spin.value() == 0.0
        comp.rot_spin.setValue(30.0)
        assert frame.rot_deg == pytest.approx(30.0)
        comp.history.undo()
        assert frame.rot_deg == 0.0
        # and a frame that carries a turn shows it when selected again
        frame.rot_deg = 12.5
        comp._rebuild_canvas()
        from views.composer import FrameItem
        again = next(it for it in comp.canvas.items()
                     if isinstance(it, FrameItem))
        again.setSelected(True)
        comp.on_selection_changed()
        assert comp.rot_spin.value() == pytest.approx(12.5)
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_turned_frame_keeps_its_snap_points_in_the_same_places(monkeypatch):
    """Snap points come from the same camera as the drawing, so a corner of
    the model stays on its corner after the turn (this is what keeps anchored
    cotas true)."""
    win, comp, item = _composer_with_model(monkeypatch)
    try:
        frame = item.model
        frame.rot_deg = 25.0
        pts, world = comp.frame_snap_points(frame)
        if not len(world):
            pytest.skip("no snap geometry in this environment")
        pages = comp._frame_world_to_page(frame, [list(w) for w in world])
        for (px, py), (sx, sy) in zip(pages, pts):
            assert (px, py) == pytest.approx((sx, sy), abs=1e-6)
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
