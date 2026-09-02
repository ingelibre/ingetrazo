# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet cota label style (position / orientation / colour), style memory
for new cotas, and Copy / Paste style."""
from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter

from core.composition import CotaItem, TextoItem


def _composer(monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    return win, ComposerWindow(win)


def _close(win, comp):
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def test_label_position_and_orientation_paint_and_hit_shape():
    from views.composer import CotaCanvasItem, paint_cota_mm

    class _Comp:
        pass
    for pos in ("above", "centered", "below"):
        for align in ("aligned", "horizontal"):
            ct = CotaItem(dx_mm=60.0, dy_mm=30.0, sep_mm=8.0, scale_n=50.0,
                          text_pos=pos, text_align=align, text_color="#aa0000")
            img = QImage(200, 200, QImage.Format_ARGB32)
            img.fill(0xFFFFFFFF)
            p = QPainter(img)
            p.translate(40, 60)
            paint_cota_mm(p, ct)                      # must not raise
            p.end()
    # The hit strip follows the label: below the line for "below".
    item_above = CotaCanvasItem(_Comp(), CotaItem(dx_mm=60.0, dy_mm=0.0,
                                                  sep_mm=0.0, text_pos="above"))
    item_below = CotaCanvasItem(_Comp(), CotaItem(dx_mm=60.0, dy_mm=0.0,
                                                  sep_mm=0.0, text_pos="below"))
    above_pt, below_pt = QPointF(30.0, -3.0), QPointF(30.0, 3.0)
    assert item_above.shape().contains(above_pt)
    assert not item_above.shape().contains(below_pt)
    assert item_below.shape().contains(below_pt)


def test_new_cotas_inherit_the_last_style_and_copy_paste_style(monkeypatch):
    from views.composer import CotaCanvasItem
    win, comp = _composer(monkeypatch)
    try:
        comp.tool_mode = "cota"
        comp.place_tool(20.0, 20.0, 80.0, 20.0, sep_mm=6.0)
        first = comp.comp.cotas[-1]
        assert first.text_pos == "above" and first.text_color == ""
        # Edit its style through the panel path: later cotas inherit it.
        comp._rebuild_canvas()
        item = next(it for it in comp.canvas.items()
                    if isinstance(it, CotaCanvasItem) and it.model is first)
        comp._panel_edit(item, {"text_pos": "centered", "text_color": "#cc0000",
                                "ends": "arrow"})
        comp._remember_cota_style(first)
        comp.tool_mode = "cota"                 # place_tool drops to select
        comp.place_tool(20.0, 40.0, 80.0, 40.0, sep_mm=6.0)
        second = comp.comp.cotas[-1]
        assert (second.text_pos, second.text_color, second.ends) == (
            "centered", "#cc0000", "arrow")
        assert second.sep_mm == 6.0 and second.dx_mm == 60.0   # geometry own

        # Copy style from a third, plain cota → paste onto the first two.
        plain = CotaItem(x_mm=20.0, y_mm=60.0, dx_mm=60.0, text_mm=4.0,
                         color="#0000cc", text_pos="below")
        comp.comp.cotas.append(plain)
        comp._rebuild_canvas()
        items = {id(it.model): it for it in comp.canvas.items()
                 if isinstance(it, CotaCanvasItem)}
        comp.copy_style(items[id(plain)])
        assert comp.can_paste_style(first)
        assert not comp.can_paste_style(TextoItem())
        items[id(first)].setSelected(True)
        items[id(second)].setSelected(True)
        comp.paste_style()
        assert first.text_mm == 4.0 and first.color == "#0000cc"
        assert second.text_pos == "below" and second.text_color == ""
        assert second.dx_mm == 60.0 and second.y_mm == 40.0    # untouched
        comp.history.undo()                                     # one item back
        assert second.text_pos == "centered" or first.text_mm != 4.0
    finally:
        _close(win, comp)


def test_cota_labels_can_carry_a_background():
    from core.composition import CotaAngularItem
    from views.composer import paint_cota_angular_mm, paint_cota_mm
    img = QImage(300, 200, QImage.Format_ARGB32)
    for pos in ("above", "centered", "below"):
        ct = CotaItem(dx_mm=80.0, dy_mm=0.0, sep_mm=0.0, text_pos=pos,
                      text_bg="#ffe08a", text_mm=4.0, offset_mm=1.0)
        img.fill(0xFFFFFFFF)
        p = QPainter(img)
        p.scale(2, 2)
        p.translate(20, 50)
        paint_cota_mm(p, ct)
        p.end()
        # sample the background strip just above the label's text box,
        # where no glyph reaches (offset 1 mm, text 4 mm, box 1.3 × text)
        top = {"above": 50 - 1.0 - 4.0, "centered": 50 - 4.0 * 0.65,
               "below": 50 + 1.0}[pos]
        x = int((20 + 40) * 2)
        assert img.pixel(x, int((top - 0.2) * 2)) & 0xFFFFFF == 0xFFE08A, pos
    ca = CotaAngularItem(ax_mm=40, ay_mm=0, bx_mm=0, by_mm=-40, radius_mm=20,
                         text_bg="#ffe08a", text_mm=4.0)
    img.fill(0xFFFFFFFF)
    p = QPainter(img)
    p.scale(2, 2)
    p.translate(100, 80)
    paint_cota_angular_mm(p, ca)
    p.end()
    import math
    a0, sweep = ca.angles()
    am = a0 + sweep / 2
    d = 20 + ca.offset_mm + ca.text_mm * 0.75
    lx, ly = 100 + d * math.cos(am), 80 + d * math.sin(am)
    assert img.pixel(int(lx * 2), int((ly - 4.0 * 0.75 + 0.2) * 2)) & 0xFFFFFF == 0xFFE08A
