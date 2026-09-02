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
