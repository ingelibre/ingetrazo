# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The composer's sacred math: paper mm × scale → metres of model, and the
camera settings that realise it (docs/composer-plan.md)."""
import math

import pytest

from core.composition import (Composicion, MarcoVista, apply_frame_camera,
                              mm_to_px, model_height_for_frame,
                              ortho_distance_for_height)


class TestScaleMath:
    def test_1_100_on_200mm_is_20m(self):
        assert model_height_for_frame(200.0, 100) == pytest.approx(20.0)

    def test_1_50_on_297mm(self):
        assert model_height_for_frame(297.0, 50) == pytest.approx(14.85)

    def test_invalid_inputs_raise(self):
        with pytest.raises(ValueError):
            model_height_for_frame(0, 100)
        with pytest.raises(ValueError):
            model_height_for_frame(100, -5)

    def test_ortho_distance_inverts_the_camera_projection(self):
        # OrbitCamera's parallel half-height is distance·tan(fov/2); the
        # inverse must reproduce the requested height exactly.
        for fov in (30.0, 45.0, 60.0):
            d = ortho_distance_for_height(20.0, fov)
            half_h = d * math.tan(math.radians(fov) / 2.0)
            assert 2 * half_h == pytest.approx(20.0)

    def test_mm_to_px_at_300dpi(self):
        # The DoD number: 10 mm at 300 dpi is 118 px.
        assert mm_to_px(10.0, 300) == 118
        assert mm_to_px(25.4, 300) == 300


class TestComposicion:
    def test_page_size_landscape_swaps(self):
        c = Composicion(paper="A4", landscape=False)
        assert c.page_size_mm() == (210.0, 297.0)
        c.landscape = True
        assert c.page_size_mm() == (297.0, 210.0)

    def test_default_frame_fits_margins(self):
        c = Composicion(paper="A3", landscape=True, margin_mm=10.0)
        f = c.default_frame()
        pw, ph = c.page_size_mm()
        assert f.x_mm == f.y_mm == 10.0
        assert f.w_mm == pw - 20.0
        assert f.h_mm == ph - 20.0

    def test_frame_render_px_follows_dpi(self):
        f = MarcoVista(w_mm=254.0, h_mm=127.0)
        assert f.render_px(300) == (3000, 1500)


class _FakeCamera:
    """Just enough of OrbitCamera for apply_frame_camera."""

    def __init__(self):
        self.fov_deg = 45.0
        self.perspective = True
        self.distance = 7.0
        self.aspect = 1.6
        self.applied_std = None

    def set_view(self, key):
        self.applied_std = key


class TestApplyFrameCamera:
    def test_scale_realised_through_the_camera(self):
        cam = _FakeCamera()
        f = MarcoVista(w_mm=170.0, h_mm=200.0, scale_n=100.0,
                       view_key="std:top")
        apply_frame_camera(cam, f)
        assert cam.applied_std == "top"
        assert cam.perspective is False
        half_h = cam.distance * math.tan(math.radians(cam.fov_deg) / 2.0)
        assert 2 * half_h == pytest.approx(20.0)   # 200 mm at 1:100
        w_px, h_px = f.render_px()
        assert cam.aspect == pytest.approx(w_px / h_px)
