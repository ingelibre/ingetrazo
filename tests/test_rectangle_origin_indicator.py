# SPDX-License-Identifier: GPL-3.0-or-later
"""The Rectangle badge leaves the actual source point visible."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QVector3D as V

from core.snap import COLOR_ENDPOINT, COLOR_ORIGIN, COLOR_MIDPOINT, SnapResult
from tools.line import LineTool
from tools.rectangle import RectangleTool
from views import theme
from views.viewport import Viewport


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from core import general_settings
    settings = QSettings(str(tmp_path / 'rectangle-origin.ini'), QSettings.IniFormat)
    monkeypatch.setattr(general_settings, 'QSettings', lambda: settings)


def render(tool, snap, cursor=None):
    image = QImage(180, 140, QImage.Format_ARGB32)
    image.fill(QColor(204, 204, 201))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    vp = SimpleNamespace(active_tool=tool, _SNAP_LABELS={},
                         _last_mouse_pos=cursor,
                         _world_to_pixel=lambda p: (p.x(), p.y()),
                         _clip_pixel_line=lambda a, b: (a, b))
    Viewport._draw_snap_indicator(vp, painter, snap)
    painter.end()
    return image


def _near_color(image, x0, y0, x1, y1, color):
    # The current tester uses thin, antialiased strokes and a translucent
    # fill. Blending changes RGB distance; the selected hue still survives.
    def matches(pixel):
        delta = abs(pixel.hslHue() - color.hslHue())
        return min(delta, 360 - delta) < 8 and pixel.hslSaturationF() > color.hslSaturationF() * 0.15
    return sum(matches(image.pixelColor(x, y))
               for x in range(x0, x1) for y in range(y0, y1))


@pytest.mark.parametrize('accent,mode', [('blue', theme.LIGHT), ('purple', theme.DARK)])
def test_origin_badge_is_offset_and_uses_the_live_accent(accent, mode):
    from PySide6.QtWidgets import QApplication
    previous_accent, previous_theme = theme.saved_accent(), theme.saved_theme()
    try:
        theme.save_accent(accent)
        theme.apply_theme(QApplication.instance(), mode)
        image = render(RectangleTool(), SnapResult(V(80, 80, 0), 'origin', COLOR_ORIGIN))
        color = theme.accent_color()
        assert color == theme.accent_color(accent)
        assert _near_color(image, 79, 55, 90, 66, color) > 15
        assert _near_color(image, 78, 78, 83, 83, color) > 0  # exact source dot
        # No large square remains around the pencil tip.
        assert image.pixelColor(73, 73) == QColor(204, 204, 201)
    finally:
        theme.save_accent(previous_accent)
        theme.apply_theme(QApplication.instance(), previous_theme)


@pytest.mark.parametrize('kind', ['endpoint', 'component_origin', 'on_edge', 'on_axis',
                                  'on_line', 'extension', 'from_point', 'aligned', 'tangent',
                                  'intersection_edge', 'intersection_face'])
def test_every_rectangle_square_marker_leaves_the_pencil_tip_clear(kind):
    theme.save_accent('blue')
    image = render(RectangleTool(), SnapResult(V(80, 80, 0), kind, COLOR_ENDPOINT))
    assert _near_color(image, 79, 55, 90, 66, theme.accent_color()) > 15
    assert image.pixelColor(73, 73) == QColor(204, 204, 201)


def test_other_tools_and_non_square_snap_shapes_keep_their_markers():
    image = render(LineTool(), SnapResult(V(80, 80, 0), 'origin', COLOR_ORIGIN))
    assert image.pixelColor(73, 73) != QColor(204, 204, 201)
    assert image.pixelColor(64, 56) == QColor(204, 204, 201)
    image = render(RectangleTool(), SnapResult(V(80, 80, 0), 'midpoint', COLOR_MIDPOINT))
    assert image.pixelColor(80, 71) != QColor(204, 204, 201)
    assert image.pixelColor(64, 56) == QColor(204, 204, 201)


def test_origin_guide_stays_on_its_actual_geometry():
    snap = SnapResult(V(80, 80, 0), 'origin', COLOR_ORIGIN,
                      guide=(V(20, 80, 0), V(140, 80, 0)),
                      guide_color=(1., 0., 0.))
    image = render(RectangleTool(), snap)
    assert any(image.pixelColor(x, 80).red() > 235
               and image.pixelColor(x, 80).green() < 40 for x in range(25, 60))
    assert image.pixelColor(30, 60) == QColor(204, 204, 201)


def test_badge_aligns_with_actual_pencil_when_pointer_is_offset_from_snap():
    theme.save_accent('blue')
    image = render(RectangleTool(), SnapResult(V(80, 80, 0), 'origin', COLOR_ORIGIN),
                   cursor=QPointF(92, 72))
    assert _near_color(image, 91, 47, 102, 58, theme.accent_color()) > 15
    assert _near_color(image, 78, 78, 83, 83, theme.accent_color()) > 0
    assert image.pixelColor(73, 61) == QColor(204, 204, 201)
