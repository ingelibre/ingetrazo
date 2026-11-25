# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""An extension that paints its own sky keeps working with fog.

Sky-photo extensions set ``viewport._draw_sky = painter.draw`` with the
0.6.2 signature ``draw(mvp)``. The frame must keep calling it that way: the
fog colours (#1139) are worked out inside ``_draw_sky`` itself.
"""
from core.style import Style
from tests.test_export_image_alpha import WIDTH, view  # noqa: F401


def test_an_own_sky_painter_with_the_old_signature_is_called(view):
    _window, viewport, _folder = view
    viewport.style_override = Style(fog_enabled=True, fog_distance=1.0,
                                    fog_thickness=2.0)
    calls = []
    viewport._draw_sky = lambda mvp: calls.append(mvp)
    try:
        image = viewport.render_image(WIDTH, overlays=False)
    finally:
        del viewport._draw_sky
    assert image is not None
    assert calls


def test_the_own_sky_without_an_override_still_takes_the_fog(view):
    _window, viewport, _folder = view
    seen = []
    cls = type(viewport)
    real = cls._sky_gradient            # a staticmethod: the bare function
    own = "_sky_gradient" in vars(cls)

    def spy(*args):
        seen.append(args[-1])
        return real(*args)

    viewport.style_override = Style(fog_enabled=True, fog_distance=1.0,
                                    fog_thickness=2.0)
    cls._sky_gradient = staticmethod(spy)
    try:
        assert viewport.render_image(WIDTH, overlays=False) is not None
    finally:
        if own:
            cls._sky_gradient = staticmethod(real)
        else:
            del cls._sky_gradient
    assert seen and seen[-1] > 0.9
