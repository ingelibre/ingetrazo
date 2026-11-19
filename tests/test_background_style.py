# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Independent sky/ground controls and compatibility with existing documents."""
from __future__ import annotations

import pytest
import numpy as np
from PySide6.QtCore import QSettings, QSize
from PySide6.QtGui import QImage, QVector3D as V

from core.scene import Scene
from core.style import Style, ground_enabled
from tests.test_edge_rendering import cube_viewport  # noqa: F401 - native fixture


def test_background_roundtrip_in_documents_views_and_library(tmp_path, monkeypatch):
    from core import style as library
    from core.camera import OrbitCamera
    from core.saved_views import SavedView
    from formats import igz

    monkeypatch.setattr(library, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))
    style = Style(name="Ground only", sky=False, ground=True,
                  ground_transparency=47, ground_from_below=False,
                  background=(0.9, 0.8, 0.7), ground_color=(0.2, 0.5, 0.3))
    library.save_user_style(style)
    assert library.style_by_name(style.name).to_dict() == style.to_dict()
    scene = Scene()
    scene.display_style = style
    scene.mesh.add_edge(V(), V(1, 0, 0))
    view = SavedView.capture("Ground", scene, OrbitCamera())
    igz.save_scene(scene, tmp_path / "ground.igz")
    loaded = Scene()
    igz.load_into(loaded, tmp_path / "ground.igz")
    assert loaded.display_style.to_dict() == style.to_dict()
    loaded.display_style = Style()
    view.apply(loaded, OrbitCamera())
    assert loaded.display_style.to_dict() == style.to_dict()


@pytest.mark.parametrize("sky", [False, True])
def test_legacy_styles_keep_their_combined_backdrop(sky):
    style = Style.from_dict({"sky": sky})
    assert style.ground is None
    assert ground_enabled(style) == sky
    assert "ground" not in style.to_dict()
    assert "ground_transparency" not in style.to_dict()
    assert "ground_from_below" not in style.to_dict()
    assert Style.from_dict({"sky": sky, "ground": not sky}).ground == (not sky)


@pytest.mark.parametrize("raw, expected", [(150, 100), (-10, 0), ("bad", 0),
                                          (float("nan"), 0), (35.7, 36)])
def test_ground_transparency_is_bounded(raw, expected):
    assert Style.from_dict({"ground_transparency": raw}).ground_transparency == expected


def test_background_controls_are_independent_and_keep_disabled_values(tmp_path, monkeypatch):
    from core import style as library
    from tests.test_styles_window import _Window
    from views.tray import StylesPanel

    monkeypatch.setattr(library, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))
    window = _Window()
    panel = StylesPanel(window)
    window.panel = panel
    try:
        style = window.viewport.scene.display_style
        # Editing another category must not silently enable the new ground plane.
        panel._edges.setChecked(False)
        assert style.ground is None
        panel._sky.setChecked(False)
        assert not style.sky and style.ground is True
        panel._ground_slider.setValue(47)
        assert style.ground_transparency == panel._ground_transparency.value() == 47
        panel._ground_from_below.setChecked(False)
        panel._ground.setChecked(False)
        assert not style.ground
        assert not panel._ground_slider.isEnabled()
        assert not panel._ground_from_below.isEnabled()
        assert panel._ground_c.isEnabled()
        panel._sky.setChecked(True)
        assert style.sky and not style.ground
        panel._ground.setChecked(True)
        assert style.ground_transparency == 47 and not style.ground_from_below
        assert panel._ground_slider.isEnabled()
        before = style.to_dict()
        panel.refresh()
        assert style.to_dict() == before
    finally:
        panel.close()
        panel.deleteLater()


def test_preview_distinguishes_sky_ground_and_transparency():
    from views.style_preview import style_preview

    size = QSize(100, 80)
    images = [style_preview(Style(sky=sky, ground=ground,
                                 ground_transparency=transparency), size).toImage()
              for sky, ground, transparency in ((False, False, 0), (True, False, 0),
                                                 (False, True, 0), (False, True, 50))]
    assert all(a != b for index, a in enumerate(images) for b in images[index + 1:])


def _pixels(vp):
    image = vp.render_image(600, 500, overlays=False).convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(image.constBits(), dtype=np.uint8).copy().reshape(
        (500, image.bytesPerLine() // 4, 4))[:, :600, :3]


def _sample(vp, pixels, point):
    mvp = vp.camera.projection_matrix() * vp.camera.view_matrix()
    projected = mvp.map(point)
    x = round((projected.x() + 1) * 300)
    y = round((1 - projected.y()) * 250)
    return pixels[y - 2:y + 3, x - 2:x + 3].mean(axis=(0, 1))


def _ground_scene(vp, view="top", perspective=False):
    scene = vp.scene
    scene.clear()
    scene.show_axes = False
    scene.display_style = Style(sky=False, ground=True, edges=False, profiles=False,
                                face_mode="monochrome", front_color=(1, 0, 0),
                                back_color=(1, 0, 0), ground_color=(0, 0, 1),
                                background=(1, 1, 1))
    for x, z in ((-0.8, 1), (0.8, -1)):
        scene.mesh.add_face([V(x - 0.4, -0.5, z), V(x + 0.4, -0.5, z),
                             V(x + 0.4, 0.5, z), V(x - 0.4, 0.5, z)])
    vp.camera.set_view(view)
    vp.camera.perspective = perspective
    vp.camera.target = V()
    vp.camera.distance = 5
    scene.version += 1
    return scene.display_style


@pytest.mark.parametrize("perspective", [False, True])
def test_ground_transparency_hides_only_geometry_below_plane(cube_viewport, perspective):
    vp = cube_viewport
    style = _ground_scene(vp, perspective=perspective)
    solid = _pixels(vp)
    assert _sample(vp, solid, V(-0.8, 0, 1)) == pytest.approx((255, 0, 0), abs=2)
    assert _sample(vp, solid, V(0.8, 0, -1)) == pytest.approx((0, 0, 255), abs=2)
    style.ground_transparency = 50
    translucent = _pixels(vp)
    assert _sample(vp, translucent, V(-0.8, 0, 1)) == pytest.approx((255, 0, 0), abs=2)
    assert _sample(vp, translucent, V(0.8, 0, -1)) == pytest.approx((128, 0, 128), abs=2)
    style.ground_transparency = 100
    transparent = _pixels(vp)
    assert _sample(vp, transparent, V(0.8, 0, -1)) == pytest.approx((255, 0, 0), abs=2)
    style.ground = False
    assert np.array_equal(_pixels(vp), transparent)


@pytest.mark.parametrize("perspective", [False, True])
def test_ground_from_below_toggle_and_untouched_near_geometry(cube_viewport, perspective):
    vp = cube_viewport
    style = _ground_scene(vp, "bottom", perspective)
    solid = _pixels(vp)
    assert _sample(vp, solid, V(-0.8, 0, 1)) == pytest.approx((0, 0, 255), abs=2)
    assert _sample(vp, solid, V(0.8, 0, -1)) == pytest.approx((255, 0, 0), abs=2)
    style.ground_from_below = False
    underneath = _pixels(vp)
    assert _sample(vp, underneath, V(-0.8, 0, 1)) == pytest.approx((255, 0, 0), abs=2)


def test_ground_keeps_coplanar_faces_visible(cube_viewport):
    vp = cube_viewport
    _ground_scene(vp)
    vp.scene.mesh.add_face([V(-0.4, -0.4, 0), V(0.4, -0.4, 0),
                             V(0.4, 0.4, 0), V(-0.4, 0.4, 0)])
    vp.scene.version += 1
    assert _sample(vp, _pixels(vp), V()) == pytest.approx((255, 0, 0), abs=2)


@pytest.mark.parametrize("quality", ["faster", "nicer"])
def test_glass_layers_correctly_on_each_side_of_translucent_ground(cube_viewport, quality):
    vp = cube_viewport
    style = _ground_scene(vp)
    style.face_mode = "textures"
    style.transparency_quality = quality
    for face in vp.scene.mesh.faces:
        face.attrs.update(color=(1, 0, 0), opacity=0.5)
    vp.scene.version += 1
    style.ground = False
    baseline = _pixels(vp)
    above = _sample(vp, baseline, V(-0.8, 0, 1))
    below = _sample(vp, baseline, V(0.8, 0, -1))
    style.ground = True
    style.ground_transparency = 50
    layered = _pixels(vp)
    # Foreground glass sees the ground through it; far glass is tinted by it.
    assert _sample(vp, layered, V(-0.8, 0, 1)) == pytest.approx(
        above - np.array([255, 255, 0]) * 0.25, abs=3)
    assert _sample(vp, layered, V(0.8, 0, -1)) == pytest.approx(
        below * 0.5 + np.array([0, 0, 255]) * 0.5, abs=3)


def test_live_view_updates_ground_without_stale_cached_frames(cube_viewport):
    from PySide6.QtWidgets import QApplication

    vp = cube_viewport
    style = _ground_scene(vp)

    def live_sample():
        for _ in range(3):
            vp.update()
            QApplication.processEvents()
        image = vp.grabFramebuffer().scaled(600, 500).convertToFormat(QImage.Format_RGBA8888)
        pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
            (500, image.bytesPerLine() // 4, 4))[:, :600, :3]
        return _sample(vp, pixels, V(0.8, 0, -1))

    assert live_sample() == pytest.approx((0, 0, 255), abs=3)
    style.ground_transparency = 50
    assert live_sample() == pytest.approx((128, 0, 128), abs=3)
    style.ground = False
    assert live_sample() == pytest.approx((255, 0, 0), abs=3)
