# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Editing a frame's view in place (LayOut: double-click the viewport, then
pan / orbit / zoom; Zoom Extents recentres the model)."""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D

from core.composition import MarcoVista, apply_frame_camera


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


def test_frame_camera_overrides_apply_after_the_view():
    cam = _Cam()
    f = MarcoVista(view_key="std:front", scale_n=100.0,
                   cam_target=[1.0, 2.0, 3.0], cam_yaw=0.3, cam_pitch=0.2)
    apply_frame_camera(cam, f, saved_view=None, scene=_Scene())
    assert (cam.target.x(), cam.target.y(), cam.target.z()) == (1, 2, 3)
    assert (cam.yaw, cam.pitch) == (0.3, 0.2)
    # Orbiting off a plan view: Z is up again (the plan swapped it to +Y).
    cam = _Cam()
    f = MarcoVista(view_key="std:top", scale_n=100.0, cam_pitch=0.5)
    apply_frame_camera(cam, f, saved_view=None, scene=_Scene())
    assert cam.pitch == 0.5 and cam.up.z() == 1.0
    cam = _Cam()
    apply_frame_camera(cam, MarcoVista(view_key="std:top"), scene=_Scene())
    assert cam.up.y() == 1.0                      # untouched plan keeps +Y


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
    frame.view_key = "std:front"
    frame.scale_n = 100.0
    frame.w_mm, frame.h_mm = 200.0, 100.0
    comp._rebuild_canvas()
    item = next(it for it in comp.canvas.items() if isinstance(it, FrameItem))
    return win, comp, item


def test_pan_moves_the_drawing_with_the_mouse(monkeypatch):
    win, comp, item = _composer_with_model(monkeypatch)
    try:
        frame = item.model
        origin = [(0.0, 0.0, 0.0)]
        (x0, y0), = comp._frame_world_to_page(frame, origin)
        comp.begin_view_edit(item)
        assert comp.view_edit_item is item
        before = comp._view_state(frame)
        comp.pan_view(item, 10.0, -5.0)         # drag right 10 mm, up 5 mm
        (x1, y1), = comp._frame_world_to_page(frame, origin)
        assert x1 - x0 == pytest.approx(10.0, abs=1e-6)
        assert y1 - y0 == pytest.approx(-5.0, abs=1e-6)
        assert frame.cam_target is not None
        # The gesture is one undo step.
        comp._commit_view_edit(item, before)
        comp.history.undo()
        assert frame.cam_target is None
        (x2, y2), = comp._frame_world_to_page(frame, origin)
        assert (x2, y2) == pytest.approx((x0, y0), abs=1e-6)
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_zoom_keeps_the_point_under_the_cursor(monkeypatch):
    win, comp, item = _composer_with_model(monkeypatch)
    try:
        frame = item.model
        corner = [(2.0, -2.0, 0.0)]
        (cx, cy), = comp._frame_world_to_page(frame, corner)
        comp.zoom_view(item, 2.0, at_mm=(cx, cy))
        assert frame.scale_n == pytest.approx(50.0)
        (cx2, cy2), = comp._frame_world_to_page(frame, corner)
        assert (cx2, cy2) == pytest.approx((cx, cy), abs=1e-6)
        comp.orbit_view(item, 0.4, 0.2)
        assert frame.cam_yaw == pytest.approx(math.radians(-90.0) + 0.4)
        assert frame.cam_pitch == pytest.approx(0.2)
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_zoom_extents_fits_the_whole_model_in_the_frame(monkeypatch):
    win, comp, item = _composer_with_model(monkeypatch)
    try:
        frame = item.model
        frame.scale_n = 5.0                           # way too close
        frame.cam_target = [30.0, 0.0, 0.0]           # and off to the side
        comp.zoom_extents(item)
        assert frame.scale_n in (20.0, 25.0, 50.0)    # a common scale
        lo, hi = win.viewport.scene.bounds()
        corners = [(x, y, z) for x in (lo.x(), hi.x())
                   for y in (lo.y(), hi.y()) for z in (lo.z(), hi.z())]
        for px, py in comp._frame_world_to_page(frame, corners):
            assert frame.x_mm <= px <= frame.x_mm + frame.w_mm
            assert frame.y_mm <= py <= frame.y_mm + frame.h_mm
        comp.end_view_edit()
        assert comp.view_edit_item is None
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_view_edits_travel_in_the_document(tmp_path):
    from core.composition import Composicion
    c = Composicion()
    f = MarcoVista(cam_target=[1.0, 2.0, 3.0], cam_yaw=0.1, scale_n=75.0)
    c.frames.append(f)
    back = Composicion.from_dict(c.to_dict())
    g = back.frames[-1]
    assert list(g.cam_target) == [1.0, 2.0, 3.0]
    assert g.cam_yaw == 0.1 and g.cam_pitch is None and g.scale_n == 75.0
