# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fog preserves the legacy sky and the 0.6.1 transparent PNG contract."""
import pytest

from core.style import Style
from tests.test_export_image_alpha import WIDTH, _at, view
from views.viewport import Viewport, fog_sky_colors


@pytest.mark.parametrize("enabled", [False, True])
def test_clear_fog_keeps_an_unset_horizon_and_the_legacy_gradient(enabled):
    style = Style(fog_enabled=enabled, fog_distance=40000.0,
                  fog_thickness=40000.0)
    colors = fog_sky_colors(style)
    assert colors == (style.sky_color, None, style.ground_color)
    assert "horizon_color" not in style.to_dict()
    sky_bottom, *_ = Viewport._sky_gradient(*colors, 0.0)
    assert sky_bottom == pytest.approx((0.96625, 0.97075, 0.97525))


def test_fog_does_not_fill_a_transparent_export_background(view):
    _window, viewport, _folder = view
    viewport.style_override = Style(fog_enabled=True, fog_distance=1.0,
                                    fog_thickness=2.0)
    image = viewport.render_image(WIDTH, overlays=False, transparent=True)
    assert image is not None
    assert _at(viewport, image, "background").alpha() == 0
    assert _at(viewport, image, "solid").alpha() == 255
    assert not viewport._export_transparent
