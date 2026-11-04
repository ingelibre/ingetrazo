# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Portable image layers, live editing and their real viewport composition."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QVector3D as V

from core.scene import Scene
from core.style import Style
from core.watermark import Watermark, load_watermarks
from tests.test_edge_rendering import cube_viewport  # noqa: F401 - native fixture
from views.watermarks import import_image, paint_watermarks, watermark_image


def _mark(tmp_path, color="red", **values):
    path = tmp_path / (color + ".png")
    image = QImage(16, 16, QImage.Format_RGBA8888)
    image.fill(QColor(color))
    assert image.save(str(path))
    return replace(Watermark.create(color, import_image(str(path))), **values)


def _paint(style, layer="foreground", size=QSize(100, 100)):
    image = QImage(size, QImage.Format_RGBA8888)
    image.fill(QColor("white"))
    painter = QPainter(image)
    paint_watermarks(painter, style, size, layer)
    painter.end()
    return image


def test_images_remain_portable_after_original_file_is_deleted(tmp_path, monkeypatch):
    from core import style as library
    from core.camera import OrbitCamera
    from core.saved_views import SavedView
    from formats import igz

    monkeypatch.setattr(library, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))
    mark = _mark(tmp_path, opacity=37, layer="background", placement="tiled")
    (tmp_path / "red.png").unlink()
    style = Style(name="Portable", watermarks=[mark], watermarks_visible=False)
    library.save_user_style(style)
    assert library.style_by_name("Portable").to_dict() == style.to_dict()
    scene = Scene()
    scene.display_style = style
    scene.mesh.add_edge(V(), V(1, 0, 0))
    view = SavedView.capture("Branded", scene, OrbitCamera())
    igz.save_scene(scene, tmp_path / "branded.igz")
    loaded = Scene()
    igz.load_into(loaded, tmp_path / "branded.igz")
    assert loaded.display_style.to_dict() == style.to_dict()
    assert watermark_image(loaded.display_style.watermarks[0].image).pixelColor(8, 8) == QColor("red")
    loaded.display_style = Style()
    view.apply(loaded, OrbitCamera())
    assert loaded.display_style.to_dict() == style.to_dict()
    copy = style.copy()
    copy.watermarks.clear()
    assert len(style.watermarks) == 1


def test_old_styles_and_malformed_entries_are_safe():
    old = Style.from_dict({})
    assert old.watermarks == [] and old.watermarks_visible
    assert "watermarks" not in old.to_dict() and "watermarks_visible" not in old.to_dict()
    assert load_watermarks("bad") == []
    assert load_watermarks([None, {}, {"image": 5}]) == []
    mark = Watermark.from_dict({"image": "broken", "opacity": 200, "scale": -4,
                                "anchor": 99, "placement": "unknown", "layer": "bad"})
    assert mark.opacity == 100 and mark.scale == 1 and mark.anchor == 8
    assert mark.layer == "foreground" and mark.placement == "positioned"
    assert watermark_image(mark.image).isNull()


def test_import_rejects_an_unreadable_image(tmp_path):
    path = tmp_path / "bad.png"
    path.write_text("not an image", encoding="utf-8")
    with pytest.raises(ValueError):
        import_image(str(path))


def test_position_opacity_visibility_and_layer_order(tmp_path):
    red = _mark(tmp_path)
    style = Style(watermarks=[red])
    image = _paint(style)
    assert image.pixelColor(85, 85) == QColor("red")
    assert image.pixelColor(50, 50) == QColor("white")
    blue = _mark(tmp_path, "blue", opacity=50)
    style.watermarks.insert(0, blue)
    color = _paint(style).pixelColor(85, 85)
    assert color.red() == pytest.approx(127, abs=1) and color.blue() == pytest.approx(128, abs=1)
    style.watermarks.reverse()
    assert _paint(style).pixelColor(85, 85) == QColor("red")
    style.watermarks_visible = False
    assert _paint(style).pixelColor(85, 85) == QColor("white")
    style.watermarks_visible = True
    style.watermarks = [replace(red, visible=False)]
    assert _paint(style).pixelColor(85, 85) == QColor("white")
    style.watermarks = [replace(red, layer="background")]
    assert _paint(style).pixelColor(85, 85) == QColor("white")
    assert _paint(style, "background").pixelColor(85, 85) == QColor("red")


def test_thumbnail_keeps_legacy_backdrop_behind_background_image(tmp_path):
    from views.style_preview import style_preview

    mark = _mark(tmp_path, placement="stretched", layer="background")
    image = style_preview(Style(watermarks=[mark]), QSize(100, 80)).toImage()
    assert image.pixelColor(95, 75) == QColor("red")


@pytest.mark.parametrize("placement", ["stretched", "tiled"])
def test_fill_modes_and_relative_export_sizing(tmp_path, placement):
    mark = _mark(tmp_path, placement=placement)
    for size in (QSize(100, 100), QSize(400, 200)):
        image = _paint(Style(watermarks=[mark]), size=size)
        assert image.pixelColor(1, 1) == QColor("red")
        assert image.pixelColor(size.width() - 2, size.height() - 2) == QColor("red")
    positioned = replace(mark, placement="positioned", anchor=0)
    small = _paint(Style(watermarks=[positioned]))
    large = _paint(Style(watermarks=[positioned]), size=QSize(400, 400))
    assert small.pixelColor(15, 15) == large.pixelColor(60, 60) == QColor("red")
    assert small.pixelColor(40, 40) == large.pixelColor(160, 160) == QColor("white")


def test_stretched_proportions_crop_instead_of_distorting(tmp_path):
    image = QImage(8, 2, QImage.Format_RGBA8888)
    image.fill(QColor("red"))
    for x in (0, 1):
        for y in (0, 1):
            image.setPixelColor(x, y, QColor("green"))
    path = tmp_path / "wide.png"
    assert image.save(str(path))
    mark = replace(Watermark.create("Wide", import_image(str(path))), placement="stretched")
    assert _paint(Style(watermarks=[mark])).pixelColor(10, 10) == QColor("red")
    mark = replace(mark, keep_aspect=False)
    assert _paint(Style(watermarks=[mark])).pixelColor(10, 10) == QColor("green")


def test_editor_import_edit_order_and_remove(tmp_path, monkeypatch):
    from core import style as library
    from tests.test_styles_window import _Window
    from views.tray import StylesPanel

    monkeypatch.setattr(library, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))
    _mark(tmp_path)
    _mark(tmp_path, "blue")
    window = _Window()
    panel = StylesPanel(window)
    window.panel = panel
    editor = panel._watermarks
    try:
        assert not editor.options.isEnabled()
        assert editor.add_image(str(tmp_path / "red.png"))
        red_id = editor._selected().id
        editor.opacity_slider.setValue(37)
        editor.layer.setCurrentIndex(editor.layer.findData("background"))
        editor.placement.setCurrentIndex(editor.placement.findData("tiled"))
        assert editor._selected().opacity == 37 and editor.opacity.value() == 37
        assert editor._selected().layer == "background" and not editor.anchor.isEnabled()
        editor.display.setChecked(False)
        assert not window.viewport.scene.display_style.watermarks_visible
        assert editor._selected().opacity == 37
        editor.add_image(str(tmp_path / "blue.png"))
        editor.down.click()
        assert window.viewport.scene.display_style.watermarks[0].id == red_id
        assert editor._selected().name == "blue"
        editor.remove.click()
        assert editor._selected().id == red_id
        editor.remove.click()
        assert not editor.options.isEnabled()
        assert window.viewport.scene.display_style.watermarks == []
    finally:
        panel.close()
        panel.deleteLater()


def _render(vp, size=(600, 500)):
    image = vp.render_image(*size, overlays=False).convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(image.constBits(), dtype=np.uint8).copy().reshape(
        (size[1], image.bytesPerLine() // 4, 4))[:, :size[0], :3]


def test_real_background_and_foreground_do_not_change_model_depth(cube_viewport, tmp_path):
    vp = cube_viewport
    style = vp.scene.display_style = Style(sky=False, ground=False, edges=False,
                                           profiles=False, face_mode="monochrome",
                                           front_color=(0, 1, 0), back_color=(0, 1, 0),
                                           background=(1, 1, 1))
    baseline = _render(vp)
    mark = _mark(tmp_path, placement="stretched", layer="background")
    style.watermarks = [mark]
    behind = _render(vp)
    assert behind[10, 10] == pytest.approx((255, 0, 0), abs=2)
    assert behind[250, 300] == pytest.approx(baseline[250, 300], abs=2)
    style.watermarks = [replace(mark, layer="foreground", opacity=50)]
    front = _render(vp)
    assert front[250, 300] == pytest.approx(
        baseline[250, 300] * 0.5 + np.array([255, 0, 0]) * 0.5, abs=3)
    style.watermarks_visible = False
    assert np.array_equal(_render(vp), baseline)


def test_live_watermark_refresh_and_export_match(cube_viewport, tmp_path):
    from PySide6.QtWidgets import QApplication

    vp = cube_viewport
    mark = _mark(tmp_path, placement="stretched")
    vp.scene.display_style.watermarks = [mark]
    for _ in range(3):
        vp.update()
        QApplication.processEvents()
    live = vp.grabFramebuffer()
    assert live.pixelColor(10, 10) == QColor("red")
    exported = _render(vp, (1200, 1000))
    assert exported[10, 10] == pytest.approx((255, 0, 0), abs=2)
    vp.scene.display_style.watermarks[0] = replace(mark, visible=False)
    vp.update()
    QApplication.processEvents()
    assert vp.grabFramebuffer().pixelColor(10, 10) != QColor("red")


def test_png_transparent_pixels_survive_opaque_material_mode(cube_viewport, tmp_path):
    vp = cube_viewport
    style = vp.scene.display_style = Style(sky=False, ground=False,
                                           material_transparency=False)
    baseline = _render(vp)
    image = QImage(16, 16, QImage.Format_RGBA8888)
    image.fill(Qt.transparent)
    for x in range(8):
        for y in range(16):
            image.setPixelColor(x, y, QColor("red"))
    path = tmp_path / "cutout.png"
    assert image.save(str(path))
    mark = Watermark.create("Cutout", import_image(str(path)))
    style.watermarks = [replace(mark, placement="stretched")]
    rendered = _render(vp)
    assert rendered[250, 100] == pytest.approx((255, 0, 0), abs=2)
    assert np.array_equal(rendered[:, 400:], baseline[:, 400:])
