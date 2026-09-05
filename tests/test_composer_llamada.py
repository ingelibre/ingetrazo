# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Detail callouts (sheets plan 2026-09-05, point 7b): a dashed box around
a part of a view, a leader and the «3 / L-05» bubble; bound to the frame
it was drawn on so it moves along."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage, QPainter, QVector3D
from PySide6.QtWidgets import QApplication, QWidget

from core.composition import Cajetin, Composicion, LlamadaItem
from tests.test_composer_canvas import _FakeViewport
from views.composer import (ComposerWindow, LlamadaCanvasItem,
                            llamada_bounds_mm, paint_llamada_mm)

_app = QApplication.instance() or QApplication([])
V = QVector3D


def _composer():
    host = QWidget()
    host.viewport = _FakeViewport()
    host.viewport.scene.mesh.add_face(
        [V(0, 0, 0), V(6, 0, 0), V(6, 0, 3), V(0, 0, 3)])
    composer = ComposerWindow(host)
    composer.comp.cajetin = Cajetin()
    composer.comp.cajetin.lamina = "L-01"
    composer._set_field_context(composer.comp)
    return composer, host


def test_the_tool_boxes_the_detail_and_binds_it_to_the_frame_under_it():
    composer, _host = _composer()
    frame = composer.comp.frames[0]
    frame.x_mm, frame.y_mm, frame.w_mm, frame.h_mm = 20, 20, 150, 100
    composer.tool_mode = "llamada"
    composer.place_tool(50, 40, 80, 60)             # a drag inside the frame
    assert len(composer.comp.llamadas) == 1
    ll = composer.comp.llamadas[0]
    assert (ll.x_mm, ll.y_mm, ll.w_mm, ll.h_mm) == (50, 40, 30, 20)
    assert ll.number == "1" and ll.sheet == "{lamina}"
    assert ll.frame_uid == frame.uid and frame.uid
    assert ll.bx_mm > ll.w_mm and ll.by_mm < 0       # bubble outside, top-right
    # a second one, drawn off any frame, is free
    composer.tool_mode = "llamada"
    composer.place_tool(200, 200, 210, 210)
    free = composer.comp.llamadas[1]
    assert free.number == "2" and free.frame_uid == ""
    assert composer._item_label(ll) == "Detail callout 1/{lamina}"


def test_a_bound_callout_moves_with_its_frame():
    composer, _host = _composer()
    frame = composer.comp.frames[0]
    frame.x_mm, frame.y_mm, frame.w_mm, frame.h_mm = 20, 20, 150, 100
    composer.tool_mode = "llamada"
    composer.place_tool(50, 40, 80, 60)
    ll = composer.comp.llamadas[0]
    before = {"x_mm": frame.x_mm, "y_mm": frame.y_mm}
    frame.x_mm += 12.0
    frame.y_mm += 5.0
    composer.push_geometry_edit(frame, {"x_mm": frame.x_mm, "y_mm": frame.y_mm},
                                before)
    assert (ll.x_mm, ll.y_mm) == pytest.approx((62.0, 45.0))
    composer._on_undo()
    assert (ll.x_mm, ll.y_mm) == pytest.approx((50.0, 40.0))
    assert (frame.x_mm, frame.y_mm) == (20, 20)
    ll.follow = False
    frame_before = {"x_mm": frame.x_mm, "y_mm": frame.y_mm}
    frame.x_mm += 3.0
    composer.push_geometry_edit(frame, {"x_mm": frame.x_mm, "y_mm": frame.y_mm},
                                frame_before)
    assert ll.x_mm == pytest.approx(50.0)            # stays put


def _paint(ll, k=4):
    r = llamada_bounds_mm(ll)
    img = QImage(int((r.width() + 4) * k), int((r.height() + 4) * k),
                 QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.scale(k, k)
    p.translate(-r.left() + 2, -r.top() + 2)
    paint_llamada_mm(p, ll)
    p.end()
    return img, (-r.left() + 2) * k, (-r.top() + 2) * k, k


def _dark(img, x0, y0, x1, y1):
    return sum(1 for x in range(max(0, int(x0)), min(img.width(), int(x1)))
               for y in range(max(0, int(y0)), min(img.height(), int(y1)))
               if img.pixelColor(x, y).lightness() < 140)


def test_painting_draws_the_dashed_box_the_leader_and_the_bubble():
    ll = LlamadaItem(w_mm=40, h_mm=30, bx_mm=56, by_mm=-8, number="3",
                     sheet="L-05")
    img, ox, oy, k = _paint(ll)
    # the box edge is dashed: ink AND gaps along the top edge
    top = [img.pixelColor(int(ox + x * k), int(oy)).lightness() < 140
           for x in range(2, 38)]
    assert any(top) and not all(top)
    # the bubble, up-right of the box
    assert _dark(img, ox + 50 * k, oy - 14 * k, ox + 62 * k, oy - 2 * k) > 30
    # the leader crosses the space between the box corner and the bubble
    assert _dark(img, ox + 41 * k, oy - 6 * k, ox + 49 * k, oy + 1 * k) > 0
    # inside the box: white
    assert _dark(img, ox + 6 * k, oy + 6 * k, ox + 34 * k, oy + 24 * k) == 0
    ll.shape = "circle"
    img, ox, oy, k = _paint(ll)
    assert _dark(img, ox + 1 * k, oy + 1 * k, ox + 5 * k, oy + 4 * k) == 0  # corner empty
    ll.bx_mm, ll.by_mm = 20, 15                        # bubble inside: no leader
    from views.composer import _llamada_leader
    assert _llamada_leader(ll) is None


def test_callouts_roundtrip_and_the_panel_edits_them():
    c = Composicion()
    c.llamadas.append(LlamadaItem(x_mm=10, y_mm=10, shape="circle", number="7",
                                  sheet="L-09", frame_uid="abc", follow=False))
    back = Composicion.from_dict(c.to_dict()).llamadas[0]
    assert (back.shape, back.number, back.sheet, back.frame_uid, back.follow) == (
        "circle", "7", "L-09", "abc", False)
    composer, _host = _composer()
    composer.comp.llamadas.append(LlamadaItem(x_mm=30, y_mm=30))
    composer._rebuild_canvas()
    item = next(it for it in composer.canvas.items()
                if isinstance(it, LlamadaCanvasItem))
    item.setSelected(True)
    composer.on_selection_changed()
    assert composer.props.currentIndex() == 14
    assert not composer.ll_follow.isEnabled()          # free: nothing to follow
    composer.ll_number.setText("4")
    composer.ll_sheet.setText("L-02")
    composer.ll_shape.setCurrentIndex(composer.ll_shape.findData("circle"))
    m = item.model
    assert (m.number, m.sheet, m.shape) == ("4", "L-02", "circle")
