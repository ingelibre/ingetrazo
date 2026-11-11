# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Modeling cues, visibility, portable styles and real pixel-width cut lines."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.camera import OrbitCamera
from core.guide import Guide
from core.modeling_style import apply_modeling_visibility, section_cut_quads
from core.scene import Scene
from core.section import SectionPlane
from core.style import Style
from tests.test_edge_rendering import cube_viewport  # noqa: F401 - native fixture


def test_modeling_options_roundtrip_in_styles_views_and_documents(tmp_path, monkeypatch):
    from core import style as library
    from core.saved_views import SavedView
    from formats import igz

    monkeypatch.setattr(library, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))
    style = Style(name="Working", modeling_colors={"selected": (0.2, 0.5, 0.8),
                                                  "guides": (0.6, 0.3, 0.2)},
                  modeling_visibility={"show_axes": False, "show_hidden_geometry": True,
                                       "show_section_planes": False, "show_section_cuts": False},
                  show_guides=False, color_by_layer=True, section_cut_width=7.5)
    library.save_user_style(style)
    assert library.style_by_name("Working").to_dict() == style.to_dict()
    scene = Scene()
    scene.display_style = style
    apply_modeling_visibility(scene)
    scene.mesh.add_edge(V(), V(1, 0, 0))
    view = SavedView.capture("Working view", scene, OrbitCamera())
    igz.save_scene(scene, tmp_path / "working.igz")
    loaded = Scene()
    igz.load_into(loaded, tmp_path / "working.igz")
    assert loaded.display_style.to_dict() == style.to_dict()
    assert not loaded.show_axes and loaded.show_hidden_geometry
    assert not loaded.show_section_planes and not loaded.show_section_cuts
    loaded.show_axes = True
    view.apply(loaded, OrbitCamera())
    assert not loaded.show_axes and loaded.display_style.to_dict() == style.to_dict()


def test_legacy_style_keeps_scene_visibility_and_bad_values_are_ignored():
    scene = Scene()
    scene.show_axes = False
    scene.display_style = Style.from_dict({})
    apply_modeling_visibility(scene)
    assert not scene.show_axes
    assert scene.display_style.show_guides and scene.display_style.section_cut_width == 2.5
    assert "modeling_colors" not in scene.display_style.to_dict()
    assert "modeling_visibility" not in scene.display_style.to_dict()
    style = Style.from_dict({"modeling_colors": {"selected": [2, -1, 0.5],
                                                  "locked": [float("nan"), 0, 0],
                                                  "unknown": [1, 0, 0]},
                             "section_cut_width": float("inf")})
    assert style.modeling_colors == {"selected": (1.0, 0.0, 0.5)}
    assert style.section_cut_width == 20
    assert Style.from_dict({"section_cut_width": 100}).section_cut_width == 20
    guide = Guide(V())
    scene.guides.append(guide)
    scene.selection.add(guide)
    scene.display_style = Style(show_guides=False)
    apply_modeling_visibility(scene)
    assert guide not in scene.selection and scene.guides == [guide]


@pytest.mark.parametrize("perspective", [False, True])
@pytest.mark.parametrize("distance", [4, 12])
def test_cut_line_geometry_keeps_pixel_width_across_projection_and_zoom(perspective, distance):
    camera = OrbitCamera()
    camera.perspective = perspective
    camera.distance = distance
    mvp = camera.projection_matrix() * camera.view_matrix()
    matrix = np.array(mvp.data()).reshape(4, 4).T
    points = section_cut_quads([[[-1, 0, 0], [1, 0, 1]]], matrix, 800, 600, 9)
    clip = np.c_[points, np.ones(len(points))] @ matrix.T
    pixels = clip[:, :2] / clip[:, 3:4] * (400, 300)
    assert np.linalg.norm(pixels[0] - pixels[5]) == pytest.approx(9, abs=0.02)
    assert np.isfinite(points).all()
    assert not len(section_cut_quads([[[0, 0, -2], [1, 0, -2]]], np.eye(4), 800, 600, 9))


def test_modeling_panel_updates_scene_guides_and_colors(tmp_path, monkeypatch):
    from core import style as library
    from tests.test_styles_window import _Window
    from views.tray import StylesPanel
    from views.viewport import shown_guides

    monkeypatch.setattr(library, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))
    monkeypatch.setattr("views.modeling_panel.get_color", lambda *a, **k: QColor(18, 52, 86))
    window = _Window()
    scene = window.viewport.scene
    guide = Guide(V(), V(1, 0, 0))
    scene.guides.append(guide)
    scene.selection.add(guide)
    panel = StylesPanel(window)
    window.panel = panel
    editor = panel._modeling
    try:
        baseline = scene.display_style.to_dict()
        panel.refresh()
        assert scene.display_style.to_dict() == baseline
        editor.colors["selected"].click()
        assert scene.display_style.modeling_colors["selected"] == pytest.approx((18/255, 52/255, 86/255))
        editor.cut_width.setValue(8)
        editor.visibility["show_guides"].setChecked(False)
        editor.visibility["show_axes"].setChecked(False)
        editor.visibility["show_section_cuts"].setChecked(False)
        editor.visibility["color_by_layer"].setChecked(True)
        assert not scene.show_axes and not scene.show_section_cuts
        assert scene.display_style.section_cut_width == 8 and scene.display_style.color_by_layer
        assert guide not in scene.selection and shown_guides(scene) == []
        assert not scene.entity_visible(guide) and not scene.entity_selectable(guide)
        assert scene.guides == [guide]
        editor.visibility["show_guides"].setChecked(True)
        assert shown_guides(scene) == [guide]
    finally:
        panel.close()
        panel.deleteLater()


def test_menu_and_modeling_checkboxes_stay_synchronized(tmp_path, monkeypatch):
    from core import style as library
    from views.main_window import MainWindow

    monkeypatch.setattr(library, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))
    window = MainWindow(defer_extensions=True)
    try:
        panel = window.styles_panel._modeling
        window._act_show_axes.setChecked(False)
        assert not panel.visibility["show_axes"].isChecked()
        panel.visibility["show_axes"].setChecked(True)
        assert window._act_show_axes.isChecked()
        window._act_hidden_geometry.setChecked(True)
        assert panel.visibility["show_hidden_geometry"].isChecked()
        panel.visibility["show_section_cuts"].setChecked(False)
        assert not window._act_show_scuts.isChecked()
        saved = window.viewport.scene.display_style.copy()
        window._set_show_axes(False)
        window._apply_display_style(saved)
        assert window.viewport.scene.show_axes and window._act_show_axes.isChecked()
    finally:
        window._saved_version = window.viewport.scene.version
        window.close()


def _pixels(image):
    image = image.convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(image.constBits(), dtype=np.uint8).copy().reshape(
        (image.height(), image.bytesPerLine() // 4, 4))[:, :image.width(), :3]


def _live(vp):
    for _ in range(3):
        vp.update()
        QApplication.processEvents()
    return _pixels(vp.grabFramebuffer())


def _count_color(pixels, rgb):
    return (np.max(abs(pixels.astype(int) - np.array(rgb)), axis=2) < 15).sum()


def test_selected_face_color_updates_without_geometry_rebuild(cube_viewport):
    vp = cube_viewport
    vp.scene.display_style = Style(sky=False, ground=False)
    vp.scene.selection.add(vp.scene.mesh.faces[1])
    vp.scene.display_style.modeling_colors["selected"] = (1, 0, 1)
    assert _count_color(_live(vp), (255, 0, 255)) > 20
    version = vp.scene.version
    vp.scene.display_style.modeling_colors["selected"] = (0, 0, 1)
    assert _count_color(_live(vp), (0, 0, 255)) > 20
    assert vp.scene.version == version


def test_locked_selected_object_uses_its_own_outline_color(cube_viewport):
    from core.group import Group

    vp = cube_viewport
    scene = vp.scene
    scene.clear()
    scene.show_axes = False
    group = Group(name="Locked")
    group.mesh.add_edge(V(-1, 0, -1), V(1, 0, 1))
    group.locked = True
    scene.groups.append(group)
    scene.selection.add(group)
    scene.version += 1
    scene.display_style = Style(sky=False, ground=False, modeling_colors={"locked": (0, 1, 0)})
    vp.camera.set_view("front")
    vp.camera.distance = 5
    pixels = _live(vp).astype(int)
    assert ((pixels[:, :, 1] > pixels[:, :, 0] + 60)
            & (pixels[:, :, 1] > pixels[:, :, 2] + 60)).sum() > 20


def test_guide_colors_and_visibility_are_used_in_rendering(cube_viewport):
    vp = cube_viewport
    vp.scene.clear()
    vp.scene.show_axes = False
    vp.scene.guides.append(Guide(V(), V(1, 0, 0)))
    vp.scene.version += 1
    style = vp.scene.display_style = Style(sky=False, ground=False,
                                           modeling_colors={"guides": (0, 0, 1)})
    vp.camera.set_view("front")
    vp.camera.distance = 5
    def blue_count():
        pixels = _pixels(vp.render_image(600, 500, overlays=False)).astype(int)
        return ((pixels[:, :, 2] > pixels[:, :, 0] + 60)
                & (pixels[:, :, 2] > pixels[:, :, 1] + 60)).sum()

    assert blue_count() > 5
    style.show_guides = False
    assert blue_count() == 0


@pytest.mark.parametrize("perspective", [False, True])
def test_cut_width_color_and_export_scale(cube_viewport, perspective):
    vp = cube_viewport
    scene = vp.scene
    style = scene.display_style = Style(sky=False, ground=False, section_fill=False,
                                        modeling_colors={"section_cut": (1, 0, 0)},
                                        section_cut_width=8)
    plane = SectionPlane(V(), V(0, -1, 0))
    scene.section_planes.append(plane)
    scene.set_active_section(plane)
    vp.camera.set_view("front")
    vp.camera.perspective = perspective
    vp.camera.distance = 5

    def cut_pixels(scale):
        vp._export_edge_px = scale
        image = _pixels(vp.render_image(600, 500, overlays=False))
        row = image[250]
        return ((row[:, 0] > 220) & (row[:, 1] < 20) & (row[:, 2] < 20)).sum()

    assert cut_pixels(1) == pytest.approx(16, abs=3)  # Two vertical cut edges.
    assert cut_pixels(2) == pytest.approx(32, abs=4)


def test_active_and_inactive_section_colors_reach_export(cube_viewport):
    vp = cube_viewport
    scene = vp.scene
    scene.display_style = Style(sky=False, ground=False, modeling_colors={
        "section_active": (1, 0, 1), "section_inactive": (0, 1, 1)})
    scene.section_planes.extend((SectionPlane(V(), V(0, 1, 0)),
                                 SectionPlane(V(0, 0, 0.5), V(0, 0, 1))))
    scene.set_active_section(scene.section_planes[0])
    image = _pixels(vp.render_image(900, 750, overlays=True))
    assert _count_color(image, (255, 0, 255)) > 5
    assert _count_color(image, (0, 255, 255)) > 5


def test_color_by_layer_changes_existing_buffers_without_repainting_faces(cube_viewport):
    from core.layers import Layer
    from views.modeling_panel import ModelingPanel

    vp = cube_viewport
    scene = vp.scene
    scene.layers.append(Layer("Green", color=(0, 1, 0)))
    for face in scene.mesh.faces:
        face.attrs.update(color=(1, 0, 0), layer="Green")
    scene.version += 1
    style = scene.display_style = Style(sky=False, ground=False, face_mode="shaded")

    def center():
        return _pixels(vp.render_image(600, 500, overlays=False))[250, 300].astype(int)

    baseline = center()
    assert baseline[0] > baseline[1] + 80
    editor = ModelingPanel(lambda: scene, vp.update)
    try:
        editor.refresh()
        editor.visibility["color_by_layer"].setChecked(True)
        green = center()
        assert green[1] > green[0] + 80
        editor.visibility["color_by_layer"].setChecked(False)
        assert center() == pytest.approx(baseline, abs=2)
        assert all(face.attrs["color"] == (1, 0, 0) for face in scene.mesh.faces)
    finally:
        editor.close()
        editor.deleteLater()
