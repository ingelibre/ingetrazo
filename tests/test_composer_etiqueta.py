# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Labels with a leader (LayOut's Label) and double-click text editing."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QImage, QPainter

from core.composition import (AddItemCommand, Composicion, EtiquetaItem,
                              MarcoVista, RemoveItemCommand, TextoItem)


def test_label_model_round_trips_and_paints():
    from views.composer import paint_etiqueta_mm
    c = Composicion()
    et = EtiquetaItem(x_mm=80, y_mm=40, ax_mm=-30, ay_mm=20, text="Muro\ncorrido",
                      anchor_uid="f1", a_world=[1, 2, 3], bg_color="#ffffaa")
    AddItemCommand(c, et).do()
    assert c.etiquetas == [et] and et in c.all_items() and et.anchored
    back = Composicion.from_dict(c.to_dict()).etiquetas[0]
    assert (back.text, back.ax_mm, back.a_world) == ("Muro\ncorrido", -30, [1, 2, 3])
    assert back.h_mm > 6.0
    RemoveItemCommand(c, et).do()
    assert c.etiquetas == []
    for arrow in (True, False):
        et.arrow = arrow
        img = QImage(300, 200, QImage.Format_ARGB32)
        img.fill(0xFFFFFFFF)
        p = QPainter(img)
        p.scale(2, 2)
        p.translate(60, 40)
        paint_etiqueta_mm(p, et)
        p.end()
        # the leader (and its head) reach the pointed-at spot
        tx, ty = int((60 - 30) * 2), int((40 + 20) * 2)
        window = [img.pixel(tx + dx, ty + dy) & 0xFFFFFF
                  for dx in range(-2, 7) for dy in range(-6, 3)]
        assert any(px != 0xFFFFFF for px in window), arrow


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


def test_label_tool_places_anchored_and_follows_the_frame(monkeypatch):
    win, comp = _composer(monkeypatch)
    try:
        frame = comp.comp.frames[0]
        frame.uid = ""
        comp.tool_mode = "etiqueta"
        world = (1.0, 2.0, 0.5)
        comp.place_tool(50.0, 60.0, 90.0, 30.0, hit_a=(50.0, 60.0, world, frame))
        et = comp.comp.etiquetas[-1]
        assert (et.x_mm, et.y_mm) == (90.0, 30.0)
        assert (et.ax_mm, et.ay_mm) == (-40.0, 30.0)
        assert et.anchored and et.anchor_uid == frame.uid and et.a_world == [1, 2, 0.5]
        assert comp.tool_mode == "select"                 # only cotas stay armed
        assert comp._item_label(et).startswith("Label")   # "Etiqueta" in es
        # The frame moves 10 mm right: the pointed-at spot follows the model
        # (page point shifts), the text block stays where it was.
        monkeypatch.setattr(comp, "frame_snap_points",
                            lambda f: (None, __import__("numpy").empty((0, 3))))
        pages = {}

        def fake_w2p(f, pts):
            return [(f.x_mm + 30.0, f.y_mm + 20.0) for _ in pts]
        monkeypatch.setattr(comp, "_frame_world_to_page", fake_w2p)
        comp._reproject_anchored_cotas()
        first = (et.ax_mm, et.ay_mm)
        frame.x_mm += 10.0
        comp._reproject_anchored_cotas()
        assert (et.x_mm, et.y_mm) == (90.0, 30.0)
        assert et.ax_mm == pytest.approx(first[0] + 10.0)
        assert et.ay_mm == pytest.approx(first[1])
    finally:
        _close(win, comp)


def test_double_click_edits_text_blocks_and_labels(monkeypatch):
    from views.composer import EtiquetaCanvasItem, TextItem
    win, comp = _composer(monkeypatch)
    try:
        t = TextoItem(x_mm=20, y_mm=20, text="hola")
        et = EtiquetaItem(x_mm=60, y_mm=60, text="Etiqueta")
        comp.comp.texts.append(t)
        comp.comp.etiquetas.append(et)
        comp._rebuild_canvas()
        items = {id(it.model): it for it in comp.canvas.items()
                 if isinstance(it, (TextItem, EtiquetaCanvasItem))}
        from views.composer import InlineTextEditor
        # In-place editor over the text block, same font scale as the paint.
        comp.edit_text_item(items[id(t)])
        ed = comp._inline_editor
        assert isinstance(ed, InlineTextEditor) and ed.toPlainText() == "hola"
        assert ed.scale() == pytest.approx(t.size_pt * 25.4 / 72.0 / 100.0 * 0.75)
        ed.setPlainText("hola mundo\n")
        ed.finish(commit=True)
        assert t.text == "hola mundo" and comp._inline_editor is None
        assert ed.scene() is None
        comp.edit_text_item(items[id(et)])
        ed = comp._inline_editor
        ed.setPlainText("Muro eje A")
        ed.finish(commit=True)
        assert et.text == "Muro eje A"
        comp.history.undo()
        assert et.text == "Etiqueta"
        # Esc cancels, and a second double-click replaces a pending editor.
        comp.edit_text_item(items[id(et)])
        first = comp._inline_editor
        first.setPlainText("basura")
        first.finish(commit=False)
        assert et.text == "Etiqueta" and comp._inline_editor is None
        comp.edit_text_item(items[id(t)])
        comp.edit_text_item(items[id(et)])
        assert comp._inline_editor.item is items[id(et)]
        comp.end_inline_edit(None, None)
        assert comp._inline_editor is None
        assert comp._style_fields_for(et)[0] is EtiquetaItem
        assert "etiqueta" in [m for m, *_ in type(comp).TOOLS]
    finally:
        _close(win, comp)


def test_the_leader_leaves_the_text_not_the_far_edge_of_a_wide_block():
    """Marco, 2026-09-08: «¿por qué no me sale la línea hasta el texto?» —
    a 50 mm block around two short words started its leader at the block's
    bottom middle, 15 mm past the words. It starts at the text now."""
    from PySide6.QtGui import QImage, QPainter
    from core.composition import EtiquetaItem
    from views.composer import (etiqueta_ink_w_mm, etiqueta_leader_start,
                                paint_etiqueta_mm)
    et = EtiquetaItem(text="ab", w_mm=50.0, ax_mm=40.0, ay_mm=5.0,
                      size_pt=11.0, arrow=False, bg_color="")
    tw = etiqueta_ink_w_mm(et)
    assert 3.0 < tw < 12.0                             # the two letters
    sx, sy = etiqueta_leader_start(et)
    assert abs(sx - (tw + 0.8)) < 1e-9                 # right edge of the text
    assert abs(sy - et.h_mm / 2) < 1e-9
    img = QImage(600, 200, QImage.Format_RGB32)
    img.fill(0xFFFFFFFF)
    p = QPainter(img)
    p.scale(8.0, 8.0)
    p.translate(5.0, 5.0)
    paint_etiqueta_mm(p, et)
    p.end()
    # midway between the text and the point the leader is a hair above
    # y = 5 mm; the old block-bottom start would have put it ~4 mm lower
    mx = (sx + 40.0) / 2
    my = sy + (5.0 - sy) * (mx - sx) / (40.0 - sx)
    px, py = round((5.0 + mx) * 8), round((5.0 + my) * 8)
    assert any((img.pixel(px, y) & 0xFF) < 160 for y in range(py - 3, py + 4))
    assert not any((img.pixel(px, y) & 0xFF) < 160
                   for y in range(py + 20, py + 45))
