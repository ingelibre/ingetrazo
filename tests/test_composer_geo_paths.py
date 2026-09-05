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
