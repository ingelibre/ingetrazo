# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Face-style persistence, live controls and real transparent rendering."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage, QVector3D as V

from core.scene import Scene
from core.style import Style
from core.transparency import transparency_draws, transparency_run
from tests.test_edge_rendering import cube_viewport  # noqa: F401 - pytest fixture


def test_face_options_roundtrip_and_preserve_legacy_defaults(tmp_path, monkeypatch):
    from core import style as library
    from core.camera import OrbitCamera
    from core.saved_views import SavedView
    from formats import igz

    monkeypatch.setattr(library, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))
    original = Style(name="Glass", face_mode="monochrome", xray=True, xray_opacity=35,
                     material_transparency=False, transparency_quality="nicer")
    library.save_user_style(original)
    assert library.style_by_name("Glass").to_dict() == original.to_dict()
    scene = Scene()
    scene.display_style = original
    scene.mesh.add_edge(V(), V(1, 0, 0))
    view = SavedView.capture("Glass", scene, OrbitCamera())
    igz.save_scene(scene, tmp_path / "glass.igz")
    loaded = Scene()
    igz.load_into(loaded, tmp_path / "glass.igz")
    assert loaded.display_style.to_dict() == original.to_dict()
    loaded.display_style = Style()
    view.apply(loaded, OrbitCamera())
    assert loaded.display_style.to_dict() == original.to_dict()
    old = Style.from_dict({})
    assert old.material_transparency and old.transparency_quality == "faster"
    assert old.xray_opacity == 60
    assert "xray_opacity" not in old.to_dict()
    invalid = Style.from_dict({"xray_opacity": 500, "transparency_quality": []})
    assert invalid.xray_opacity == 80 and invalid.transparency_quality == "faster"
    assert Style.from_dict({"xray_opacity": -3}).xray_opacity == 20
    assert Style.from_dict({"xray_opacity": "NaN"}).xray_opacity == 60


def test_old_xray_styles_load_as_an_overlay_and_new_styles_keep_their_mode():
    positional = Style("Legacy", "shaded", False)
    assert not positional.edges and not positional.xray
    legacy = Style.from_dict({"name": "Old", "face_mode": "xray", "xray_opacity": 35})
    assert legacy.face_mode == "textures" and legacy.xray and legacy.xray_opacity == 35
    assert legacy.to_dict()["face_mode"] == "textures" and legacy.to_dict()["xray"]
    assert Style(face_mode="xray").xray
    for mode in ("textures", "shaded", "hidden_line", "monochrome", "wireframe"):
        style = Style(face_mode=mode, xray=True)
        restored = style.copy()
        assert restored.face_mode == mode and restored.xray
    assert "xray" not in Style().to_dict()


def test_nicer_sorts_across_material_runs_and_changes_with_view_direction():
    def parts(depth):
        vertices = np.zeros((3, 6), dtype=np.float32)
        vertices[:, :3] = ((-1, depth, -1), (1, depth, -1), (0, depth, 1))
        return [vertices.tobytes()]

    near = transparency_run(parts(1), 0, 6, 0.5)
    far = transparency_run(parts(3), 12, 6, 0.4, path="glass.png", side="back")
    assert transparency_draws([near, far], (0, 0, 0), (0, 1, 0)) == [(near, 0, 3), (far, 12, 3)]
    assert transparency_draws([near, far], (0, 0, 0), (0, 1, 0), True) == [(far, 12, 3), (near, 0, 3)]
    assert transparency_draws([near, far], (0, 5, 0), (0, -1, 0), True) == [(near, 0, 3), (far, 12, 3)]


def test_xray_shortcut_preserves_edge_settings_opacity_and_edits():
    from types import SimpleNamespace
    from views.main_window import MainWindow

    class Window:
        viewport = SimpleNamespace(scene=Scene())
        def _apply_display_style(self, style):
            self.viewport.scene.display_style = style.copy()

    window = Window()
    window.viewport.scene.display_style = Style(face_mode="shaded", profile_width=8,
                                              xray_opacity=35, transparency_quality="nicer")
    MainWindow._toggle_xray(window)
    style = window.viewport.scene.display_style
    assert style.face_mode == "shaded" and style.xray and style.profile_width == 8 and style.xray_opacity == 35
    style.xray_opacity = 70
    style.profile_width = 9
    MainWindow._toggle_xray(window)
    style = window.viewport.scene.display_style
    assert style.face_mode == "shaded" and not style.xray and style.profile_width == 9 and style.xray_opacity == 70
    assert style.transparency_quality == "nicer"
    window.viewport.scene = Scene()
    window.viewport.scene.display_style = Style(face_mode="xray", profile_width=7)
    MainWindow._toggle_xray(window)
    assert window.viewport.scene.display_style.face_mode == "textures"
    assert not window.viewport.scene.display_style.xray
    assert window.viewport.scene.display_style.profile_width == 7


def test_face_controls_apply_live_and_keep_disabled_values(tmp_path, monkeypatch):
    from core import style as library
    from views.tray import StylesPanel

    monkeypatch.setattr(library, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))

    class Viewport:
        scene = Scene()
        def update(self):
            pass

    class Window:
        viewport = Viewport()
        def _sync_style_menu(self):
            panel.refresh()

    window = Window()
    panel = StylesPanel(window)
    try:
        style = window.viewport.scene.display_style
        assert not panel._xray_opacity.isEnabled()
        panel._xray.click()
        assert style.face_mode == "textures" and style.xray and panel._xray_opacity.isEnabled()
        assert len(panel._face_modes.buttons()) == 5
        assert panel._xray not in panel._face_modes.buttons()
        panel._xray_slider.setValue(32)
        assert style.xray_opacity == 32 and panel._xray_opacity.value() == 32
        panel._transparency_quality.setCurrentIndex(1)
        assert style.transparency_quality == "nicer"
        panel._material_transparency.setChecked(False)
        assert not style.material_transparency and not panel._transparency_quality.isEnabled()
        panel._face_modes.button(2).click()
        assert style.face_mode == "hidden_line" and style.xray and panel._xray_opacity.isEnabled()
        panel._xray.click()
        assert style.face_mode == "hidden_line" and not style.xray and not panel._xray_opacity.isEnabled()
        panel.refresh()
        assert panel._xray_opacity.value() == 32 and panel._transparency_quality.currentData() == "nicer"
        panel._xray.click()
        assert style.xray_opacity == 32
    finally:
        panel.close()


@pytest.mark.parametrize("mode", ["textures", "shaded", "hidden_line", "monochrome"])
def test_xray_allows_real_endpoint_snapping_through_faces_without_changing_mode(mode):
    from PySide6.QtCore import Qt
    from tools.line import LineTool
    from views.viewport import Viewport

    vp = Viewport()
    try:
        vp.resize(900, 750)
        vp.camera.aspect = 900 / 750
        vp.camera.set_view("front")
        vp.camera.perspective = False
        vp.camera.distance = 5
        vp.scene.show_axes = False
        vp.scene.display_style = Style(face_mode=mode)
        _plane(vp, 0, (1, 1, 1))
        target = V(0.15, 0.5, 0.2)
        vp.scene.mesh.add_edge(target, V(0.65, 0.5, 0.2))
        vp.scene.version += 1
        vp.active_tool = LineTool()
        x, y = vp._world_to_pixel(target)
        assert vp._is_occluded(target)
        assert vp._occluded_many([target]) == [True]
        before = vp._snap_at(x, y, Qt.NoModifier)
        assert before is None or before.kind != "endpoint" or (before.point - target).length() > 1e-4
        vp.scene.display_style.xray = True
        assert not vp._is_occluded(target)
        assert vp._occluded_many([target]) == [False]
        snapped = vp._snap_at(x, y, Qt.NoModifier)
        assert snapped is not None and snapped.kind == "endpoint"
        assert (snapped.point - target).length() < 1e-4
        assert vp.scene.display_style.face_mode == mode
        vp.scene.display_style.xray = False
        assert vp._is_occluded(target)
    finally:
        vp.close()


def _plane(vp, y, color, opacity=1.0):
    face = vp.scene.mesh.add_face([V(-1, y, -1), V(1, y, -1), V(1, y, 1), V(-1, y, 1)])
    face.attrs.update(color=color, opacity=opacity)
    vp.scene.version += 1
    return face


def _setup(vp, mode="textures"):
    vp.scene.clear()
    vp.scene.show_axes = False
    vp.scene.display_style = Style(face_mode=mode, edges=False, profiles=False, sky=False,
                                   background=(1, 1, 1))
    vp.camera.set_view("front")
    vp.camera.perspective = False
    vp.camera.distance = 5
    return vp.scene.display_style


def _image(vp):
    return vp.render_image(900, 750, overlays=False).convertToFormat(QImage.Format_RGBA8888)


@pytest.mark.parametrize("mode", ["textures", "shaded", "hidden_line", "monochrome", "wireframe"])
def test_xray_preserves_each_face_modes_rendering_and_only_adds_transparency(cube_viewport, tmp_path, mode):
    vp = cube_viewport
    style = _setup(vp, mode)
    style.front_color = (0.2, 0.7, 0.2)
    face = _plane(vp, 0, (0.9, 0.1, 0.1))
    texture = QImage(16, 16, QImage.Format_RGB32)
    texture.fill(QColor(255, 0, 0))
    for y in range(16):
        for x in range(8, 16):
            texture.setPixelColor(x, y, QColor(0, 0, 255))
    path = tmp_path / "two-colors.png"
    assert texture.save(str(path))
    face.attrs["texture"] = {"path": str(path), "sw": 2, "sh": 2}
    vp.scene.version += 1

    def pixels():
        image = _image(vp)
        return np.frombuffer(image.constBits(), dtype=np.uint8).copy().reshape((750, image.bytesPerLine() // 4, 4))

    opaque = pixels()
    before = style.to_dict()
    style.xray = True
    style.xray_opacity = 40
    transparent = pixels()
    assert style.face_mode == mode
    expected = opaque[:, :, :3] if mode == "wireframe" else opaque[:, :, :3] * 0.4 + 255 * 0.6
    assert np.abs(transparent[:, :, :3].astype(float) - expected).max() <= 3
    style.xray = False
    style.xray_opacity = 60
    assert style.to_dict() == before
    assert np.array_equal(pixels(), opaque)


@pytest.mark.parametrize("textured", [False, True])
@pytest.mark.parametrize("grouped", [False, True])
def test_nicer_composites_overlapping_materials_in_depth_order(cube_viewport, tmp_path, textured, grouped):
    vp = cube_viewport
    style = _setup(vp)
    _plane(vp, -0.5, (1, 0, 0), 0.5)  # Near red is inserted first, then far blue.
    far = _plane(vp, 0.5, (0, 0, 1), 0.5)
    if textured:
        texture = QImage(8, 8, QImage.Format_RGB32)
        texture.fill(QColor(0, 0, 255))
        path = tmp_path / "blue.png"
        assert texture.save(str(path))
        far.attrs["texture"] = {"path": str(path), "sw": 1, "sh": 1}
    if grouped:
        from core.group import Group
        mesh = vp.scene.mesh
        vp.scene.mesh = type(mesh)()
        vp.scene.groups.append(Group(mesh))
        vp.scene.version += 1
    faster = _image(vp).pixelColor(450, 375)
    style.transparency_quality = "nicer"
    nicer = _image(vp).pixelColor(450, 375)
    assert faster.blue() > faster.red() + 25
    assert nicer.red() > nicer.blue() + 25
    assert nicer.alpha() == 255
    cache = vp._transparency_order
    _image(vp)
    assert vp._transparency_order is cache
    style.material_transparency = False
    opaque = _image(vp).pixelColor(450, 375)
    assert opaque.red() > opaque.blue() + 100 and opaque.blue() < 5
    assert all(face.attrs["opacity"] == 0.5 for face in vp.scene.mesh.faces)
    style.material_transparency = True
    assert _image(vp).pixelColor(450, 375) == nicer


@pytest.mark.parametrize("kind", ["color", "texture", "group", "back"])
def test_xray_opacity_changes_real_loose_textured_and_instanced_faces(cube_viewport, tmp_path, kind):
    vp = cube_viewport
    style = _setup(vp, "xray")
    face = _plane(vp, 0, (0, 0, 0))
    if kind == "texture":
        texture = QImage(8, 8, QImage.Format_RGB32)
        texture.fill(QColor(0, 0, 0))
        path = tmp_path / "black.png"
        assert texture.save(str(path))
        face.attrs["texture"] = {"path": str(path), "sw": 1, "sh": 1}
    elif kind == "back":
        face.attrs["color"] = (1, 1, 1)
        face.attrs["back"] = {"color": (0, 0, 0)}
        vp.camera.set_view("back")
    elif kind == "group":
        from core.group import Group
        mesh = vp.scene.mesh
        vp.scene.mesh = type(mesh)()
        vp.scene.groups.append(Group(mesh))
    vp.scene.version += 1
    style.xray_opacity = 20
    low = _image(vp).pixelColor(450, 375)
    style.xray_opacity = 80
    high = _image(vp).pixelColor(450, 375)
    assert low.red() > high.red() + 100
    assert low.alpha() == high.alpha() == 255


def test_material_toggle_displays_texture_cutouts_as_opaque(cube_viewport, tmp_path):
    vp = cube_viewport
    style = _setup(vp)
    face = _plane(vp, 0, (1, 0, 0))
    texture = QImage(8, 8, QImage.Format_RGBA8888)
    texture.fill(QColor(255, 0, 0, 64))
    path = tmp_path / "cutout.png"
    assert texture.save(str(path))
    face.attrs["texture"] = {"path": str(path), "sw": 1, "sh": 1}
    vp.scene.version += 1

    def red_count():
        image = _image(vp)
        pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape((750, image.bytesPerLine() // 4, 4))
        area = pixels[300:450, 350:550, :3].astype(int)
        return (area[:, :, 0] > area[:, :, 1] + 60).sum()

    transparent = red_count()
    style.material_transparency = False
    opaque = red_count()
    assert opaque > transparent * 1.5
    assert face.attrs["texture"]["path"] == str(path)


def test_live_frame_updates_when_xray_opacity_changes(cube_viewport):
    from PySide6.QtWidgets import QApplication
    vp = cube_viewport
    style = _setup(vp, "xray")
    _plane(vp, 0, (0, 0, 0))

    def frame(opacity):
        style.xray_opacity = opacity
        vp.update()
        QApplication.processEvents()
        image = vp.grabFramebuffer()
        return image.pixelColor(image.width() // 2, image.height() // 2)

    low, high = frame(20), frame(80)
    assert low.red() > high.red() + 100


@pytest.mark.parametrize("mode", ["hidden_line", "monochrome"])
@pytest.mark.parametrize("back", [False, True])
def test_flat_modes_draw_glass_faces_as_solid(cube_viewport, mode, back):
    vp = cube_viewport
    style = _setup(vp, mode)
    # 0.6.1 keeps glass translucent in Monochrome; Styles can opt out.
    style.material_transparency = False
    # 0.6.1 keeps glass translucent in Monochrome; Styles can opt out.
    style.material_transparency = False
    style.front_color = (0.2, 0.5, 0.2)
    face = _plane(vp, 0, (1, 0, 0), 0.2)
    if back:
        face.attrs["back"] = {"color": (1, 0, 0)}
        vp.camera.set_view("back")
        vp.scene.version += 1
    color = _image(vp).pixelColor(450, 375)
    if back and mode == "monochrome":
        assert color.blue() > color.red() + 20
    else:
        assert color.green() > color.red() + 50 and color.red() < 80
    assert color.alpha() == 255




@pytest.mark.parametrize("back", [False, True])
def test_monochrome_keeps_release_glass_translucent_and_grey(cube_viewport, back):
    from core.style import MONOCHROME_GLASS_RGB

    vp = cube_viewport
    style = _setup(vp, "monochrome")
    style.front_color = (0.2, 0.5, 0.2)
    face = _plane(vp, 0, (1, 0, 0), 0.2)
    if back:
        face.attrs["back"] = {"color": (1, 0, 0)}
        vp.camera.set_view("back")
        vp.scene.version += 1
    color = _image(vp).pixelColor(450, 375)
    expected = round(255 * (0.8 + 0.2 * MONOCHROME_GLASS_RGB[0]))
    assert abs(color.red() - expected) <= 2
    assert abs(color.green() - color.red()) <= 1
    assert abs(color.blue() - color.red()) <= 1
    assert color.alpha() == 255
