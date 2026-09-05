# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Chain dimensions (sheets plan 2026-09-05, point 3): points in a row on
one dimension line, the total stacked above when the chain ends, and the
sheet's default cota style remembered across sessions."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, QSettings
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QWidget

from tests.test_composer_canvas import _FakeViewport
from views.composer import ComposerWindow

_app = QApplication.instance() or QApplication([])
V = QVector3D


def _composer():
    host = QWidget()
    host.viewport = _FakeViewport()
    host.viewport.scene.mesh.add_face(
        [V(0, 0, 0), V(6, 0, 0), V(6, 0, 3), V(0, 0, 3)])
    composer = ComposerWindow(host)
    composer.comp.frames[0].view_key = "std:front"
    composer.comp.frames[0].scale_n = 100.0
    composer.snap_cache.clear()
    return composer, host


def test_a_chain_places_segments_on_one_line_and_stacks_the_total():
    composer, _host = _composer()
    view = composer._view
    composer._set_tool_mode("cota_cadena")
    P = [QPointF(20, 50), QPointF(50, 50), QPointF(90, 50), QPointF(110, 50)]
    view._chain_click(P[0], None)
    view._chain_click(P[1], None)
    assert composer.comp.cotas == []               # nothing until the offset
    view._chain_click(QPointF(35, 40), None)        # the line 10 mm above
    assert len(composer.comp.cotas) == 1
    first = composer.comp.cotas[0]
    assert (first.x_mm, first.y_mm, first.dx_mm) == (20, 50, 30)
    assert first.sep_mm == pytest.approx(-10.0)      # above = negative normal
    view._chain_click(P[2], None)
    view._chain_click(P[3], None)
    assert len(composer.comp.cotas) == 3
    for ct in composer.comp.cotas:
        assert ct.sep_mm == pytest.approx(-10.0)     # all on the same line
    assert composer.tool_mode == "cota_cadena"       # still armed
    # clicking the last point again ends the chain: the total is stacked
    view._chain_click(P[3], None)
    assert len(composer.comp.cotas) == 4
    total = composer.comp.cotas[-1]
    assert (total.x_mm, total.dx_mm) == (20, 90)
    assert total.sep_mm < -10.0 - 5.0                # one row further out
    assert total.real_distance_m() == pytest.approx(9.0)
    assert view._chain_pts == [] and view._chain_cotas == []
    # undo pops only the total
    composer._on_undo()
    assert len(composer.comp.cotas) == 3


def test_a_jog_keeps_the_next_segment_on_the_chain_line():
    composer, _host = _composer()
    view = composer._view
    composer._set_tool_mode("cota_cadena")
    view._chain_click(QPointF(20, 50), None)
    view._chain_click(QPointF(50, 50), None)
    view._chain_click(QPointF(30, 42), None)          # line 8 mm above
    # the next point sits 3 mm LOWER on the page: the segment tilts, but
    # its dimension line must still pass through the chain line at (50, 42)
    view._chain_click(QPointF(80, 53), None)
    ct = composer.comp.cotas[-1]
    nx, ny = ct.normal()
    line_y_at_start = ct.y_mm + ny * ct.sep_mm
    line_x_at_start = ct.x_mm + nx * ct.sep_mm
    assert (line_x_at_start, line_y_at_start) != (50, 50)
    # the foot of the new line at its first point lies on y = 42
    assert line_y_at_start == pytest.approx(42.0, abs=0.6)
    # a perpendicular jog cannot meet the line: it keeps the chain sep
    view._chain_click(QPointF(80, 20), None)
    assert composer.comp.cotas[-1].sep_mm == pytest.approx(-8.0, abs=0.5)


def test_esc_and_tool_switch_finish_the_chain_and_a_short_chain_has_no_total():
    composer, _host = _composer()
    view = composer._view
    composer._set_tool_mode("cota_cadena")
    view._chain_click(QPointF(20, 50), None)
    view._chain_click(QPointF(50, 50), None)
    view._chain_click(QPointF(35, 44), None)
    assert len(composer.comp.cotas) == 1
    view.cancel_placement()                           # Esc
    assert len(composer.comp.cotas) == 1              # one segment: no total
    assert view._chain_pts == []
    view._chain_click(QPointF(60, 80), None)
    view._chain_click(QPointF(90, 80), None)
    view._chain_click(QPointF(70, 74), None)
    view._chain_click(QPointF(120, 80), None)
    composer._set_tool_mode("select")                 # switching tools ends it
    assert len(composer.comp.cotas) == 1 + 2 + 1      # two segments + total


def test_anchored_chain_points_anchor_each_segment():
    composer, _host = _composer()
    frame = composer.comp.frames[0]
    view = composer._view
    pts, wpts = composer.frame_snap_points(frame)
    # the façade's bottom corners and the bottom midpoint, left to right
    bottom: dict = {}                    # one hit per distinct x (corners repeat)
    for k in range(len(wpts)):
        if abs(wpts[k][2]) < 1e-9:
            bottom.setdefault(round(float(wpts[k][0]), 6), k)
    hits = [composer.nearest_snap_point(float(pts[k][0]), float(pts[k][1]), 0.5)
            for _x, k in sorted(bottom.items())]
    assert len(hits) >= 3 and all(h is not None for h in hits)
    composer._set_tool_mode("cota_cadena")
    for h in hits[:2]:
        view._chain_click(QPointF(h[0], h[1]), h)
    view._chain_click(QPointF(hits[0][0], hits[0][1] + 8.0), None)
    view._chain_click(QPointF(hits[2][0], hits[2][1]), hits[2])
    view.finish_chain()
    cotas = composer.comp.cotas
    assert len(cotas) == 3 and all(c.anchored for c in cotas)
    assert cotas[-1].real_distance_m() == pytest.approx(6.0)     # the total
    assert cotas[0].real_distance_m() + cotas[1].real_distance_m() == \
        pytest.approx(6.0)


def test_the_default_cota_style_survives_a_new_composer():
    composer, host = _composer()
    from core.composition import CotaItem
    sample = CotaItem(text_mm=3.6, ends="arrow", color="#aa0000", units="cm")
    composer._remember_cota_style(sample)
    saved = json.loads(str(QSettings().value("composer/default_cota_style")))
    assert saved["ends"] == "arrow" and saved["units"] == "cm"
    again = ComposerWindow(host)
    assert again._last_cota_style["text_mm"] == 3.6
    assert again._last_cota_style["color"] == "#aa0000"
    ct = again._new_cota((0, 0), (30, 0), 5.0)
    assert (ct.text_mm, ct.ends, ct.units) == (3.6, "arrow", "cm")
    # clean up the shared settings for the other tests
    QSettings().remove("composer/default_cota_style")
