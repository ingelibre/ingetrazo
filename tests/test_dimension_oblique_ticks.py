# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Oblique ticks at 45° to the dimension line, «/» on a horizontal one, as
the technical-drawing standards draw them (#741). The sheet drew «\\»,
135° to the line, and the 3D view drew them square to it."""
from __future__ import annotations

import math
import sys

import pytest
from PySide6.QtGui import QImage, QPainter, QVector3D
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core.composition import CotaAngularItem, CotaItem, CotaRadialItem  # noqa: E402


class _Recorder(QPainter):
    """A real painter that also keeps every line it is asked to draw."""

    def __init__(self, device):
        super().__init__(device)
        self.lines = []

    def drawLine(self, *args):
        if len(args) == 2:
            a, b = args
            self.lines.append((a.x(), a.y(), b.x(), b.y()))
        else:
            self.lines.append(tuple(float(v) for v in args[:4]))
        super().drawLine(*args)


def _ticks(lines, length):
    """The lines of the given length: the ticks, not the dimension line."""
    return [ln for ln in lines
            if math.hypot(ln[2] - ln[0], ln[3] - ln[1]) == pytest.approx(
                length, abs=0.01)]


def _is_slash(line):
    """«/» on screen (y down): rising to the right, at 45°."""
    x0, y0, x1, y1 = line
    dx, dy = x1 - x0, y1 - y0
    return abs(abs(dx) - abs(dy)) < 1e-6 and dx * dy < 0


def _paint(fn, item):
    img = QImage(400, 400, QImage.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    p = _Recorder(img)
    p.translate(200, 200)
    fn(p, item)
    p.end()
    return p.lines


def test_tick_angle_is_45_degrees_counter_clockwise_on_the_sheet():
    from views.composer import oblique_tick_angle
    k = oblique_tick_angle(0.0)                       # horizontal line
    assert (math.cos(k), math.sin(k)) == pytest.approx(
        (math.sqrt(0.5), -math.sqrt(0.5)))           # up and right: «/»
    # A reversed line ends in the very same tick.
    r = oblique_tick_angle(math.pi)
    assert math.sin(r - k) == pytest.approx(0.0, abs=1e-12)
    # A vertical one: the «/» turned with the line, «\» on screen.
    v = oblique_tick_angle(math.pi / 2)
    assert math.cos(v) * math.sin(v) > 0


def test_horizontal_sheet_cota_ends_in_slashes():
    from views.composer import paint_cota_mm
    ct = CotaItem(x_mm=0, y_mm=0, dx_mm=40, dy_mm=0, ends="tick",
                  text_bg="")
    ticks = _ticks(_paint(paint_cota_mm, ct), 3.2)
    assert len(ticks) == 2 and all(_is_slash(t) for t in ticks)


def test_vertical_sheet_cota_turns_its_ticks_with_the_line():
    from views.composer import paint_cota_mm
    ct = CotaItem(x_mm=0, y_mm=0, dx_mm=0, dy_mm=40, ends="tick",
                  text_bg="")
    ticks = _ticks(_paint(paint_cota_mm, ct), 3.2)
    assert len(ticks) == 2 and not any(_is_slash(t) for t in ticks)


def test_horizontal_radial_cota_ends_in_a_slash():
    from views.composer import paint_cota_radial_mm
    cr = CotaRadialItem(radius_mm=20, angle_deg=0.0, ends="tick",
                        kind="diameter", centre_mark=False)
    ticks = _ticks(_paint(paint_cota_radial_mm, cr), 3.2)
    assert len(ticks) == 2 and all(_is_slash(t) for t in ticks)


def test_angular_cota_tick_at_the_top_of_its_arc_is_a_slash():
    from views.composer import paint_cota_angular_mm
    # rays to the right and straight up: the arc's end at the top runs
    # horizontally there
    ca = CotaAngularItem(ax_mm=30, ay_mm=0, bx_mm=0, by_mm=-30,
                         radius_mm=18, ends="tick")
    ticks = _ticks(_paint(paint_cota_angular_mm, ca), 3.2)
    top = [t for t in ticks if (t[1] + t[3]) / 2 < -17]
    assert len(top) == 1 and _is_slash(top[0])


def test_frame_annotations_draw_the_model_ticks_as_slashes(monkeypatch):
    from core.dimension import Dimension
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    win = MainWindow()
    comp = ComposerWindow(win)
    try:
        scene = win.viewport.scene
        scene.mesh.add_face([QVector3D(-2, 0, 0), QVector3D(2, 0, 0),
                             QVector3D(2, 0, 3), QVector3D(-2, 0, 3)])
        scene.dimensions.append(Dimension(QVector3D(-2, 0, 0),
                                          QVector3D(2, 0, 0),
                                          QVector3D(0, 0, -0.5)))
        scene.dimension_style["ends"] = "tick"
        scene.version += 1
        frame = comp.comp.frames[0]
        frame.view_key, frame.style = "std:front", "vectorial"
        frame.w_mm, frame.h_mm, frame.scale_n = 200.0, 100.0, 50.0
        frame.annotations = True
        lines = [a[1:5] for a in comp.compute_annotations(frame)
                 if a[0] == "line"]
        ticks = _ticks(lines, 3.2)
        assert len(ticks) == 2 and all(_is_slash(t) for t in ticks)
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_3d_view_draws_oblique_ticks_not_square_ones(monkeypatch):
    from core.dimension import Dimension
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        scene = vp.scene
        dim = Dimension(QVector3D(0, 0, 0), QVector3D(10, 0, 0),
                        QVector3D(0, 0, 0))
        scene.dimensions.append(dim)
        scene.dimension_style["ends"] = "tick"

        def to_px(p):
            return (100.0, 200.0) if p.x() < 5 else (300.0, 200.0)

        monkeypatch.setattr(vp, "_world_to_pixel", to_px)
        monkeypatch.setattr(vp, "_occluded_on_screen", lambda w: False)
        monkeypatch.setattr(vp, "_draw_occluded_segment", lambda *a: None)
        img = QImage(400, 400, QImage.Format_ARGB32)
        img.fill(0xFFFFFFFF)
        p = _Recorder(img)
        vp._draw_dimensions(p)
        p.end()
        ticks = _ticks(p.lines, 8.0)
        assert len(ticks) == 2 and all(_is_slash(t) for t in ticks)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
