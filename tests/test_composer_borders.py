# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Background opacity, the frame border that prints only when asked, and
the configurable sheet border."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from core.composition import (Composicion, CotaItem, MarcoVista,
                              PAPER_SIZES_MM, TextoItem)


def _rgb(img, x, y):
    return img.pixel(x, y) & 0xFFFFFF


def test_background_opacity_blends_with_the_page():
    from views.composer import paint_cota_mm, paint_text_mm
    img = QImage(300, 120, QImage.Format_ARGB32)
    for opacity, expect_full in ((1.0, True), (0.5, False)):
        t = TextoItem(w_mm=40.0, text="Pileta", bg_color="#0000ff",
                      bg_opacity=opacity)
        img.fill(0xFFFFFFFF)
        p = QPainter(img)
        p.scale(2, 2)
        p.translate(10, 10)
        paint_text_mm(p, t)
        p.end()
        px = _rgb(img, int((10 + 38) * 2), int((10 + 1) * 2))
        assert (px == 0x0000FF) is expect_full
        if not expect_full:
            assert px not in (0x0000FF, 0xFFFFFF)     # a real blend
    ct = CotaItem(dx_mm=80.0, text_bg="#ff0000", text_bg_opacity=0.25,
                  text_mm=4.0, offset_mm=1.0)
    img.fill(0xFFFFFFFF)
    p = QPainter(img)
    p.scale(2, 2)
    p.translate(20, 50)
    paint_cota_mm(p, ct)
    p.end()
    px = _rgb(img, int(60 * 2), int((50 - 5 - 0.2) * 2))
    assert px not in (0xFF0000, 0xFFFFFF)


def test_frame_border_prints_only_when_asked_but_guides_on_screen():
    from views.composer import paint_frame_mm
    frame = MarcoVista(w_mm=60.0, h_mm=40.0, style="sombreado")
    fill = QImage(4, 4, QImage.Format_RGB32)
    fill.fill(0xFFDDDDDD)

    def render(screen, **kw):
        for k, v in kw.items():
            setattr(frame, k, v)
        img = QImage(200, 140, QImage.Format_ARGB32)
        img.fill(0xFFFFFFFF)
        p = QPainter(img)
        p.scale(2, 2)
        p.translate(10, 10)
        paint_frame_mm(p, frame, fill, screen=screen)
        p.end()
        return img

    # print, border off: the edge pixel is the page (or the fill), no ink
    img = render(False, border=False)
    edge = _rgb(img, int((10 + 60) * 2) + 1, int((10 + 20) * 2))
    assert edge == 0xFFFFFF
    # canvas, border off: a light guide, never the dark ink
    img = render(True, border=False)
    edge_px = [_rgb(img, int((10 + 60) * 2) + d, int((10 + 20) * 2))
               for d in (-1, 0, 1)]
    assert any(px != 0xFFFFFF for px in edge_px)
    assert all(px != 0x282E36 for px in edge_px)
    # print, border on with its own width and colour
    img = render(False, border=True, border_mm=1.0, border_color="#ff0000")
    edge_px = [_rgb(img, int((10 + 60) * 2) + d, int((10 + 20) * 2))
               for d in (-2, -1, 0, 1)]
    assert 0xFF0000 in edge_px
    assert MarcoVista().border is False


def test_sheet_border_round_trips_and_paints_every_style():
    from views.composer import paint_sheet_border_mm
    c = Composicion(paper="A4", landscape=True, margin_mm=10.0)
    assert c.border is False
    assert "border" not in c.to_dict()
    c.border, c.border_mm, c.border_color = True, 1.0, "#0000ff"
    c.border_radius_mm, c.border_style = 4.0, "double"
    back = Composicion.from_dict(c.to_dict())
    assert (back.border, back.border_mm, back.border_color,
            back.border_radius_mm, back.border_style) == (
        True, 1.0, "#0000ff", 4.0, "double")
    pw, ph = c.page_size_mm()
    for style in ("single", "double", "dashed"):
        c.border_style = style
        img = QImage(int(pw * 2), int(ph * 2), QImage.Format_ARGB32)
        img.fill(0xFFFFFFFF)
        p = QPainter(img)
        p.scale(2, 2)
        paint_sheet_border_mm(p, c)
        p.end()
        # the top edge of the margin rectangle carries the border
        mid_x = int(pw)
        col = [_rgb(img, mid_x, int(10 * 2) + d) for d in (-2, -1, 0, 1, 2)]
        assert 0x0000FF in col, style
        # rounded corners leave the exact corner pixel white
        assert _rgb(img, int(10 * 2), int(10 * 2)) == 0xFFFFFF
    c.border = False
    assert "border" not in c.to_dict()


def test_sheet_border_stays_above_a_frame_that_reaches_the_margin(monkeypatch):
    from views.composer import ComposerWindow, _SheetBorderCanvasItem
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    try:
        c = comp.comp
        c.border, c.border_mm, c.border_color = True, 1.0, "#0000ff"
        pw, ph = c.page_size_mm()
        frame = c.frames[0]
        frame.x_mm, frame.y_mm = c.margin_mm - 5, c.margin_mm - 5
        frame.w_mm, frame.h_mm = pw - 2 * c.margin_mm + 10, 60.0
        fill = QImage(4, 4, QImage.Format_RGB32)
        fill.fill(0xFFDDDDDD)
        comp.render_cache[id(frame)] = fill
        img = QImage(int(pw * 2), int(ph * 2), QImage.Format_ARGB32)
        img.fill(0xFFFFFFFF)
        p = QPainter(img)
        p.scale(2, 2)
        comp._paint_sheet(p, c)
        p.end()
        col = [_rgb(img, int(pw), int(c.margin_mm * 2) + d)
               for d in (-2, -1, 0, 1, 2)]
        assert 0x0000FF in col                       # not hidden by the frame
        comp._rebuild_canvas()
        border = next(it for it in comp.canvas.items()
                      if isinstance(it, _SheetBorderCanvasItem))
        assert border.zValue() > max(it.zValue() for it in comp.canvas.items()
                                     if it is not border)
        assert border.acceptedMouseButtons() == Qt.NoButton
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_frame_scale_label_follows_the_scale_and_its_position():
    from views.composer import paint_frame_mm
    frame = MarcoVista(w_mm=80.0, h_mm=40.0, style="sombreado", scale_n=40.0,
                       show_scale=True)
    assert frame.scale_label() == "ESC. 1:40"
    frame.scale_text = "Escala {n}"
    frame.scale_n = 75.0
    assert frame.scale_label() == "Escala 75"
    fill = QImage(4, 4, QImage.Format_RGB32)
    fill.fill(0xFF3366AA)
    for pos, probe in (("under-right", (70.0, 43.0)), ("under-left", (5.0, 43.0)),
                       ("inside-br", (74.0, 37.0)), ("inside-bl", (6.0, 37.0))):
        frame.scale_pos = pos
        img = QImage(240, 140, QImage.Format_ARGB32)
        img.fill(0xFFFFFFFF)
        p = QPainter(img)
        p.scale(2, 2)
        p.translate(10, 10)
        paint_frame_mm(p, frame, fill)
        p.end()
        x, y = probe
        window = [_rgb(img, int((10 + x) * 2) + dx, int((10 + y) * 2) + dy)
                  for dx in range(-8, 9, 2) for dy in range(-6, 7, 2)]
        # something dark (ink) or white (the inside box) sits where the
        # label goes — never only the frame's blue fill / bare page
        assert any(px not in (0x3366AA, 0xFFFFFF) for px in window) or (
            pos.startswith("inside") and 0xFFFFFF in window), pos
    c = Composicion()
    c.frames.append(frame)
    # Loading turns the legacy frame flag into a bound text block (below).
    loaded = Composicion.from_dict(c.to_dict())
    assert loaded.frames[0].show_scale is False
    assert len(loaded.texts) == 1


def test_legacy_fixed_scale_labels_load_as_bound_texts():
    """Documents saved before the movable scale label carried it as a frame
    flag the panel no longer exposes — the user had no way to switch it
    off. Loading converts each one into a text block bound to its frame."""
    from core.composition import PT_TO_MM, expand_fields, set_field_context
    c = Composicion()
    for i, pos in enumerate(("under-right", "under-left", "inside-br",
                             "inside-bl")):
        c.frames.append(MarcoVista(x_mm=20.0, y_mm=20.0 + i * 60.0, w_mm=80.0,
                                   h_mm=40.0, scale_n=40.0, show_scale=True,
                                   scale_pos=pos, scale_mm=3.0))
    c.frames.append(MarcoVista(x_mm=120.0, y_mm=20.0, w_mm=50.0, h_mm=30.0,
                               scale_n=100.0, show_scale=False))
    loaded = Composicion.from_dict(c.to_dict())
    assert all(f.show_scale is False for f in loaded.frames)
    assert len(loaded.texts) == 4                # the plain frame gets none
    by_pos = dict(zip(("under-right", "under-left", "inside-br", "inside-bl"),
                      loaded.texts))
    for f, (pos, t) in zip(loaded.frames, by_pos.items()):
        assert f.uid and t.frame_uid == f.uid and t.follow
        assert t.text == "ESC. {escala}" and t.bold
        assert abs(t.size_pt - 3.0 / PT_TO_MM) < 1e-6
        if pos.startswith("under"):
            assert t.y_mm > f.y_mm + f.h_mm and not t.bg_color
        else:
            assert f.y_mm < t.y_mm < f.y_mm + f.h_mm and t.bg_color
        assert t.align == ("left" if pos in ("under-left", "inside-bl") else "right")
    ur = by_pos["under-right"]
    assert ur.x_mm + ur.w_mm == loaded.frames[0].x_mm + loaded.frames[0].w_mm
    set_field_context(comp=loaded)
    assert expand_fields(ur.text, ur.frame_uid) == "ESC. 1:40"
    # Custom templates keep their wording; the number follows the frame.
    c2 = Composicion()
    c2.frames.append(MarcoVista(scale_n=75.0, show_scale=True,
                                scale_text="Escala {n}"))
    t2 = Composicion.from_dict(c2.to_dict()).texts[0]
    assert t2.text == "Escala {escala}"
    set_field_context(comp=Composicion.from_dict(c2.to_dict()))
    # Round trip: an already-migrated sheet loads unchanged.
    again = Composicion.from_dict(loaded.to_dict())
    assert len(again.texts) == 4
