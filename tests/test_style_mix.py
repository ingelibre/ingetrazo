# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Mix individual categories without replacing styles or shared source data."""
from __future__ import annotations

from dataclasses import fields

import numpy as np
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QImage, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.style import BUILTIN_STYLES, Style, delete_user_style, save_user_style, user_styles
from core.style_mix import STYLE_CATEGORIES, mix_style_category
from tests.test_edge_rendering import cube_viewport  # noqa: F401 - native fixture
from tests.test_watermarks import _mark


@pytest.fixture
def library(tmp_path, monkeypatch):
    import core.style as styles

    monkeypatch.setattr(styles, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))


def test_every_style_setting_belongs_to_exactly_one_mix_category():
    grouped = [name for names in STYLE_CATEGORIES.values() for name in names]
    assert len(grouped) == len(set(grouped))
    assert set(grouped) == {field.name for field in fields(Style)} - {"name"}


def test_face_mix_retains_target_identity_edges_background_and_modeling():
    target = Style(name="Working", edges=False, profile_width=11, sky=False,
                   background=(0.1, 0.2, 0.3), show_guides=False, section_cut_width=8)
    source = Style(name="Sample", face_mode="monochrome", xray=True, xray_opacity=35,
                   material_transparency=False, transparency_quality="nicer",
                   front_color=(0.4, 0.5, 0.6), back_color=(0.6, 0.4, 0.2),
                   ambient_occlusion=True, ao_intensity=1.4)
    before = target.to_dict()
    mixed = mix_style_category(target, source, "faces")
    assert mixed.name == "Working" and mixed.face_mode == "monochrome" and mixed.xray
    assert mixed.xray_opacity == 35 and not mixed.material_transparency
    assert mixed.transparency_quality == "nicer" and mixed.front_color == source.front_color
    assert mixed.back_color == source.back_color and mixed.ambient_occlusion
    assert mixed.ao_intensity == 1.4
    assert not mixed.edges and mixed.profile_width == 11
    assert not mixed.sky and mixed.background == target.background
    assert not mixed.show_guides and mixed.section_cut_width == 8
    assert target.to_dict() == before


def test_edges_and_legacy_background_copy_their_disabled_values():
    target = Style(face_mode="shaded", ground=True, ground_transparency=50)
    source = Style(profile_width=7, profile_cap="round_extended", edge_color_mode="axis",
                   extensions=False, extension_length=-8, endpoints=True, endpoint_type="triangle",
                   endpoint_size=12, depth_cue=True, depth_cue_width=6, dashes=False)
    mixed = mix_style_category(target, source, "edges")
    assert mixed.profile_width == 7 and mixed.profile_cap == "round_extended"
    assert not mixed.extensions and mixed.extension_length == -8
    assert mixed.endpoint_type == "triangle" and mixed.endpoint_size == 12
    assert mixed.depth_cue and mixed.depth_cue_width == 6 and not mixed.dashes
    assert mixed.face_mode == "shaded" and mixed.ground_transparency == 50
    background = mix_style_category(mixed, Style(sky=True), "background")
    assert background.ground is None and background.sky and background.ground_transparency == 0
    assert background.profile_width == 7 and background.face_mode == "shaded"


def test_mixed_watermarks_replace_collection_and_mutable_settings_are_independent(tmp_path):
    red, blue = _mark(tmp_path), _mark(tmp_path, "blue", create_mask=True)
    target = Style(watermarks=[red], modeling_colors={"locked": (1, 0, 0)})
    source = Style(watermarks=[blue], watermarks_visible=False,
                   modeling_colors={"selected": (1, 0, 1)},
                   modeling_visibility={"show_axes": False}, section_cut_width=9)
    mixed = mix_style_category(target, source, "watermarks")
    assert mixed.watermarks == [blue] and not mixed.watermarks_visible
    assert mixed.modeling_colors == target.modeling_colors
    mixed.watermarks.clear()
    assert source.watermarks == [blue] and target.watermarks == [red]
    mixed = mix_style_category(target, source, "modeling")
    assert mixed.section_cut_width == 9 and mixed.modeling_visibility == {"show_axes": False}
    mixed.modeling_colors["selected"] = (0, 1, 0)
    mixed.modeling_visibility.clear()
    assert source.modeling_colors["selected"] == (1, 0, 1)
    assert source.modeling_visibility == {"show_axes": False}


def test_legacy_xray_and_unknown_mix_category():
    source = Style()
    source.face_mode = "xray"  # Historical scripting assignment.
    mixed = mix_style_category(Style(profile_width=5), source, "faces")
    assert mixed.face_mode == "textures" and mixed.xray and mixed.profile_width == 5
    with pytest.raises(ValueError):
        mix_style_category(Style(), source, "unknown")


def _editor():
    from tests.test_styles_window import _Window
    from views.tray import StylesPanel

    window = _Window()
    panel = StylesPanel(window)
    window.panel = panel
    panel._tabs.setCurrentIndex(2)
    return window, panel


def _select(panel, name, collection="builtin"):
    mix = panel._mix
    mix.collection.setCurrentIndex(mix.collection.findData(collection))
    for row in range(mix.browser.count()):
        if tuple(mix.browser.item(row).data(Qt.UserRole)) == (collection, name):
            mix.browser.setCurrentRow(row)
            return mix.browser.item(row)
    raise AssertionError(name)


def test_source_selection_does_not_apply_the_full_style(library):
    window, panel = _editor()
    try:
        scene = window.viewport.scene
        before = scene.display_style.to_dict()
        preset_before = [style.to_dict() for style in BUILTIN_STYLES]
        _select(panel, "Hidden line")
        assert scene.display_style.to_dict() == before
        panel._mix.targets["faces"].click()
        assert scene.display_style.name == before["name"]
        assert scene.display_style.face_mode == "hidden_line"
        assert scene.display_style.sky == before["sky"]
        assert panel._tabs.currentIndex() == 2
        assert panel._mix._source.name == "Hidden line"
        assert [style.to_dict() for style in BUILTIN_STYLES] == preset_before
        assert window.status_bar.messages
    finally:
        panel.close()
        panel.deleteLater()


def test_mix_drag_drop_and_foreign_mime(library):
    window, panel = _editor()
    try:
        item = _select(panel, "Hidden line")
        mix = panel._mix
        mime = mix.browser.mimeData([item])
        target = mix.targets["background"]
        enter = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(target, enter)
        assert enter.isAccepted()
        move = QDragMoveEvent(QPoint(8, 8), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(target, move)
        assert move.isAccepted() and move.dropAction() == Qt.CopyAction
        drop = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(target, drop)
        assert drop.isAccepted() and not target.isDown()
        assert not window.viewport.scene.display_style.sky
        assert window.viewport.scene.display_style.face_mode == "textures"
        foreign = QMimeData()
        foreign.setText("not a source style")
        assert mix._resolve_drop(foreign) is None
    finally:
        panel.close()
        panel.deleteLater()


def test_modeling_only_applies_its_scene_visibility(library):
    from core.guide import Guide

    source = Style(name="Cue source", profile_width=6, show_guides=False,
                   modeling_visibility={"show_axes": False, "show_section_cuts": False})
    save_user_style(source)
    window, panel = _editor()
    try:
        scene = window.viewport.scene
        guide = Guide(V())
        scene.guides.append(guide)
        scene.selection.add(guide)
        _select(panel, "Cue source", "user")
        panel._mix.targets["edges"].click()
        assert scene.show_axes and scene.show_section_cuts and guide in scene.selection
        panel._mix.targets["modeling"].click()
        assert not scene.show_axes and not scene.show_section_cuts
        assert guide not in scene.selection and not scene.display_style.show_guides
        assert not panel._modeling.visibility["show_axes"].isChecked()
        assert scene.display_style.profile_width == 6
        assert user_styles()[0].to_dict() == source.to_dict()
    finally:
        panel.close()
        panel.deleteLater()


def test_source_deletion_clears_targets_without_resetting_the_mixed_style(library):
    save_user_style(Style(name="Wide edges", profile_width=9))
    window, panel = _editor()
    try:
        _select(panel, "Wide edges", "user")
        panel._mix.targets["edges"].click()
        before = window.viewport.scene.display_style.to_dict()
        delete_user_style("Wide edges")
        panel.refresh()
        assert panel._mix._source is None
        assert not any(button.isEnabled() for button in panel._mix.targets.values())
        assert window.viewport.scene.display_style.to_dict() == before
    finally:
        panel.close()
        panel.deleteLater()


def test_mixed_style_can_be_saved_and_recalled_in_views_and_igz(library, tmp_path, monkeypatch):
    from core.camera import OrbitCamera
    from core.saved_views import SavedView
    from formats import igz

    source = Style(name="Signature", watermarks=[_mark(tmp_path)], face_mode="monochrome")
    save_user_style(source)
    monkeypatch.setattr("views.tray.QInputDialog.getText", lambda *a, **k: ("Mixed", True))
    window, panel = _editor()
    try:
        _select(panel, "Signature", "user")
        panel._mix.targets["watermarks"].click()
        panel._mix.targets["faces"].click()
        panel._on_save()
        scene = window.viewport.scene
        assert scene.display_style.name == "Mixed"
        assert panel._mix._source.name == "Signature"
        scene.mesh.add_edge(V(), V(1, 0, 0))
        view = SavedView.capture("Mixed", scene, OrbitCamera())
        igz.save_scene(scene, tmp_path / "mixed.igz")
        from core.scene import Scene
        loaded = Scene()
        igz.load_into(loaded, tmp_path / "mixed.igz")
        assert loaded.display_style.to_dict() == scene.display_style.to_dict()
        loaded.display_style = Style()
        view.apply(loaded, OrbitCamera())
        assert loaded.display_style.to_dict() == scene.display_style.to_dict()
        assert next(style for style in user_styles() if style.name == "Signature").to_dict() == source.to_dict()
    finally:
        panel.close()
        panel.deleteLater()


def test_mixed_edges_change_real_render_without_switching_faces(cube_viewport, library):
    from tests.test_styles_window import _Window
    from views.tray import StylesPanel

    vp = cube_viewport
    vp.scene.display_style = Style(name="Working", sky=False, ground=False,
                                   background=(1, 1, 1), face_mode="monochrome")
    save_user_style(Style(name="Red edges", profile_width=8, edge_color=(1, 0, 0),
                          face_mode="wireframe", background=(0, 0, 1)))
    window = _Window()
    window.viewport = vp
    panel = StylesPanel(window)
    window.panel = panel

    def pixels():
        image = vp.render_image(600, 500, overlays=False).convertToFormat(QImage.Format_RGBA8888)
        return np.frombuffer(image.constBits(), dtype=np.uint8).copy().reshape(
            (500, image.bytesPerLine() // 4, 4))[:, :600, :3]

    try:
        baseline = pixels()
        _select(panel, "Red edges", "user")
        assert np.array_equal(pixels(), baseline)
        panel._mix.targets["edges"].click()
        mixed = pixels()
        assert ((mixed[:, :, 0] > 220) & (mixed[:, :, 1] < 20) & (mixed[:, :, 2] < 20)).sum() > 50
        projected = (vp.camera.projection_matrix() * vp.camera.view_matrix()).map(V(1, 0, 0))
        x, y = round((projected.x() + 1) * 300), round((1 - projected.y()) * 250)
        assert mixed[y, x].astype(int) == pytest.approx(baseline[y, x].astype(int), abs=2)
        assert vp.scene.display_style.face_mode == "monochrome"
        assert vp.scene.display_style.background == (1, 1, 1)
    finally:
        panel.close()
        panel.deleteLater()
