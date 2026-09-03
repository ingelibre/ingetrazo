# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Bold / italic / underline on text blocks and leader labels, applied from
the panel (the Italic box used to be wired to a handler that never sent
it, so it did nothing)."""
from __future__ import annotations

from PySide6.QtGui import QImage, QPainter

from core.composition import (AddItemCommand, Composicion, EtiquetaItem,
                              TextoItem)


def _ink(img: QImage) -> int:
    return sum(1 for x in range(img.width()) for y in range(img.height())
               if (img.pixel(x, y) & 0xFFFFFF) != 0xFFFFFF)


def _render(paint, model) -> QImage:
    img = QImage(420, 160, QImage.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    p = QPainter(img)
    p.scale(3, 3)
    p.translate(8, 8)
    paint(p, model)
    p.end()
    return img


def test_text_block_underline_round_trips_and_paints():
    from views.composer import paint_text_mm
    plain = TextoItem(text="Vista frontal", size_pt=14.0, w_mm=100.0)
    under = TextoItem(text="Vista frontal", size_pt=14.0, w_mm=100.0,
                      underline=True)
    c = Composicion()
    c.texts += [plain, under]
    back = Composicion.from_dict(c.to_dict()).texts
    assert (back[0].underline, back[1].underline) == (False, True)
    assert _ink(_render(paint_text_mm, under)) > _ink(_render(paint_text_mm, plain))
    # files from before the field load as plain text
    d = c.to_dict()
    d["texts"][1].pop("underline")
    assert Composicion.from_dict(d).texts[1].underline is False


def test_label_italic_and_underline_round_trip_and_paint():
    from views.composer import paint_etiqueta_mm
    base = dict(x_mm=10.0, y_mm=10.0, w_mm=80.0, ax_mm=-4.0, ay_mm=30.0,
                text="Muro", size_pt=12.0, arrow=False)
    plain = EtiquetaItem(**base)
    italic = EtiquetaItem(**base, italic=True)
    under = EtiquetaItem(**base, underline=True)
    c = Composicion()
    c.etiquetas += [plain, italic, under]
    back = Composicion.from_dict(c.to_dict()).etiquetas
    assert [(e.italic, e.underline) for e in back] == [
        (False, False), (True, False), (False, True)]
    imgs = [_render(paint_etiqueta_mm, e) for e in (plain, italic, under)]
    assert _ink(imgs[2]) > _ink(imgs[0])
    assert imgs[1] != imgs[0]


def test_panel_applies_style_to_text_blocks_and_labels(monkeypatch):
    from views.composer import ComposerWindow, EtiquetaItem as _E  # noqa: F401
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    try:
        t = TextoItem(x_mm=20.0, y_mm=20.0, w_mm=60.0, text="Planta")
        et = EtiquetaItem(x_mm=80.0, y_mm=40.0, text="Muro")
        comp.history.execute(AddItemCommand(comp.comp, t))
        comp.history.execute(AddItemCommand(comp.comp, et))
        comp._rebuild_canvas()
        ti = comp._item_for(t)
        ti.setSelected(True)
        comp.on_selection_changed()
        comp.text_italic.setChecked(True)
        comp.text_underline.setChecked(True)
        comp.text_align.setCurrentIndex(comp.text_align.findData("center"))
        assert (t.italic, t.underline, t.align) == (True, True, "center")
        assert (t.text, t.size_pt, t.bold) == ("Planta", 14.0, False)
        ti.setSelected(False)
        ei = comp._item_for(et)
        ei.setSelected(True)
        comp.on_selection_changed()
        comp.et_bold.setChecked(True)
        comp.et_italic.setChecked(True)
        comp.et_underline.setChecked(True)
        assert (et.bold, et.italic, et.underline) == (True, True, True)
        comp.history.undo()
        assert et.underline is False
        assert "underline" in comp.STYLE_FIELDS[TextoItem]
        assert {"italic", "underline"} <= set(comp.STYLE_FIELDS[EtiquetaItem])
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
