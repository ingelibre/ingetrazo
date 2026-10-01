# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The zoom and the orbit pivot read the point under the cursor from the
depth of the frame on screen, not from the pick index (issue #158): on a
model of 21 406 placements the first wheel notch built the index — every
placement baked, minutes and 8 GB. Needs a GL context that renders."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _box(scene, x0, y0, z0, x1, y1, z1):
    p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        scene.mesh.add_face([p[i] for i in idx])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    for _ in range(10):
        _app.processEvents()
    vp = w.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        w.close()
        pytest.skip("no OpenGL context on this platform")
    vp.scene.guides.clear()
    _box(vp.scene, -1, -1, 0, 1, 1, 2)                   # front face at y = -1
    vp.scene.version += 1
    vp.camera.set_view("front")                           # looking toward +Y
    vp.camera.perspective = False
    vp.camera.fit_to(V(-3, -1, -1), V(3, 1, 3))
    vp.grabFramebuffer()                                  # a frame on screen
    if vp._depth_world_at(10, 10) is None:
        w._saved_version = vp.scene.version
        w.close()
        pytest.skip("this GL context gives no depth read-back")
    yield w
    w._saved_version = vp.scene.version
    w.close()


def _no_index(vp, monkeypatch):
    built = []
    monkeypatch.setattr(type(vp), "_pick_index",
                        lambda self: built.append(1) or None)
    return built


def test_the_zoom_finds_the_face_under_the_cursor_from_the_depth(win, monkeypatch):
    vp = win.viewport
    built = _no_index(vp, monkeypatch)
    px = vp._world_to_pixel(V(0.3, -1.0, 1.2))
    p = vp._world_under_cursor(*px)
    assert p is not None
    assert (p.x(), p.y(), p.z()) == pytest.approx((0.3, -1.0, 1.2), abs=0.05)
    assert built == []


def test_the_orbit_pivot_too(win, monkeypatch):
    vp = win.viewport
    built = _no_index(vp, monkeypatch)
    px = vp._world_to_pixel(V(-0.5, -1.0, 0.5))
    p = vp._orbit_pivot_at(*px)
    assert (p.x(), p.y(), p.z()) == pytest.approx((-0.5, -1.0, 0.5), abs=0.05)
    assert built == []


def test_the_sky_does_not_build_the_index_either(win, monkeypatch):
    vp = win.viewport
    built = _no_index(vp, monkeypatch)
    px = vp._world_to_pixel(V(2.8, -1.0, 2.8))            # beside the box
    vp._world_under_cursor(*px)
    vp._orbit_pivot_at(*px)
    assert built == []


def test_after_the_camera_moves_without_a_frame_it_falls_back(win):
    vp = win.viewport
    vp.camera.orbit(30.0, 5.0, vp.height())               # no repaint yet
    assert vp._depth_world_at(10, 10) is None
