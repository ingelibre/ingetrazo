# SPDX-License-Identifier: GPL-3.0-or-later
"""The Rectangle shows the same inference markers as every other tool.

#1131 drew Rectangle's square markers as a small accent-coloured badge
beside the pencil. The familiar convention (checked 19-11) keeps each
inference in its own colour, on the point, whatever the drawing tool:
green endpoint, red on edge, and so on."""
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


SQUARE_KINDS = ['endpoint', 'origin', 'component_origin', 'on_edge',
                'on_axis', 'on_line', 'extension', 'from_point', 'aligned',
                'tangent', 'intersection_edge', 'intersection_face']


@pytest.mark.parametrize('kind', SQUARE_KINDS)
def test_rectangle_markers_are_the_line_markers(kind):
    snap = SnapResult(V(80, 80, 0), kind, COLOR_ENDPOINT)
    assert render(RectangleTool(), snap) == render(LineTool(), snap)


@pytest.mark.parametrize('accent', ['blue', 'purple'])
def test_an_endpoint_keeps_its_own_colour_with_any_accent(accent):
    previous = theme.saved_accent()
    try:
        theme.save_accent(accent)
        image = render(RectangleTool(),
                       SnapResult(V(80, 80, 0), 'endpoint', COLOR_ENDPOINT))
        green = QColor.fromRgbF(*COLOR_ENDPOINT)
        assert _near_color(image, 72, 72, 89, 89, green) > 15
        assert image.pixelColor(80, 52) == QColor(204, 204, 201)  # no badge
    finally:
        theme.save_accent(previous)


def test_origin_guide_stays_on_its_actual_geometry():
    snap = SnapResult(V(80, 80, 0), 'origin', COLOR_ORIGIN,
                      guide=(V(20, 80, 0), V(140, 80, 0)),
                      guide_color=(1., 0., 0.))
    image = render(RectangleTool(), snap)
    assert any(image.pixelColor(x, 80).red() > 235
               and image.pixelColor(x, 80).green() < 40 for x in range(25, 60))
    assert image.pixelColor(30, 60) == QColor(204, 204, 201)


def test_a_midpoint_keeps_its_own_marker():
    image = render(RectangleTool(), SnapResult(V(80, 80, 0), 'midpoint', COLOR_MIDPOINT))
    assert image.pixelColor(80, 71) != QColor(204, 204, 201)
