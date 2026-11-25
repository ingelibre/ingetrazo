# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet cotas: the label below its line, turned to read the other way,
and the text–line gap set from the panel."""
from __future__ import annotations

from core.composition import Composicion, CotaItem

PX = 20


def _paint(ct, ox=20.0, oy=30.0, w=100, h=80):
    from PySide6.QtGui import QImage, QPainter
    from views.composer import paint_cota_mm
    img = QImage(w * PX, h * PX, QImage.Format_RGB32)
    img.fill(0xFFFFFFFF)
    p = QPainter(img)
    p.scale(PX, PX)
    p.translate(ox, oy)
    paint_cota_mm(p, ct)
    p.end()
    return img


def _inked(img, x, y) -> bool:
    return (img.pixel(x, y) & 0xFF) < 128


def test_a_label_below_hangs_offset_mm_under_the_line():
    """The gap is measured to where the figures begin, as «above» measures
    it to their baseline: the drafter's gap is the gap he sees."""
    ct = CotaItem(dx_mm=60.0, dy_mm=0.0, sep_mm=0.0, text="88", text_mm=5.0,
                  offset_mm=2.0, ends="none", text_pos="below")
    img = _paint(ct)
    line_y = 30 * PX
    x0, x1 = 45 * PX, 55 * PX
    top = next((y for y in range(line_y + PX // 2, img.height())
                if any(_inked(img, x, y) for x in range(x0, x1))), None)
    assert top is not None
    assert not any(_inked(img, x, y) for x in range(x0, x1)
                   for y in range(line_y - 10 * PX, line_y - PX // 2))
    gap_mm = (top - line_y) / PX
    assert 1.8 <= gap_mm <= 2.4, gap_mm


def test_flip_turns_a_vertical_label_but_keeps_its_side():
    """A vertical cota reads bottom-to-top at the left of its line (ISO);
    flipped, it reads top-to-bottom — from the right — still at the left."""
    from views.composer import cota_text_layout
    plain = CotaItem(dx_mm=0.0, dy_mm=40.0, sep_mm=0.0, text="88",
                     text_mm=5.0, offset_mm=1.0, ends="none")
    flipped = CotaItem(**{**plain.__dict__, "text_flip": True})
    assert cota_text_layout(plain) == ("above", -90.0)
    assert cota_text_layout(flipped) == ("below", 90.0)

    line_x = 20 * PX
    for ct in (plain, flipped):
        img = _paint(ct)
        rows = range(40 * PX, 60 * PX)
        left = any(_inked(img, x, y) for y in rows
                   for x in range(line_x - 10 * PX, line_x - PX // 2))
        right = any(_inked(img, x, y) for y in rows
                    for x in range(line_x + PX // 2, line_x + 10 * PX))
        assert left and not right
    # …and the glyphs really did turn
    assert _paint(plain) != _paint(flipped)


def test_flip_does_not_turn_a_horizontal_label():
    from views.composer import cota_text_layout
    ct = CotaItem(dx_mm=0.0, dy_mm=40.0, text_align="horizontal",
                  text_flip=True)
    assert cota_text_layout(ct) == ("above", 0.0)


def test_flip_travels_in_the_file():
    comp = Composicion()
    comp.cotas.append(CotaItem(text_flip=True, text_pos="below",
                               offset_mm=1.7))
    again = Composicion.from_dict(comp.to_dict()).cotas[0]
    assert (again.text_flip, again.text_pos, again.offset_mm) == (
        True, "below", 1.7)


def test_the_panel_sets_position_gap_and_flip(monkeypatch):
    from views.composer import ComposerWindow, CotaCanvasItem
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = None
    try:
        comp = ComposerWindow(win)
        ct = CotaItem(x_mm=30.0, y_mm=30.0, dx_mm=0.0, dy_mm=40.0,
                      scale_n=50.0, offset_mm=0.5)
        comp.comp.cotas.append(ct)
        comp._rebuild_canvas()
        item = next(it for it in comp.canvas.items()
                    if isinstance(it, CotaCanvasItem) and it.model is ct)
        comp.canvas.clearSelection()
        item.setSelected(True)
        comp.on_selection_changed()
        assert comp.cota_offset.value() == 0.5
        assert not comp.cota_text_flip.isChecked()
        comp.cota_text_pos.setCurrentIndex(
            comp.cota_text_pos.findData("below"))
        comp.cota_offset.setValue(1.5)
        comp.cota_text_flip.setChecked(True)
        model = item.model
        assert (model.text_pos, model.offset_mm, model.text_flip) == (
            "below", 1.5, True)
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_ticking_show_unit_changes_nothing_else(monkeypatch):
    """The panel writes every field back on any edit. A box the user did
    not touch must keep the cota's own value: the old ±100 mm separation
    box clamped a line placed further out, and every box rounded to 2
    decimals; an «off the menu» text position became «above»."""
    from views.composer import ComposerWindow, CotaCanvasItem
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = None
    try:
        comp = ComposerWindow(win)
        far = CotaItem(x_mm=30.0, y_mm=30.0, dx_mm=40.0, dy_mm=0.0,
                       sep_mm=1150.0, text_pos="centered", offset_mm=0.537)
        fine = CotaItem(x_mm=30.0, y_mm=90.0, dx_mm=40.0, dy_mm=0.0,
                        sep_mm=-9.101)
        comp.comp.cotas += [far, fine]
        comp._rebuild_canvas()
        for ct in (far, fine):
            item = next(it for it in comp.canvas.items()
                        if isinstance(it, CotaCanvasItem) and it.model is ct)
            comp.canvas.clearSelection()
            item.setSelected(True)
            comp.on_selection_changed()
            before = dict(ct.__dict__)
            comp.cota_show_unit.setChecked(not ct.show_unit)
            changed = {k for k in before if before[k] != ct.__dict__[k]}
            assert changed == {"show_unit"}, changed
        comp.cota_sep.setValue(-12.0)              # a real edit still lands
        assert fine.sep_mm == -12.0
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
