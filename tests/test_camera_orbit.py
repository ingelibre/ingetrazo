# SPDX-License-Identifier: GPL-3.0-or-later
"""The orbit gesture's direction — the bug two users reported on 2026-09-09.

The claim under test is not "pitch has this sign" (that is the code written
twice); it is that ORBIT AND PAN AGREE. Both gestures grab the model, so
whichever way you drag, a given point must travel the same way on screen
under either one. The vertical axis of `orbit` disagreed with `pan` from
the first release until 0.3.16, and every report of it arrived as "the
orbit is mirrored" with the reporter unable to name which axis — which is
what a single flipped axis feels like from the outside.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math

from PySide6.QtGui import QVector3D

from core.camera import OrbitCamera

#: A point one metre above what the camera looks at: high enough on screen
#: that both gestures move it visibly, and it sits still in world space.
MARK = QVector3D(0.0, 0.0, 1.0)

DRAG = 40          # pixels of gesture
VIEWPORT_H = 600


def _screen_y(cam) -> float:
    """Where MARK lands vertically, in NDC (+1 top, -1 bottom)."""
    mvp = cam.projection_matrix() * cam.view_matrix()
    return mvp.map(MARK).y()


def _camera() -> OrbitCamera:
    cam = OrbitCamera()
    cam.aspect = 4.0 / 3.0
    return cam


def test_drag_down_moves_the_model_down_under_both_gestures():
    """Drag down: the model comes down the screen, orbiting or panning."""
    orbited, panned = _camera(), _camera()
    before = _screen_y(orbited)
    assert before == _screen_y(panned)

    orbited.orbit(0, DRAG, VIEWPORT_H)
    panned.pan(0, DRAG, VIEWPORT_H)

    assert _screen_y(orbited) < before, "orbit sent the model UP"
    assert _screen_y(panned) < before, "pan sent the model UP on a down-drag"


def test_drag_down_lifts_the_camera_over_the_model():
    """The same thing said in world terms: you rise and see the top."""
    cam = _camera()
    eye_before = cam.eye().z()
    cam.orbit(0, DRAG, VIEWPORT_H)
    assert cam.eye().z() > eye_before


def test_drag_up_is_the_exact_opposite():
    cam = _camera()
    before = _screen_y(cam)
    cam.orbit(0, -DRAG, VIEWPORT_H)
    assert _screen_y(cam) > before


def test_horizontal_axis_was_never_the_broken_one():
    """Drag right, the model swings right — orbit and pan alike."""
    def _screen_x(cam):
        mvp = cam.projection_matrix() * cam.view_matrix()
        return mvp.map(QVector3D(1.0, 0.0, 0.0)).x()

    orbited, panned = _camera(), _camera()
    before = _screen_x(orbited)
    orbited.orbit(DRAG, 0, VIEWPORT_H)
    panned.pan(DRAG, 0, VIEWPORT_H)
    assert _screen_x(orbited) > before
    assert _screen_x(panned) > before


def test_the_poles_are_still_out_of_reach():
    """The clamp survives the sign change — in both directions."""
    cam = _camera()
    for _ in range(50):
        cam.orbit(0, 200, VIEWPORT_H)
    assert cam.pitch <= math.radians(89.0)
    cam = _camera()
    for _ in range(50):
        cam.orbit(0, -200, VIEWPORT_H)
    assert cam.pitch >= math.radians(-89.0)
