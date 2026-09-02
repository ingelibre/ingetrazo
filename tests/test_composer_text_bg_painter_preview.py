# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Text blocks with a background, the one-tool format painter, and the
print preview's painter."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QImage, QKeyEvent, QPainter

from core.composition import Composicion, CotaItem, TextoItem


def test_text_background_paints_behind_and_round_trips():
    from views.composer import paint_text_mm
    t = TextoItem(w_mm=40.0, text="Pileta", bg_color="#ffe08a")
    img = QImage(200, 100, QImage.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    p = QPainter(img)
    p.scale(2, 2)
    p.translate(10, 10)
    paint_text_mm(p, t)
    p.end()
    # a pixel inside the block but off the glyphs carries the background
    assert img.pixel(int((10 + 38) * 2), int((10 + 1) * 2)) & 0xFFFFFF == 0xFFE08A
    c = Composicion()
    c.texts.append(t)
    assert Composicion.from_dict(c.to_dict()).texts[0].bg_color == "#ffe08a"
    plain = TextoItem(w_mm=40.0, text="Pileta")
    img.fill(0xFFFFFFFF)
    p = QPainter(img)
    p.scale(2, 2)
    p.translate(10, 10)
    paint_text_mm(p, plain)
    p.end()
    assert img.pixel(int((10 + 38) * 2), int((10 + 1) * 2)) & 0xFFFFFF == 0xFFFFFF


def test_format_painter_copies_on_first_click_and_pastes_after(monkeypatch):
    from views.composer import ComposerWindow, CotaCanvasItem, TextItem
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    try:
        src = CotaItem(x_mm=20, y_mm=20, dx_mm=50, text_mm=4.5, color="#aa0000",
                       text_pos="below")
        dst = CotaItem(x_mm=20, y_mm=60, dx_mm=50)
        txt = TextoItem(x_mm=20, y_mm=90, text="hola")
        comp.comp.cotas += [src, dst]
        comp.comp.texts.append(txt)
        comp._rebuild_canvas()
        by_id = {id(it.model): it for it in comp.canvas.items()
                 if isinstance(it, (CotaCanvasItem, TextItem))}
        comp._set_tool_mode("estilo")
        assert comp.tool_mode == "estilo" and comp._painter_armed
        comp.format_painter_click(by_id[id(src)])         # 1st click: copy
        assert not comp._painter_armed
        assert comp._style_clip[0] is CotaItem
        comp.format_painter_click(by_id[id(txt)])         # other kind: no-op
        assert txt.color == "#1e242c"
        comp.format_painter_click(by_id[id(dst)])         # paste
        assert (dst.text_mm, dst.color, dst.text_pos) == (4.5, "#aa0000", "below")
        assert dst.y_mm == 60                             # geometry untouched
        # Esc leaves the tool.
        comp._view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape,
                                           Qt.NoModifier))
        assert comp.tool_mode == "select"
        assert [m for m, *_ in ComposerWindow.TOOLS].count("estilo") == 1
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_print_preview_painter_produces_a_page(monkeypatch, tmp_path):
    from PySide6.QtPrintSupport import QPrinter
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    try:
        comp.comp.texts.append(TextoItem(x_mm=30, y_mm=30, text="Prueba",
                                         bg_color="#eeeeee"))
        printer = comp._printer_for_sheet()
        out = tmp_path / "lamina.pdf"
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(out))
        comp._paint_to_printer(printer)
        assert out.exists() and out.stat().st_size > 1000
        assert printer.pageLayout().orientation().name.lower().startswith(
            "landscape" if comp.comp.landscape else "portrait")
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
