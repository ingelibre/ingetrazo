# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Section marks in model views (sheets plan 2026-09-05, point 7a): the
trace of each section plane that cuts across a frame's view, with the
arrows toward the side the section looks at and its letter in bubbles."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage, QPainter, QVector3D
from PySide6.QtWidgets import QApplication, QWidget

from core.composition import MarcoVista
from core.section import SectionPlane
from tests.test_composer_canvas import _FakeViewport
from views.composer import ComposerWindow, FrameItem, _paint_annots_mm

_app = QApplication.instance() or QApplication([])
V = QVector3D


def _box(m, x0, y0, z0, x1, y1, z1):
    m.add_face([V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0)])
    m.add_face([V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)])
    m.add_face([V(x0, y0, z0), V(x1, y0, z0), V(x1, y0, z1), V(x0, y0, z1)])
    m.add_face([V(x0, y1, z0), V(x1, y1, z0), V(x1, y1, z1), V(x0, y1, z1)])
    m.add_face([V(x0, y0, z0), V(x0, y1, z0), V(x0, y1, z1), V(x0, y0, z1)])
    m.add_face([V(x1, y0, z0), V(x1, y1, z0), V(x1, y1, z1), V(x1, y0, z1)])


def _composer(planes):
    host = QWidget()
    host.viewport = _FakeViewport()
    sc = host.viewport.scene
    _box(sc.mesh, 0, 0, 0, 8, 4, 3)
    for sp in planes:
        sc.section_planes.append(sp)
    composer = ComposerWindow(host)
    frame = composer.comp.frames[0]
    frame.x_mm, frame.y_mm, frame.w_mm, frame.h_mm = 10.0, 10.0, 200.0, 100.0
    frame.scale_n = 100.0                    # 10 mm of paper per metre
    return composer, frame, host


def _marks(annots):
    return [a for a in annots if a[0] == "secmark"]


def test_a_cross_section_plane_leaves_its_trace_on_the_plan():
    # a vertical plane across the box at y = 1.5 looking north (+Y)
    sp = SectionPlane(V(4, 1.5, 1), V(0, -1, 0), name="Corte 1")
    composer, frame, _host = _composer([sp])
    frame.view_key = "std:top"
    assert _marks(composer.compute_annotations(frame)) == []   # opt-in
    frame.section_marks = True
    marks = _marks(composer.compute_annotations(frame))
    assert len(marks) == 1
    _k, x0, y0, x1, y1, ax, ay, label, size = marks[0]
    assert label == "A" and size == pytest.approx(2.8)
    assert y0 == pytest.approx(y1, abs=1e-6)              # runs along X
    # the box is 8 m = 80 mm wide: the line spans it plus a margin each side
    assert abs(x1 - x0) == pytest.approx(80.0 + 12.0, abs=0.5)
    # the section looks toward +Y = UP the sheet (paper y grows down)
    assert ax == pytest.approx(0.0, abs=1e-6) and ay == pytest.approx(-1.0)
    # the plane's own letter wins
    sp.symbol = "B"
    composer.annot_cache.clear()
    assert _marks(composer.compute_annotations(frame))[0][7] == "B"


def test_a_plane_face_on_to_the_view_has_no_trace_and_a_flipped_one_points_back():
    front = SectionPlane(V(4, 1.5, 1), V(0, -1, 0))     # parallel to a front view
    side = SectionPlane(V(3, 2, 1), V(1, 0, 0))         # across the front view
    composer, frame, _host = _composer([front, side])
    frame.view_key, frame.section_marks = "std:front", True
    marks = _marks(composer.compute_annotations(frame))
    assert len(marks) == 1 and marks[0][7] == "B"        # the second plane
    _k, x0, y0, x1, y1, ax, ay, _l, _s = marks[0]
    assert x0 == pytest.approx(x1, abs=1e-6)              # vertical trace
    assert abs(y1 - y0) == pytest.approx(30.0 + 12.0, abs=0.5)   # 3 m tall
    assert ax == pytest.approx(-1.0) and ay == pytest.approx(0.0, abs=1e-6)
    side.flip()
    composer.annot_cache.clear()
    assert _marks(composer.compute_annotations(frame))[0][5] == pytest.approx(1.0)


def test_the_mark_is_painted_with_bubbles_at_both_ends():
    frame = MarcoVista(w_mm=120.0, h_mm=60.0)
    k = 4
    img = QImage(int(frame.w_mm * k), int(frame.h_mm * k), QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.scale(k, k)
    _paint_annots_mm(p, frame, [("secmark", 20.0, 30.0, 100.0, 30.0,
                                  0.0, -1.0, "A", 2.8)])
    p.end()

    def dark(x0, y0, x1, y1):
        return sum(1 for x in range(int(x0 * k), int(x1 * k))
                   for y in range(int(y0 * k), int(y1 * k))
                   if img.pixelColor(x, y).lightness() < 140)
    assert dark(40, 29, 80, 31) > 0                      # the line
    assert dark(14, 18, 26, 30) > 20                     # bubble + arrow, left end
    assert dark(94, 18, 106, 30) > 20                    # …and right end
    assert dark(40, 32, 80, 60) == 0                     # nothing below the line


def test_toggling_the_marks_redoes_only_the_overlay():
    sp = SectionPlane(V(4, 1.5, 1), V(0, -1, 0))
    composer, frame, _host = _composer([sp])
    frame.view_key, frame.style = "std:top", "vectorial"
    composer.render_frame(frame)
    lines = composer.hlr_cache[id(frame)]
    item = next(it for it in composer.canvas.items()
                if getattr(it, "model", None) is frame)
    assert isinstance(item, FrameItem)
    item.setSelected(True)
    composer.on_selection_changed()
    composer.secmark_check.setChecked(True)
    assert frame.section_marks is True
    assert composer.hlr_cache.get(id(frame)) is lines     # drawing kept
    assert len(_marks(composer.annot_cache[id(frame)])) == 1
