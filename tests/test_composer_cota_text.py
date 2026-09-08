# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet cotas: double-click edits the text, <> stands for the value."""
from __future__ import annotations

from core.composition import CotaItem


def test_cota_text_placeholder_expands_to_the_value():
    ct = CotaItem(dx_mm=80.0, dy_mm=0.0, scale_n=100.0)
    assert ct.label() == "8.00 m"
    ct.text = "H = <> (verificar)"
    assert ct.label() == "H = 8.00 m (verificar)"
    ct.text = "VARIABLE"
    assert ct.label() == "VARIABLE"


def test_double_click_edits_the_cota_text(monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from views.composer import ComposerWindow, CotaCanvasItem
    from views.main_window import MainWindow

    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = None
    try:
        comp = ComposerWindow(win)
        ct = CotaItem(x_mm=30.0, y_mm=30.0, dx_mm=60.0, dy_mm=0.0,
                      scale_n=40.0)
        comp.comp.cotas.append(ct)
        comp._rebuild_canvas()
        item = next(it for it in comp.canvas.items()
                    if isinstance(it, CotaCanvasItem) and it.model is ct)
        asked = {}

        def fake_get_text(parent, title, label, text="", **kw):
            asked["prefill"] = text
            return asked["answer"], True
        monkeypatch.setattr(QInputDialog, "getText",
                            staticmethod(fake_get_text))

        asked["answer"] = "H = <>"
        comp.edit_cota_text(item)
        assert asked["prefill"] == "2.40 m"              # shows the value
        assert ct.text == "H = <>" and ct.label() == "H = 2.40 m"
        comp.history.undo()
        assert ct.text == ""
        comp.history.redo()

        asked["answer"] = "<>"                           # back to automatic
        comp.edit_cota_text(item)
        assert asked["prefill"] == "H = <>"
        assert ct.text == "" and ct.label() == "2.40 m"
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_centered_horizontal_label_on_a_vertical_cota_opens_only_its_height():
    """A horizontal label on a vertical cota covers its HEIGHT along the
    line, not its width: the dimension line must survive on both sides
    (Marco, 2026-09-08: «en 0.80 no se ve la línea de acotación y en la
    0.50 sí» — the 16 mm cota lost its line, the 10 mm one kept it)."""
    from PySide6.QtGui import QImage, QPainter
    from core.composition import CotaItem
    from views.composer import paint_cota_mm
    ct = CotaItem(x_mm=0.0, y_mm=0.0, dx_mm=0.0, dy_mm=-16.0, sep_mm=-9.0,
                  scale_n=50.0, text_pos="centered", text_align="horizontal",
                  text_mm=3.0, stroke_mm=0.25, ends="tick", text_bg="")
    assert ct.label().startswith("0.80")
    img = QImage(400, 400, QImage.Format_RGB32)
    img.fill(0xFFFFFFFF)
    p = QPainter(img)
    p.scale(8.0, 8.0)                    # 8 px per mm
    p.translate(25.0, 30.0)              # the cota's origin
    paint_cota_mm(p, ct)
    p.end()
    # the dimension line runs at x = -9 mm → column (25 - 9) * 8 = 128 px,
    # from y = 30 mm (row 240) up to y = 14 mm (row 112); the label sits
    # at the middle (y = 22 mm, row 176)

    def ink(row):
        return any((img.pixel(x, row) & 0xFF) < 160 for x in range(126, 131))
    assert ink(240 - 4 * 8)              # 4 mm from the lower end: line
    assert ink(112 + 4 * 8)              # 4 mm from the upper end: line
    # just outside the glyphs (±1.5 mm) but inside the opening (±2.85 mm)
    assert not ink(176 + 18) and not ink(176 - 18)


def test_beside_puts_a_horizontal_label_whole_to_one_side_of_a_vertical_cota():
    """Marco, 2026-09-08: «sería bueno que la posición de texto en acotar
    también haya una opción para ponerla a un costado» — the label stands
    clear of the line on one side (or the other), and the line stays whole."""
    from PySide6.QtGui import QImage, QPainter
    from core.composition import CotaItem
    from views.composer import cota_aside_frame, paint_cota_mm

    def render(pos):
        ct = CotaItem(x_mm=0.0, y_mm=0.0, dx_mm=0.0, dy_mm=-16.0, sep_mm=-9.0,
                      scale_n=50.0, text_pos=pos, text_align="horizontal",
                      text_mm=3.0, stroke_mm=0.25, ends="tick", text_bg="")
        img = QImage(480, 400, QImage.Format_RGB32)
        img.fill(0xFFFFFFFF)
        p = QPainter(img)
        p.scale(8.0, 8.0)
        p.translate(30.0, 30.0)
        paint_cota_mm(p, ct)
        p.end()
        return ct, img

    def ink(img, x0, x1, y0, y1):
        return any((img.pixel(x, y) & 0xFF) < 160
                   for y in range(y0, y1) for x in range(x0, x1))

    line_px = (30 - 9) * 8                      # the dimension line's column
    mid_row = (30 - 8) * 8
    ct, img = render("aside")
    ox, oy, deg, tw, th = cota_aside_frame(ct)
    assert deg == 0.0 and abs(oy) < 1e-9
    assert abs(abs(ox) - (ct.offset_mm + tw / 2)) < 1e-9   # clear of the line
    side = 1 if ox > 0 else -1
    # the line is whole at the label's height
    assert ink(img, line_px - 2, line_px + 3, mid_row - 2, mid_row + 3)
    # the label inks on its side only, past the offset
    lo, hi = sorted((line_px + side * 10, line_px + side * int(tw * 8)))
    assert ink(img, lo, hi, mid_row - 12, mid_row + 12)
    lo2, hi2 = sorted((line_px - side * 10, line_px - side * int(tw * 8)))
    assert not ink(img, lo2, hi2, mid_row - 12, mid_row + 12)
    ct2, img2 = render("aside_below")
    ox2 = cota_aside_frame(ct2)[0]
    assert ox2 == -ox                                        # the other side
