# SPDX-License-Identifier: GPL-3.0-or-later
"""The ground's shadows are not drawn from below the ground (#1301).

With shadows on, a camera orbited under the ground plane still showed the
shadows cast on the ground (the box's, the figure's at its feet), seen
through the catcher plane from underneath. The GL pass needs a screen;
what is pinned here is the camera's answer and that the catcher pass
returns before drawing anything when the camera is below it.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math
from types import SimpleNamespace

from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from core.camera import OrbitCamera

_app = QApplication.instance() or QApplication([])

#: The catcher's height in the viewport.
CATCHER_Z = -0.005


def _camera(pitch_deg: float, target_z: float = 0.0,
            perspective: bool = True) -> OrbitCamera:
    cam = OrbitCamera()
    cam.target = QVector3D(0.0, 0.0, target_z)
    cam.distance = 20.0
    cam.pitch = math.radians(pitch_deg)
    cam.perspective = perspective
    return cam


def test_perspective_above_the_ground_sees_it_from_above():
    assert not _camera(30.0).sees_from_below(CATCHER_Z)


def test_perspective_below_the_ground_sees_it_from_below():
    assert _camera(-30.0).sees_from_below(CATCHER_Z)


def test_perspective_judges_by_the_eye_not_the_view_direction():
    # Looking up at a roof from a terrace: the eye is above the ground.
    assert not _camera(-20.0, target_z=12.0).sees_from_below(CATCHER_Z)
    # Looking down into a pit from inside it: the eye is below the ground.
    assert _camera(30.0, target_z=-30.0).sees_from_below(CATCHER_Z)


def test_two_point_perspective_judges_like_perspective():
    cam = _camera(-30.0)
    cam.two_point = True
    assert cam.sees_from_below(CATCHER_Z)


def test_parallel_judges_by_the_view_direction():
    # The parallel eye is only a point at `distance`: looking down at a
    # target deep underground still sees the ground from above.
    assert not _camera(30.0, target_z=-50.0,
                       perspective=False).sees_from_below(CATCHER_Z)
    assert _camera(-30.0, target_z=50.0,
                   perspective=False).sees_from_below(CATCHER_Z)


def test_catcher_pass_draws_nothing_from_below():
    from views.viewport import Viewport

    def no_draw(*_a, **_k):
        raise AssertionError("the catcher pass went on to draw")

    fake = SimpleNamespace(
        camera=_camera(-30.0),
        _base_map_showing=lambda: False,
        _terrain_showing=lambda: False,
        _photo_showing=lambda: False,
        scene=SimpleNamespace(bounds=no_draw),
    )
    Viewport._draw_shadow_ground(fake, style=None)   # returns early


def test_catcher_pass_still_draws_from_above():
    from views.viewport import Viewport

    reached = []

    def bounds():
        reached.append(True)
        return None, None                  # empty scene: nothing to draw

    fake = SimpleNamespace(
        camera=_camera(30.0),
        _base_map_showing=lambda: False,
        _terrain_showing=lambda: False,
        _photo_showing=lambda: False,
        scene=SimpleNamespace(bounds=bounds),
    )
    Viewport._draw_shadow_ground(fake, style=None)
    assert reached
