# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The composer's angular dimension (LayOut's Angular Dimension tool)."""
from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QPainter

from core.composition import (AddItemCommand, Composicion, CotaAngularItem,
                              RemoveItemCommand)


def test_angle_is_the_short_way_round_and_labels_follow_decimals():
    ca = CotaAngularItem(ax_mm=30, ay_mm=0, bx_mm=0, by_mm=-30)   # right, up
    a0, sweep = ca.angles()
    assert a0 == pytest.approx(0.0)
    assert sweep == pytest.approx(-math.pi / 2)        # counter-clockwise on screen
    assert ca.angle_deg() == pytest.approx(90.0)
    assert ca.label() == "90.0°"
    ca.decimals = 0
    assert ca.label() == "90°"
    ca.text = "α = <>"
    assert ca.label() == "α = 90°"
    # 350° apart the short way is 10°, whichever ray comes first.
    wide = CotaAngularItem(ax_mm=30, ay_mm=0,
                           bx_mm=30 * math.cos(math.radians(350)),
                           by_mm=30 * math.sin(math.radians(350)))
    assert wide.angle_deg() == pytest.approx(10.0)


def test_angular_cota_lives_in_the_composition_and_round_trips():
    c = Composicion()
    ca = CotaAngularItem(x_mm=50, y_mm=60, radius_mm=12.5, text="<> aprox.")
    AddItemCommand(c, ca).do()
    assert c.cotas_ang == [ca] and ca in c.all_items()
    back = Composicion.from_dict(c.to_dict())
    assert len(back.cotas_ang) == 1
    assert (back.cotas_ang[0].radius_mm, back.cotas_ang[0].text) == (12.5, "<> aprox.")
    RemoveItemCommand(c, ca).do()
    assert c.cotas_ang == []


def test_angular_cota_paints_in_every_end_style():
    from views.composer import paint_cota_angular_mm
    for ends in ("arrow", "tick", "none"):
        ca = CotaAngularItem(ax_mm=40, ay_mm=10, bx_mm=-5, by_mm=-35,
                             radius_mm=18, ends=ends, text_color="#aa0000")
        img = QImage(200, 200, QImage.Format_ARGB32)
        img.fill(0xFFFFFFFF)
        p = QPainter(img)
        p.translate(100, 100)
        paint_cota_angular_mm(p, ca)
        p.end()
        # something was drawn near the arc's middle
        a0, sweep = ca.angles()
        am = a0 + sweep / 2
        x = int(100 + 18 * math.cos(am))
        y = int(100 + 18 * math.sin(am))
        window = [img.pixel(x + dx, y + dy) & 0xFFFFFF
                  for dx in range(-3, 4) for dy in range(-3, 4)]
        assert any(px != 0xFFFFFF for px in window)


def _press(view, x, y, button=Qt.LeftButton):
    pos = QPointF(x, y)
    view.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, pos, pos,
                                     button, button, Qt.NoModifier))
    view.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, pos, pos,
                                       button, Qt.NoButton, Qt.NoModifier))


def test_four_clicks_place_an_angular_cota_and_escape_cancels(monkeypatch):
    from views.composer import ComposerWindow, CotaAngularCanvasItem
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    try:
        view = comp._view
        view.resetTransform()                       # 1 px = 1 mm
        view.horizontalScrollBar().setValue(0)
        view.verticalScrollBar().setValue(0)

        def scene_xy(x_mm, y_mm):
            p = view.mapFromScene(QPointF(x_mm, y_mm))
            return p.x(), p.y()

        comp._set_tool_mode("cota_ang")
        _press(view, *scene_xy(100.0, 100.0))      # vertex
        _press(view, *scene_xy(140.0, 100.0))      # ray A: right
        assert len(view._ang_pts) == 2
        _press(view, *scene_xy(100.0, 60.0))       # ray B: up on the page
        assert len(view._ang_pts) == 3 and view._preview is not None
        _press(view, *scene_xy(100.0, 80.0))       # arc radius = 20 mm
        assert len(comp.comp.cotas_ang) == 1
        ca = comp.comp.cotas_ang[0]
        assert (ca.x_mm, ca.y_mm) == (100.0, 100.0)
        assert (ca.ax_mm, ca.ay_mm) == (40.0, 0.0)
        assert (ca.bx_mm, ca.by_mm) == (0.0, -40.0)
        assert ca.radius_mm == pytest.approx(20.0)
        assert ca.label() == "90.0°"
        assert comp.tool_mode == "select" and view._ang_pts == []
        comp._rebuild_canvas()
        assert any(isinstance(it, CotaAngularCanvasItem)
                   for it in comp.canvas.items())
        assert "90.0°" in comp._item_label(ca)
        assert comp._style_fields_for(ca)[0] is CotaAngularItem

        # Esc halfway through drops the placement.
        comp._set_tool_mode("cota_ang")
        _press(view, *scene_xy(30.0, 30.0))
        _press(view, *scene_xy(60.0, 30.0))
        view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape,
                                     Qt.NoModifier))
        assert view._ang_pts == [] and view._preview is None
        assert len(comp.comp.cotas_ang) == 1
        comp.history.undo()
        assert comp.comp.cotas_ang == []
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
