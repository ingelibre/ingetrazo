# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A trackpad pinch zooms like the wheel (#248).

macOS (and libinput touchpads) deliver the pinch as ZoomNativeGesture
events the viewport did not read: on a Mac trackpad the pinch did
nothing at all (trace of a real session, 20-10: 28 pinch events, every
one dropped)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QNativeGestureEvent, QPointingDevice, QWheelEvent
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

CENTRE = QPointF(200, 150)


@pytest.fixture
def vp():
    from views.viewport import Viewport
    view = Viewport(None)
    view.resize(400, 300)
    return view


def pinch(vp, value, at=CENTRE):
    QApplication.sendEvent(vp, QNativeGestureEvent(
        Qt.ZoomNativeGesture, QPointingDevice.primaryPointingDevice(), 2,
        at, at, at, value, QPointF(), 0))


def notch(vp, dy, at=CENTRE):
    QApplication.sendEvent(vp, QWheelEvent(
        at, at, QPoint(), QPoint(0, dy),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))


def test_spreading_the_fingers_zooms_in_and_pinching_zooms_out(vp):
    d0 = vp.camera.distance
    pinch(vp, 0.1)
    assert vp.camera.distance < d0
    d1 = vp.camera.distance
    pinch(vp, -0.1)
    assert vp.camera.distance > d1


def test_a_pinch_of_one_notchs_scale_zooms_one_notch(vp):
    from views.viewport import Viewport
    wheel = Viewport(None)
    wheel.resize(400, 300)
    notch(wheel, 120)
    pinch(vp, 1.0 / 0.9 - 1.0)
    assert vp.camera.distance == pytest.approx(wheel.camera.distance, rel=1e-6)


def test_the_point_under_the_fingers_stays_put(vp):
    at = QPointF(260, 110)
    focus = vp._world_under_cursor(at.x(), at.y())
    assert focus is not None
    d0 = vp.camera.distance
    for _ in range(10):
        pinch(vp, 0.04, at)
    assert vp.camera.distance < d0 * 0.75          # it did zoom
    px = vp._world_to_pixel(focus)
    assert px is not None
    assert px[0] == pytest.approx(at.x(), abs=0.5)
    assert px[1] == pytest.approx(at.y(), abs=0.5)


def test_many_small_pinch_out_steps_do_not_race_away(vp):
    # A wheel notch backs off at least 5 cm (or 1 % of the model); a pinch
    # arrives as dozens of tiny steps, and each taking that whole floor
    # threw the view a metre back on a gentle pinch from close up.
    # The floor pushes the target back (not the orbit distance), so what
    # is measured is how far the eye ends up from the point it zoomed on.
    vp.camera.distance = 0.5
    focus = vp._world_under_cursor(CENTRE.x(), CENTRE.y())
    assert focus is not None
    r0 = (vp.camera.eye() - focus).length()
    for _ in range(20):
        pinch(vp, -0.01)
    r1 = (vp.camera.eye() - focus).length()
    assert r1 == pytest.approx(r0 / 0.99 ** 20, rel=0.05)


def test_the_wheel_preference_does_not_flip_the_pinch(vp):
    vp._invert_wheel = True
    d0 = vp.camera.distance
    pinch(vp, 0.1)
    assert vp.camera.distance < d0


# ---- smart zoom (two-finger double tap) ------------------------------------

def smart_zoom(vp):
    QApplication.sendEvent(vp, QNativeGestureEvent(
        Qt.SmartZoomNativeGesture, QPointingDevice.primaryPointingDevice(),
        2, CENTRE, CENTRE, CENTRE, 1.0, QPointF(), 0))


class _Window:
    """The two MainWindow methods under test, over a real viewport, with
    Zoom Extents framing a fixed box."""

    def __init__(self, vp):
        from types import MethodType

        from PySide6.QtGui import QVector3D
        from views.main_window import MainWindow
        self.viewport = vp
        self._camera_pose = MethodType(MainWindow._camera_pose, self)
        self._on_smart_zoom = MethodType(MainWindow._on_smart_zoom, self)
        self.box = (QVector3D(0, 0, 0), QVector3D(20, 10, 6))
        vp.smartZoomRequested.connect(self._on_smart_zoom)

    def _on_zoom_extents(self):
        self.viewport.camera.fit_box(*self.box)


def test_a_double_tap_frames_the_model_and_a_second_goes_back(vp):
    win = _Window(vp)
    vp.camera.distance = 2.0
    start = win._camera_pose()
    smart_zoom(vp)
    framed = win._camera_pose()
    assert framed != start                        # Zoom Extents ran
    smart_zoom(vp)
    assert win._camera_pose() == pytest.approx(start)


def test_after_moving_the_view_a_double_tap_frames_again(vp):
    win = _Window(vp)
    vp.camera.distance = 2.0
    start = win._camera_pose()
    smart_zoom(vp)
    framed = win._camera_pose()
    pinch(vp, 0.2)                                # the user moved on
    moved = win._camera_pose()
    smart_zoom(vp)
    # Framed again (same orientation, so the same pose as the first time),
    # not sent back to where the first tap started.
    assert win._camera_pose() == pytest.approx(framed)
    assert win._camera_pose() != pytest.approx(start)
    assert win._camera_pose() != pytest.approx(moved)
