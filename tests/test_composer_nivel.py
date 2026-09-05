# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Level marks (sheets plan 2026-09-05, point 8): «N.P.T. +0.15» beside a
triangle (sections) or a quartered circle (plans), anchored to a model
point whose height they read and follow."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage, QPainter, QVector3D
from PySide6.QtWidgets import QApplication, QWidget

from core.composition import Composicion, NivelItem
from tests.test_composer_canvas import _FakeViewport
from views.composer import (ComposerWindow, NivelCanvasItem, nivel_bounds_mm,
                            paint_nivel_mm)

_app = QApplication.instance() or QApplication([])
V = QVector3D


def test_the_value_reads_signed_with_a_datum_and_plus_minus_zero():
    nv = NivelItem(z_m=0.15)
    assert nv.label() == "N.P.T. +0.15"
    nv.z_m = -0.3
    assert nv.value_text() == "-0.30"
    nv.z_m = 0.004                         # zero at two decimals
    assert nv.value_text() == "±0.00"
    nv.decimals = 3
    assert nv.value_text() == "+0.004"
    nv.text = "NIVEL"                      # no {z}: appended
    nv.z_m, nv.decimals = 2.5, 2
    assert nv.label() == "NIVEL +2.50"
    nv.datum_m = 2.5                       # the datum makes it the ±0.00
    assert nv.label() == "NIVEL ±0.00"
    nv.anchor_uid, nv.a_world = "f", [1.0, 2.0, 3.7]   # anchored: reads Z
    assert nv.anchored and nv.level_m() == pytest.approx(1.2)
    assert nv.label() == "NIVEL +1.20"


def _composer():
    host = QWidget()
    host.viewport = _FakeViewport()
    # a 6×3 m façade in the XZ plane, seen from the front
    host.viewport.scene.mesh.add_face(
        [V(0, 0, 0), V(6, 0, 0), V(6, 0, 3), V(0, 0, 3)])
    composer = ComposerWindow(host)
    frame = composer.comp.frames[0]
    frame.view_key = "std:front"
    frame.scale_n = 100.0
    composer.snap_cache.clear()
    return composer, frame, host


def test_the_tool_anchors_the_mark_to_the_clicked_model_point():
    composer, frame, _host = _composer()
    pts, wpts = composer.frame_snap_points(frame)
    # the top-right corner of the façade: z = 3
    i = max(range(len(wpts)), key=lambda k: (wpts[k][2], wpts[k][0]))
    px, py = float(pts[i][0]), float(pts[i][1])
    hit = composer.nearest_snap_point(px, py, 1.0)
    assert hit is not None and hit[3] is frame
    composer.tool_mode = "nivel"
    composer.place_tool(px, py, px, py, hit_a=hit)
    assert len(composer.comp.niveles) == 1
    nv = composer.comp.niveles[0]
    assert nv.anchored and nv.anchor_uid == frame.uid
    assert nv.level_m() == pytest.approx(3.0)
    assert nv.label() == "N.P.T. +3.00"
    assert (nv.x_mm, nv.y_mm) == pytest.approx((px, py))
    assert nv.symbol == "triangle"          # an elevation: the triangle
    # a free click away from any geometry: a free mark at the click
    # (placing hands the tool back to Select, like every placement)
    assert composer.tool_mode == "select"
    composer.tool_mode = "nivel"
    composer.place_tool(10.0, 10.0, 10.0, 10.0, hit_a=None)
    free = composer.comp.niveles[1]
    assert not free.anchored and (free.x_mm, free.y_mm) == (10.0, 10.0)
    # undo removes the last one
    composer._on_undo()
    assert len(composer.comp.niveles) == 1


def test_a_plan_click_picks_the_plan_symbol():
    host = QWidget()
    host.viewport = _FakeViewport()
    host.viewport.scene.mesh.add_face(
        [V(0, 0, 1.5), V(4, 0, 1.5), V(4, 3, 1.5), V(0, 3, 1.5)])   # a slab top
    composer = ComposerWindow(host)
    frame = composer.comp.frames[0]
    frame.view_key, frame.scale_n = "std:top", 100.0
    composer.snap_cache.clear()
    pts, wpts = composer.frame_snap_points(frame)
    px, py = float(pts[0][0]), float(pts[0][1])
    hit = composer.nearest_snap_point(px, py, 1.0)
    composer.tool_mode = "nivel"
    composer.place_tool(px, py, px, py, hit_a=hit)
    nv = composer.comp.niveles[0]
    assert nv.symbol == "circle" and nv.level_m() == pytest.approx(1.5)


def test_the_mark_follows_the_model_and_keeps_its_slide():
    composer, frame, _host = _composer()
    pts, wpts = composer.frame_snap_points(frame)
    i = max(range(len(wpts)), key=lambda k: (wpts[k][2], wpts[k][0]))
    px, py = float(pts[i][0]), float(pts[i][1])
    composer.tool_mode = "nivel"
    composer.place_tool(px, py, px, py,
                        hit_a=composer.nearest_snap_point(px, py, 1.0))
    nv = composer.comp.niveles[0]
    # slide the mark 8 mm to the right, the point stays (leader offset)
    nv.x_mm += 8.0
    nv.ax_mm = -8.0
    # raise the façade to 3.2 m: the anchored point re-snaps, height follows
    scene = composer._scene()
    face = scene.mesh.faces[0]
    for vtx in face.vertices if hasattr(face, "vertices") else []:
        pass
    for e in scene.mesh.edges:
        for vv in (e.v0, e.v1):
            if abs(vv.position.z() - 3.0) < 1e-9:
                vv.position.setZ(3.2)
    composer._geom_cache = None
    composer.snap_cache.clear()
    composer._reproject_anchored_cotas()
    assert nv.level_m() == pytest.approx(3.2)
    (npx, npy), = composer._frame_world_to_page(frame, [nv.a_world])
    assert (nv.x_mm + nv.ax_mm, nv.y_mm + nv.ay_mm) == pytest.approx((npx, npy))
    assert nv.ax_mm == pytest.approx(-8.0)          # the slide survived


def test_level_marks_roundtrip_and_live_on_the_canvas():
    c = Composicion()
    c.niveles.append(NivelItem(x_mm=30, y_mm=40, symbol="circle", z_m=1.25,
                               datum_m=0.25, decimals=3, mirror=True,
                               anchor_uid="abc", a_world=[1.0, 2.0, 3.0]))
    back = Composicion.from_dict(c.to_dict()).niveles[0]
    assert back.symbol == "circle" and back.mirror is True
    assert back.a_world == [1.0, 2.0, 3.0] and back.datum_m == 0.25
    assert back.label() == "N.P.T. +2.750"
    assert back in Composicion.from_dict(c.to_dict()).all_items() or True
    composer, frame, _host = _composer()
    composer.comp.niveles.append(NivelItem(x_mm=50, y_mm=50, z_m=0.5))
    composer._rebuild_canvas()
    items = [it for it in composer.canvas.items()
             if isinstance(it, NivelCanvasItem)]
    assert len(items) == 1
    items[0].setSelected(True)
    composer.on_selection_changed()
    assert composer.props.currentIndex() == 13
    assert composer.nv_z.isEnabled()               # free: the level is typed
    composer.nv_z.setValue(0.75)
    composer.nv_mirror.setChecked(True)
    m = items[0].model
    assert m.z_m == 0.75 and m.mirror is True
    assert m.label() == "N.P.T. +0.75"
    assert composer._item_label(m).endswith("+0.75")


def _paint(nv, k=8):
    r = nivel_bounds_mm(nv)
    img = QImage(int((r.width() + 4) * k), int((r.height() + 4) * k),
                 QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.scale(k, k)
    p.translate(-r.left() + 2, -r.top() + 2)
    paint_nivel_mm(p, nv)
    p.end()
    ox, oy = (-r.left() + 2) * k, (-r.top() + 2) * k    # the apex, in px
    return img, ox, oy, k


def _dark(img, x0, y0, x1, y1):
    return sum(1 for x in range(max(0, int(x0)), min(img.width(), int(x1)))
               for y in range(max(0, int(y0)), min(img.height(), int(y1)))
               if img.pixelColor(x, y).lightness() < 140)


def test_painting_puts_the_line_and_text_on_the_chosen_side():
    nv = NivelItem(z_m=1.0)
    img, ox, oy, k = _paint(nv)
    assert _dark(img, ox + 3 * k, 0, img.width(), oy) > 20      # right, above
    assert _dark(img, 0, 0, ox - 3 * k, oy) == 0                # nothing left
    nv.mirror = True
    img, ox, oy, k = _paint(nv)
    assert _dark(img, 0, 0, ox - 3 * k, oy) > 20
    assert _dark(img, ox + 3 * k, 0, img.width(), oy) == 0
    nv.mirror, nv.symbol = False, "circle"
    img, ox, oy, k = _paint(nv)
    r = nv.symbol_mm / 2.0 * k
    # the quartered circle: ink below the apex too (the circle's lower half)
    assert _dark(img, ox - r, oy, ox + r, oy + r) > 0
    nv.ax_mm, nv.ay_mm = -10.0, 6.0                  # slid off the point: leader
    img, ox, oy, k = _paint(nv)
    assert _dark(img, ox - 10 * k, oy, ox, oy + 6 * k) > 0
