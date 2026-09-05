# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Traced georef paths show inside a sheet's model view (Marco, 2026-09-05:
next to the terrain profile he placed a model view of the same path "solo
que no se ve la línea del path en composiciones"). They ride the paper
overlay — the GL render comes back without the viewport's overlays and the
vector pass only knows edges — so every style shows them, whether or not
the frame opted into the model's dimensions."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QImage, QPainter, QVector3D
from PySide6.QtWidgets import QApplication, QWidget

from core.composition import MarcoVista
from georef.geopath import GeoPath
from tests.test_composer_canvas import _FakeViewport
from views.composer import ComposerWindow, paint_frame_mm

_app = QApplication.instance() or QApplication([])


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _composer(paths):
    host = QWidget()
    host.viewport = _FakeViewport()
    host.viewport.scene.geo_paths.extend(paths)
    composer = ComposerWindow(host)
    frame = composer.comp.frames[0]
    frame.view_key = "std:top"
    frame.x_mm, frame.y_mm, frame.w_mm, frame.h_mm = 10.0, 10.0, 200.0, 100.0
    frame.scale_n = 1000.0                 # 1 mm of paper per metre
    return composer, frame, host


def _polys(annots):
    return [a[1] for a in annots if a[0] == "poly"]


def test_a_traced_path_lands_on_paper_at_the_frame_scale():
    road = GeoPath([V(0, 0), V(50, 0), V(50, 20)], name="Eje")
    composer, frame, _host = _composer([road])
    assert frame.annotations is False       # no opt-in needed for paths
    annots = composer.compute_annotations(frame)
    polys = _polys(annots)
    assert len(polys) == 1 and len(polys[0]) == 3
    (x0, y0), (x1, y1), (x2, y2) = polys[0]
    # Plan view at 1:1000: 50 m east = 50 mm to the right, 20 m north =
    # 20 mm UP the sheet (paper y grows downwards).
    assert x1 - x0 == pytest.approx(50.0, abs=1e-6)
    assert y1 - y0 == pytest.approx(0.0, abs=1e-6)
    assert x2 - x1 == pytest.approx(0.0, abs=1e-6)
    assert y1 - y2 == pytest.approx(20.0, abs=1e-6)
    # Nothing else sneaks in while the frame has not opted into dimensions.
    assert {a[0] for a in annots} == {"poly"}


def test_a_closed_lot_closes_on_paper_and_lonely_nodes_are_skipped():
    lot = GeoPath([V(0, 0), V(30, 0), V(30, 30), V(0, 30)], closed=True)
    stub = GeoPath([V(5, 5)])               # a single click: nothing to draw
    composer, frame, _host = _composer([lot, stub])
    polys = _polys(composer.compute_annotations(frame))
    assert len(polys) == 1
    assert len(polys[0]) == 5 and polys[0][0] == polys[0][-1]


def test_render_frame_caches_the_paths_for_every_style():
    road = GeoPath([V(0, 0), V(40, 0)])
    composer, frame, host = _composer([road])
    host.viewport.render_image = lambda *a, **k: None    # no GL here
    for style in ("vectorial", "sombreado"):
        frame.style = style
        composer.annot_cache.pop(id(frame), None)
        composer.render_frame(frame)        # the fake viewport has no GL
        assert len(_polys(composer.annot_cache[id(frame)])) == 1


def test_the_path_is_painted_in_the_viewport_ink():
    road = GeoPath([V(-40, 0), V(40, 0)])
    composer, frame, _host = _composer([road])
    frame.style = "vectorial"
    composer.hlr_cache[id(frame)] = []      # an empty (but rendered) view
    annots = composer.compute_annotations(frame)
    (x0, y0), (x1, y1) = _polys(annots)[0]
    scale = 4.0                             # 4 px per mm
    img = QImage(int(frame.w_mm * scale), int(frame.h_mm * scale),
                 QImage.Format_RGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    painter.scale(scale, scale)
    paint_frame_mm(painter, frame, None, hlr=[], annots=annots)
    painter.end()
    mid = img.pixelColor(int((x0 + x1) / 2 * scale), int(y0 * scale))
    assert mid.blue() > 120 and mid.red() < 90        # cyan-ish ink
    # Off the line the paper is still white.
    off = img.pixelColor(int((x0 + x1) / 2 * scale), int((y0 + 15) * scale))
    assert off.red() == off.green() == off.blue() == 255


def test_chainage_marks_follow_the_profile_step():
    from core.composition import Composicion
    from views.composer import chainage_step
    road = GeoPath([V(0, 0), V(50, 0)])
    composer, frame, _host = _composer([road])
    assert frame.km_marks is False                    # opt-in, saved with the sheet
    frame.km_marks, frame.km_step_m = True, 20.0
    c = Composicion()
    c.frames.append(frame)
    back = Composicion.from_dict(c.to_dict()).frames[-1]
    assert back.km_marks is True and back.km_step_m == 20.0
    annots = composer.compute_annotations(frame)
    (x0, y0), _end = _polys(annots)[0]
    labels = [a for a in annots if a[0] == "text"]
    ticks = [a for a in annots if a[0] == "line"]
    # Every 20 m, plus the end of the path (10 m past the last mark).
    assert [t[4] for t in labels] == ["0+000", "0+020", "0+040", "0+050"]
    assert len(ticks) == 4
    # The 0+020 mark sits 20 mm along the road (1:1000) and its label
    # stands off the line, perpendicular to it.
    x20, y20 = labels[1][1], labels[1][2]
    assert x20 == pytest.approx(x0 + 20.0, abs=1e-6)
    assert abs(y20 - y0) > 1.0
    assert abs(labels[1][3]) == pytest.approx(90.0)
    # The tick crosses the road at that station.
    t = ticks[1]
    assert (t[1] + t[3]) / 2 == pytest.approx(x0 + 20.0, abs=1e-6)
    assert t[2] < y0 < t[4] or t[4] < y0 < t[2]
    # «auto» = the round step the profile picks for the same path.
    frame.km_step_m = 0.0
    auto = [a[4] for a in composer.compute_annotations(frame) if a[0] == "text"]
    assert chainage_step(50.0) == 10.0
    assert auto == ["0+000", "0+010", "0+020", "0+030", "0+040", "0+050"]
