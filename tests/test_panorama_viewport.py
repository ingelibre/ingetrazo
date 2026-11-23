# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The style's 360° panorama in a real frame: looking north shows the
picture's middle, east its right quarter; the rotation turns it, the fog
covers it, and a parallel view or a lost file keeps the gradient.

Needs an OpenGL context (on Windows run with ``QT_QPA_PLATFORM=windows``;
offscreen platforms without one skip)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

from core.style import Style
from tests.test_panorama_backdrop import (EAST, NORTH, SOUTH, WEST, SKY,
                                          GROUND, quarters, save_png)

_app = QApplication.instance() or QApplication([])
WIDTH = 320


@pytest.fixture
def empty_view(tmp_path):
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    vp = win.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        win._saved_version = vp.scene.version
        win.close()
        pytest.skip("no OpenGL context on this platform")
    vp.camera.perspective = True
    vp.camera.fov_deg = 40.0
    png = save_png(quarters(256, 128), tmp_path / "pano.png")
    yield vp, png
    vp.style_override = None
    win._saved_version = vp.scene.version
    win.close()


def _centre(vp, style, direction):
    vp.style_override = style
    vp.camera.look_from(V(0, 0, 1.6), direction)
    image = vp.render_image(WIDTH, overlays=False)
    assert image is not None
    colour = image.pixelColor(image.width() // 2, image.height() // 2)
    return colour.red(), colour.green(), colour.blue()


def _near(got, want, tol=12):
    return all(abs(a - b) <= tol for a, b in zip(got, want))


@pytest.mark.parametrize("direction, colour", [
    (V(0, 1, 0), NORTH), (V(1, 0, 0), EAST), (V(0, -1, 0), SOUTH),
    (V(-1, 0, 0), WEST), (V(0.2, 1, 6), SKY), (V(0.2, 1, -6), GROUND)])
def test_the_view_shows_the_panorama_in_its_direction(empty_view, direction,
                                                      colour):
    vp, png = empty_view
    got = _centre(vp, Style(panorama=png), direction)
    assert _near(got, colour), got


def test_the_rotation_turns_the_picture(empty_view):
    vp, png = empty_view
    got = _centre(vp, Style(panorama=png, panorama_rotation=90.0), V(0, 1, 0))
    assert _near(got, EAST), got


def test_without_a_panorama_the_gradient_shows(empty_view):
    vp, _png = empty_view
    got = _centre(vp, Style(), V(0, 1, 0))
    assert not _near(got, NORTH, 60), got


def test_with_the_sky_off_the_panorama_hides(empty_view):
    vp, png = empty_view
    got = _centre(vp, Style(panorama=png, sky=False), V(0, 1, 0))
    assert not _near(got, NORTH, 60), got


def test_a_parallel_view_keeps_the_gradient(empty_view):
    vp, png = empty_view
    vp.camera.perspective = False
    got = _centre(vp, Style(panorama=png), V(0, 1, 0))
    assert not _near(got, NORTH, 60), got


def test_a_lost_file_keeps_the_gradient(empty_view, tmp_path):
    vp, _png = empty_view
    got = _centre(vp, Style(panorama=str(tmp_path / "gone.hdr")), V(0, 1, 0))
    assert not _near(got, NORTH, 60), got


def test_thick_fog_covers_the_panorama(empty_view):
    vp, png = empty_view
    fog = (0.5, 0.6, 0.7)
    got = _centre(vp, Style(panorama=png, fog_enabled=True, fog_distance=1.0,
                            fog_thickness=1.0, fog_color=fog), V(0, 1, 0))
    assert _near(got, tuple(round(c * 255) for c in fog)), got
