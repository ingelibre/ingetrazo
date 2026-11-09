# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fog display-style data and its live panel.

The rendering pass has separate, pure tests below where possible.  These
widget tests deliberately stop before OpenGL: they protect the document and
UI contract on headless CI runners as well as on machines with a GPU.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QVector3D
from PySide6.QtWidgets import QApplication

from core.camera import OrbitCamera
from core.scene import Scene
from core.style import (BUILTIN_STYLES, FOG_DISTANCE_RANGE,
                        FOG_THICKNESS_RANGE, Style)


_app = QApplication.instance() or QApplication(sys.argv[:1])


def test_fog_defaults_off_and_builtin_styles_keep_it_off():
    style = Style()
    assert style.fog_enabled is False
    assert style.fog_use_background is False
    assert style.fog_distance == 10.0
    assert style.fog_thickness == 10.0
    assert FOG_DISTANCE_RANGE == (0.0, 40000.0)
    assert FOG_THICKNESS_RANGE == (0.01, 40000.0)
    assert FOG_DISTANCE_RANGE[0] <= style.fog_distance <= FOG_DISTANCE_RANGE[1]
    assert FOG_THICKNESS_RANGE[0] <= style.fog_thickness <= FOG_THICKNESS_RANGE[1]
    assert len(style.fog_color) == 3
    assert all(0.0 <= channel <= 1.0 for channel in style.fog_color)
    assert all(not preset.fog_enabled for preset in BUILTIN_STYLES)


def test_fog_style_round_trip_keeps_every_setting():
    original = Style(fog_enabled=True, fog_distance=14.0,
                     fog_thickness=23.0, fog_color=(0.2, 0.4, 0.6),
                     fog_use_background=True)
    restored = Style.from_dict(original.to_dict())
    assert restored.fog_enabled is True
    assert restored.fog_distance == pytest.approx(14.0)
    assert restored.fog_thickness == pytest.approx(23.0)
    assert restored.fog_color == pytest.approx((0.2, 0.4, 0.6))
    assert restored.fog_use_background is True


def test_document_and_saved_view_keep_the_fog(tmp_path):
    from core.saved_views import SavedView
    from formats import igz as igz_format

    scene = Scene()
    scene.mesh.add_edge(QVector3D(), QVector3D(1, 0, 0))
    scene.display_style = Style(
        fog_enabled=True, fog_distance=18.0, fog_thickness=42.0,
        fog_color=(0.3, 0.5, 0.7), fog_use_background=True)

    path = tmp_path / "fog.igz"
    igz_format.save_scene(scene, path)
    loaded = Scene()
    igz_format.load_into(loaded, path)
    assert loaded.display_style.to_dict() == scene.display_style.to_dict()

    camera = OrbitCamera()
    saved = SavedView.capture("Fog", scene, camera)
    recalled = SavedView.from_dict(saved.to_dict())
    loaded.display_style = Style()
    recalled.apply(loaded, camera)
    assert loaded.display_style.to_dict() == scene.display_style.to_dict()


def test_legacy_style_gets_the_non_foggy_defaults():
    raw = Style(fog_enabled=True, fog_distance=0.8, fog_thickness=0.7,
                fog_color=(1.0, 0.0, 0.0),
                fog_use_background=True).to_dict()
    for key in ("fog_enabled", "fog_distance", "fog_thickness",
                "fog_color", "fog_use_background"):
        raw.pop(key)
    restored = Style.from_dict(raw)
    default = Style()
    assert restored.fog_enabled is False
    assert restored.fog_distance == default.fog_distance
    assert restored.fog_thickness == default.fog_thickness
    assert restored.fog_color == default.fog_color
    assert restored.fog_use_background is False


def test_bad_fog_values_are_safe_and_clamped():
    restored = Style.from_dict({
        "fog_enabled": True,
        "fog_distance": -100,
        "fog_thickness": 100000,
        "fog_color": (-4, 0.4, 9, 0.1),
    })
    assert restored.fog_distance == FOG_DISTANCE_RANGE[0]
    assert restored.fog_thickness == FOG_THICKNESS_RANGE[1]
    assert restored.fog_color == pytest.approx((0.0, 0.4, 1.0))

    default = Style()
    malformed = Style.from_dict({
        "fog_distance": "near",
        "fog_thickness": float("nan"),
        "fog_color": "grey",
    })
    assert malformed.fog_distance == default.fog_distance
    assert malformed.fog_thickness == default.fog_thickness
    assert malformed.fog_color == default.fog_color


class _Viewport:
    def __init__(self):
        self.scene = Scene()
        self.updates = 0

    def update(self):
        self.updates += 1


class _Window:
    def __init__(self):
        self.viewport = _Viewport()


def test_depth_controls_are_absolute_distances_from_the_camera():
    """Start is distance; end is distance + thickness, both in metres."""
    from views.viewport import fog_depth_range

    assert fog_depth_range(14.0, 23.0) == pytest.approx((14.0, 37.0))
    assert fog_depth_range(0.0, 10.0) == pytest.approx((0.0, 10.0))


def test_bad_absolute_depths_are_finite_and_bounded():
    from math import isfinite
    from views.viewport import fog_depth_range

    start, end = fog_depth_range(float("nan"), -5)
    assert isfinite(start) and isfinite(end)
    assert start == Style().fog_distance
    assert end == pytest.approx(start + FOG_THICKNESS_RANGE[0])
    assert fog_depth_range(float("nan"), float("nan")) == pytest.approx(
        (Style().fog_distance,
         Style().fog_distance + Style().fog_thickness))
    assert fog_depth_range(1e9, 1e9) == pytest.approx(
        (FOG_DISTANCE_RANGE[1],
         FOG_DISTANCE_RANGE[1] + FOG_THICKNESS_RANGE[1]))


def test_effective_fog_color_uses_custom_or_background_and_falls_back():
    from views.viewport import effective_fog_color

    custom = Style(fog_enabled=True, fog_color=(0.1, 0.2, 0.3),
                   background=(0.7, 0.8, 0.9))
    assert effective_fog_color(custom) == pytest.approx((0.1, 0.2, 0.3))

    custom.fog_use_background = True
    assert effective_fog_color(custom) == pytest.approx((0.7, 0.8, 0.9))

    clamped = SimpleNamespace(fog_use_background=False,
                              fog_color=(-4, 0.4, 9))
    assert effective_fog_color(clamped) == pytest.approx((0.0, 0.4, 1.0))

    bad_custom = SimpleNamespace(fog_use_background=False,
                                 fog_color=(float("nan"), 0.2, 0.3))
    assert effective_fog_color(bad_custom) == pytest.approx(
        Style().fog_color)
    bad_background = SimpleNamespace(fog_use_background=True,
                                     background="not a color")
    assert effective_fog_color(bad_background) == pytest.approx(
        Style().background)


def test_environment_fogs_like_sketchup_and_clears_at_farthest_stop():
    from views.viewport import (fog_backdrop, fog_backdrop_strength,
                                fog_sky_colors)

    near = Style(
        fog_enabled=True, fog_distance=FOG_DISTANCE_RANGE[0],
        fog_thickness=FOG_THICKNESS_RANGE[0], fog_color=(0.0, 0.0, 0.0),
        background=(1.0, 1.0, 1.0), sky=True,
        sky_color=(1.0, 0.0, 0.0), horizon_color=(0.0, 1.0, 0.0),
        ground_color=(0.0, 0.0, 1.0))
    assert fog_backdrop_strength(near) == pytest.approx(1.0)
    clear, draw_sky = fog_backdrop(near)
    assert draw_sky is True
    assert clear == pytest.approx((0.0, 0.0, 0.0))
    expected_near = ((0.0, 0.0, 0.0),
                     (0.0, 0.0, 0.0),
                     (0.0, 0.0, 0.85))
    for got, expected in zip(fog_sky_colors(near), expected_near):
        assert got == pytest.approx(expected)

    default = Style(fog_enabled=True)
    assert fog_backdrop_strength(default) == pytest.approx(1.0)
    assert fog_backdrop_strength(
        SimpleNamespace(fog_enabled=True)) == pytest.approx(1.0)

    transition = near.copy()
    transition.fog_distance = 30000.0
    transition.fog_thickness = FOG_THICKNESS_RANGE[0]
    assert 0.0 < fog_backdrop_strength(transition) < 1.0

    far = near.copy()
    far.fog_distance = FOG_DISTANCE_RANGE[1]
    far.fog_thickness = FOG_THICKNESS_RANGE[1]
    # At the farthest stop the styled environment is completely restored.
    assert fog_backdrop_strength(far) == pytest.approx(0.0)
    clear, draw_sky = fog_backdrop(far)
    assert draw_sky is True
    assert clear == pytest.approx(far.background)
    expected_far = (far.sky_color, far.horizon_color, far.ground_color)
    for got, expected in zip(fog_sky_colors(far), expected_far):
        if expected is None:
            assert got is None
        else:
            assert got == pytest.approx(expected)

    from views.viewport import Viewport
    gradient = Viewport._sky_gradient(
        expected_near[0], expected_near[1], expected_near[2], 0.0, 1.0)
    assert gradient[2] == pytest.approx(expected_near[1])
    assert gradient[3] == pytest.approx(expected_near[2])
    assert gradient[4] == pytest.approx(expected_near[1])

    far.fog_enabled = False
    assert fog_backdrop_strength(far) == 0.0


def test_dual_handle_track_pushes_end_and_never_crosses():
    from views.tray import _FogRangeSlider

    slider = _FogRangeSlider()
    changes = []
    slider.positionsChanged.connect(
        lambda start, end: changes.append((start, end)))
    try:
        slider.setRange(0, 100)
        slider.setPositions(20, 60)
        assert (slider.startPosition(), slider.endPosition()) == (20, 60)

        slider._active = "start"
        slider._move_active(80)
        assert (slider.startPosition(), slider.endPosition()) == (80, 80)

        slider._active = "end"
        slider._move_active(10)
        assert (slider.startPosition(), slider.endPosition()) == (80, 80)
        slider._move_active(95)
        assert (slider.startPosition(), slider.endPosition()) == (80, 95)
        assert changes[-1] == (80, 95)
    finally:
        slider.close()


def test_fog_panel_edits_dual_range_live_in_model_units(monkeypatch):
    from core import units
    from views.tray import FogPanel, _FogRangeSlider

    monkeypatch.setattr(units, "model_unit", lambda: "cm")
    window = _Window()
    panel = FogPanel(window)
    try:
        style = window.viewport.scene.display_style
        style.background = (0.12, 0.34, 0.56)
        panel.refresh()
        assert isinstance(panel._range, _FogRangeSlider)
        assert panel._range.startPosition() == panel._distance_pos(
            style.fog_distance)
        assert panel._range.endPosition() == panel._distance_pos(
            style.fog_distance + style.fog_thickness)
        assert not panel._enable.isChecked()
        assert not panel._range.isEnabled()
        assert not panel._range_val.isEnabled()
        assert not panel._use_background.isEnabled()
        assert not panel._color_lbl.isEnabled()
        assert not panel._color.isEnabled()

        panel._enable.setChecked(True)
        assert style.fog_enabled
        assert panel._range.isEnabled()
        assert panel._range_val.isEnabled()
        assert panel._use_background.isEnabled()
        assert panel._color_lbl.isEnabled()
        assert panel._color.isEnabled()

        assert panel._distance_at(0) == FOG_DISTANCE_RANGE[0]
        assert panel._distance_at(panel._FOG_SLIDER_STEPS) \
            == FOG_DISTANCE_RANGE[1]
        midpoint = panel._FOG_SLIDER_STEPS // 2
        assert panel._distance_at(midpoint) < FOG_DISTANCE_RANGE[1] / 10

        start_pos = panel._distance_pos(14.0)
        end_pos = panel._distance_pos(37.0)
        panel._range.setPositions(start_pos, end_pos)
        start = panel._distance_at(start_pos)
        end = panel._distance_at(end_pos)
        assert style.fog_distance == pytest.approx(start)
        assert style.fog_thickness == pytest.approx(end - start)
        assert start == pytest.approx(14.0, rel=0.03)
        assert end == pytest.approx(37.0, rel=0.03)
        start_cm = units.length_number(start, "cm")
        end_cm = units.length_number(end, "cm")
        arrow = "\N{RIGHTWARDS ARROW}"
        assert panel._range_val.text() == (
            f"{units.localized(f'{start_cm:.2f}')} {arrow} "
            f"{units.localized(f'{end_cm:.2f}')} cm")
        assert "%" not in panel._range_val.text()

        panel._use_background.setChecked(True)
        assert style.fog_use_background
        assert "rgb(31,87,143)" in panel._color.styleSheet()
        assert not panel._color_lbl.isEnabled()
        assert not panel._color.isEnabled()
        panel._use_background.setChecked(False)
        assert not style.fog_use_background
        assert panel._color_lbl.isEnabled()
        assert panel._color.isEnabled()
        assert window.viewport.updates >= 4

        panel._enable.setChecked(False)
        assert not style.fog_enabled
        assert not panel._range.isEnabled()
        assert not panel._color.isEnabled()
    finally:
        panel.close()


def test_fog_panel_color_picker_updates_only_the_custom_color(monkeypatch):
    from views import tray

    window = _Window()
    panel = tray.FogPanel(window)
    try:
        style = window.viewport.scene.display_style
        panel._enable.setChecked(True)
        background = style.background
        monkeypatch.setattr(
            tray, "get_color", lambda *_a, **_k: QColor(51, 102, 153))
        before = window.viewport.updates
        panel._pick_color()
        assert style.fog_color == pytest.approx((0.2, 0.4, 0.6), abs=0.004)
        assert style.background == background
        assert "rgb(51,102,153)" in panel._color.styleSheet()
        assert window.viewport.updates == before + 1
    finally:
        panel.close()


class _UniformProgram:
    def __init__(self):
        self.values = {}

    def setUniformValue(self, location, value):
        self.values[location] = value

    def setUniformValue1f(self, location, value):
        self.values[location] = value


class _UniformViewport:
    def __init__(self):
        self.camera = OrbitCamera()
        self.camera.distance = 10.0
        self.camera.yaw = 0.0
        self.camera.pitch = 0.0
        self.scene = type("SceneBounds", (), {
            "bounds": lambda _self: (
                QVector3D(-10, -1, -1), QVector3D(0, 1, 1))
        })()
        self._program = _UniformProgram()
        self._loc_fog_enable = "enabled"
        self._loc_fog_eye = "eye"
        self._loc_fog_forward = "forward"
        self._loc_fog_color = "color"
        self._loc_fog_start = "start"
        self._loc_fog_end = "end"


def test_fog_uniforms_are_off_or_use_the_selected_color_source():
    from views.viewport import Viewport

    viewport = _UniformViewport()
    Viewport._apply_fog_uniforms(viewport, Style())
    assert viewport._program.values == {"enabled": 0}

    custom = Style(fog_enabled=True, fog_distance=14.0,
                   fog_thickness=23.0, fog_color=(0.1, 0.2, 0.3))
    Viewport._apply_fog_uniforms(viewport, custom)
    values = viewport._program.values
    assert values["enabled"] == 1
    assert values["start"] == pytest.approx(14.0)
    assert values["end"] == pytest.approx(37.0)
    assert (values["color"].x(), values["color"].y(), values["color"].z()) \
        == pytest.approx(custom.fog_color)

    custom.background = (0.7, 0.8, 0.9)
    custom.fog_use_background = True
    Viewport._apply_fog_uniforms(viewport, custom)
    color = viewport._program.values["color"]
    assert (color.x(), color.y(), color.z()) == pytest.approx(custom.background)

    first_eye = viewport._program.values["eye"]
    fixed_range = (viewport._program.values["start"],
                   viewport._program.values["end"])
    viewport.camera.move_eye(QVector3D(3, 4, 5))
    Viewport._apply_fog_uniforms(viewport, custom)
    moved_eye = viewport._program.values["eye"]
    assert (moved_eye.x(), moved_eye.y(), moved_eye.z()) != pytest.approx(
        (first_eye.x(), first_eye.y(), first_eye.z()))
    assert (viewport._program.values["start"],
            viewport._program.values["end"]) == pytest.approx(fixed_range)
