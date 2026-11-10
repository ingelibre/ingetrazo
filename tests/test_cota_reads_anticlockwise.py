# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Regla 2 de la normativa de acotación (Rafael, «Rafa 3D», 09:00–10:00).

Dimension text is read from the bottom and from the right of the sheet —
you tilt your head to the LEFT, never to the right. It is the rule he
repeats most, and it is circular: it holds at every inclination.

The rule was written out at five call sites in two contradictory
spellings. Three tested ``deg > 90 or deg < -90`` and so let the exact
+90° of a cota drawn DOWNWARD through; two tested ``deg <= -90`` and so
turned every vertical the wrong way round — and that second pair is what
projects the MODEL's dimensions onto a sheet, which is where Rafael saw it.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage, QPainter, QVector3D

from core.composition import CotaItem, readable_deg


# ---- the rule itself ------------------------------------------------------

@pytest.mark.parametrize("dx,dy,want", [
    (10.0, 0.0, 0.0),        # horizontal, left to right
    (-10.0, 0.0, 0.0),       # …drawn right to left: same text
    (0.0, 10.0, -90.0),      # vertical drawn DOWN the page ← the one that leaked
    (0.0, -10.0, -90.0),     # vertical drawn UP the page
    (10.0, 10.0, 45.0),      # down to the right
    (-10.0, -10.0, 45.0),
    (10.0, -10.0, -45.0),    # up to the right
    (-10.0, 10.0, -45.0),
    (10.0, 30.0, 71.565051),     # steep: already legible, left alone
    (-10.0, 30.0, -71.565051),   # steep the other way: wraps a half-turn
    (0.0, 0.0, 0.0),             # a cota of no length says nothing
])
def test_the_text_never_reads_head_to_the_right(dx, dy, want):
    deg = readable_deg(dx, dy)
    assert deg == pytest.approx(want, abs=1e-6)
    assert -90.0 <= deg < 90.0          # the legible half-turn, half-open


def test_a_line_and_its_reverse_give_the_very_same_text_angle():
    """Which way the drafter happened to drag is not information."""
    for dx, dy in ((40.0, 0.0), (0.0, 40.0), (30.0, 17.0), (-8.0, 25.0)):
        assert readable_deg(dx, dy) == pytest.approx(readable_deg(-dx, -dy))


# ---- the sheet cota paints it -------------------------------------------

def _paint(ct, w_mm=80.0, h_mm=80.0, px=4):
    from views.composer import paint_cota_mm
    img = QImage(int(w_mm * px), int(h_mm * px), QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, False)
    p.scale(px, px)
    p.translate(ct.x_mm, ct.y_mm)
    paint_cota_mm(p, ct)
    p.end()
    return img


def _ink(img) -> int:
    return sum(1 for y in range(img.height()) for x in range(img.width())
               if img.pixelColor(x, y) != QColor(255, 255, 255))


def test_the_same_vertical_cota_drawn_either_way_paints_identically():
    """Two cotas over the SAME segment, dragged in opposite directions.
    Before the fix the one drawn downward came out turned 180°."""
    down = CotaItem(x_mm=40.0, y_mm=20.0, dx_mm=0.0, dy_mm=40.0,
                    sep_mm=0.0, scale_n=50.0)
    up = CotaItem(x_mm=40.0, y_mm=60.0, dx_mm=0.0, dy_mm=-40.0,
                  sep_mm=0.0, scale_n=50.0)
    assert down.label() == up.label() == "2.00 m"
    a, b = _paint(down), _paint(up)
    assert _ink(a) > 200, "nothing was drawn"
    assert a == b


def test_the_hit_area_turns_with_the_text(monkeypatch):
    """`shape()` had the OTHER spelling of the rule, so on a vertical cota
    the click strip leaned away from the label it was meant to cover."""
    from views.composer import ComposerWindow, CotaCanvasItem
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = None
    try:
        comp = ComposerWindow(win)
        ct = CotaItem(x_mm=60.0, y_mm=40.0, dx_mm=0.0, dy_mm=50.0,
                      sep_mm=0.0, scale_n=50.0, text_pos="above")
        comp.comp.cotas.append(ct)
        comp._rebuild_canvas()
        item = next(it for it in comp.canvas.items()
                    if isinstance(it, CotaCanvasItem) and it.model is ct)
        shape = item.shape().translated(item.pos())
        # «Above» a bottom-to-top text is the page's LEFT: that is where the
        # label sits, and the strip must be there too.
        from PySide6.QtCore import QPointF
        left = QPointF(ct.x_mm - ct.offset_mm - ct.text_mm * 0.6,
                       ct.y_mm + ct.dy_mm / 2)
        right = QPointF(ct.x_mm + ct.offset_mm + ct.text_mm * 0.6,
                        ct.y_mm + ct.dy_mm / 2)
        assert shape.contains(left)
        assert not shape.contains(right)
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- and so do the MODEL's dimensions on a sheet -------------------------

def test_a_model_dimension_on_a_sheet_reads_the_same_way():
    """The pair of call sites that got it wrong ALWAYS: a vertical model
    dimension projected into a frame came out at +90°, head to the right."""
    from core.dimension import Dimension
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    win = MainWindow()
    comp = ComposerWindow(win)
    try:
        scene = win.viewport.scene
        scene.mesh.add_face([QVector3D(-2, 0, 0), QVector3D(2, 0, 0),
                             QVector3D(2, 0, 3), QVector3D(-2, 0, 3)])
        scene.dimensions.append(                    # the wall's HEIGHT
            Dimension(QVector3D(-2, 0, 0), QVector3D(-2, 0, 3),
                      QVector3D(-0.5, 0, 0)))
        scene.version += 1
        frame = comp.comp.frames[0]
        frame.view_key, frame.style = "std:front", "vectorial"
        frame.w_mm, frame.h_mm, frame.scale_n = 200.0, 100.0, 50.0
        frame.annotations = True
        annots = comp.compute_annotations(frame)
        value = next(a for a in annots if a[0] == "text" and "m" in a[4])
        assert value[4] == "3.00 m"
        assert value[3] == pytest.approx(-90.0, abs=1e-6)
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- reglas 1, 5 y 18: la norma del DOCUMENTO ----------------------------

def test_the_position_carries_the_standard_the_line_obeys():
    """Rule 5 (09:00): in ISO «la línea de cota NUNCA se interrumpe», and
    the text goes above it. Opening the line around the text is the
    German/Japanese standard (rule 18, 14:00) — so the two standards are
    the two positions, and switching the document's does NOT redraw a cota
    already placed (Marco's own 0.80/0.50 report of 2026-09-08 depends on
    `centered` opening the line)."""
    iso = CotaItem(x_mm=20.0, y_mm=40.0, dx_mm=48.0, dy_mm=0.0,
                   sep_mm=0.0, scale_n=50.0, text_pos="above")
    din = CotaItem(x_mm=20.0, y_mm=40.0, dx_mm=48.0, dy_mm=0.0,
                   sep_mm=0.0, scale_n=50.0, text_pos="centered")
    row = int(40.0 * 4)
    span = range(int(20.0 * 4) + 4, int(68.0 * 4) - 4)

    def gap(img):
        return sum(1 for x in span
                   if img.pixelColor(x, row) == QColor(255, 255, 255))
    assert gap(_paint(iso)) == 0            # ISO: the line runs whole
    assert gap(_paint(din)) > 20            # German: it opens for the text


def test_the_standard_lives_in_the_document_and_defaults_to_iso(tmp_path):
    """It travels in the .igz, and an older file — which has no such key —
    opens as ISO, which is what those drawings were made to."""
    from pathlib import Path
    from core.scene import Scene
    from formats.igz import load_into, save_scene
    assert Scene().dimension_style["norma"] == "iso"

    scene = Scene()
    scene.dimension_style["norma"] = "din"
    path = Path(tmp_path) / "cotas.igz"
    save_scene(scene, path)
    back = Scene()
    load_into(back, path)
    assert back.dimension_style["norma"] == "din"

    legacy = Scene()                       # the load path is an update()
    legacy.dimension_style.update({"decimals": 3, "units": "cm"})
    assert legacy.dimension_style["norma"] == "iso"


def test_a_new_cota_is_born_iso_whatever_the_document_or_memory_say(
        monkeypatch):
    """Only ISO is on offer for now (Marco, 2026-09-20: «hagamos las ISO
    por ahora… en posición de texto sé restrictivo»): a new cota is born
    ``above`` even if the document carries the German standard or the
    remembered style of the last cota says otherwise. The panel's
    text-position menu offers ISO and, for a cota whose upper side is
    taken, «below» — nothing outside a standard."""
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = None
    try:
        comp = ComposerWindow(win)
        comp._last_cota_style = {}
        assert comp.dimension_norma() == "iso"
        assert comp._new_cota((0.0, 0.0), (40.0, 0.0), 0.0).text_pos == "above"
        win.viewport.scene.dimension_style["norma"] = "din"
        assert comp._new_cota((0.0, 0.0), (40.0, 0.0), 0.0).text_pos == "above"
        comp._last_cota_style = {"text_pos": "aside"}
        assert comp._new_cota((0.0, 0.0), (40.0, 0.0), 0.0).text_pos == "above"
        keys = [comp.cota_text_pos.itemData(i)
                for i in range(comp.cota_text_pos.count())]
        assert keys == ["above", "below"]
        # …and the model's dimension-style panel offers no standard switch.
        from views.tray import DimensionStylePanel
        assert not hasattr(DimensionStylePanel(win), "_norma")
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
