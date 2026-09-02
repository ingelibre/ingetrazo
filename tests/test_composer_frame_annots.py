# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet cotas pick by their drawn lines, Esc drops the selection, and a
frame can carry the model's own dimensions and leader texts."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QVector3D

from core.composition import CotaItem, Composicion, MarcoVista


def _composer(monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    return win, comp


def _close(win, comp):
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def test_small_cota_inside_a_big_oblique_one_gets_the_click(monkeypatch):
    from views.composer import CotaCanvasItem
    win, comp = _composer(monkeypatch)
    try:
        big = CotaItem(x_mm=119.4, y_mm=154.1, dx_mm=-14.8, dy_mm=97.2,
                       sep_mm=-84.6, z=9.0)                # Marco's 4.00 m
        small = CotaItem(x_mm=115.4, y_mm=190.2, dx_mm=-4.0, dy_mm=24.0,
                         sep_mm=-20.4, z=8.0)              # his 0.97 m
        comp.comp.cotas += [big, small]
        comp._rebuild_canvas()
        by_id = {id(it.model): it for it in comp.canvas.items()
                 if isinstance(it, CotaCanvasItem)}
        big_item, small_item = by_id[id(big)], by_id[id(small)]
        # The small cota's dimension line midpoint, in page mm.
        nx, ny = small.normal()
        mid = QPointF(small.x_mm + small.dx_mm / 2 + nx * small.sep_mm,
                      small.y_mm + small.dy_mm / 2 + ny * small.sep_mm)
        assert big_item.boundingRect().translated(
            big_item.pos()).contains(mid)             # the box covers it…
        hit = [it for it in comp.canvas.items(mid)
               if isinstance(it, CotaCanvasItem)]
        assert hit and hit[0] is small_item           # …the shape does not
        assert big_item not in hit
        # The big one is still picked on its own line.
        nx, ny = big.normal()
        bmid = QPointF(big.x_mm + big.dx_mm / 2 + nx * big.sep_mm,
                       big.y_mm + big.dy_mm / 2 + ny * big.sep_mm)
        assert big_item in comp.canvas.items(bmid)
    finally:
        _close(win, comp)


def test_escape_drops_the_selection(monkeypatch):
    from views.composer import FrameItem
    win, comp = _composer(monkeypatch)
    try:
        comp._rebuild_canvas()
        item = next(it for it in comp.canvas.items() if isinstance(it, FrameItem))
        item.setSelected(True)
        assert comp.canvas.selectedItems()
        ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        comp._view.keyPressEvent(ev)
        assert comp.canvas.selectedItems() == []
    finally:
        _close(win, comp)


def test_frame_annotations_flag_and_render_paths(monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    assert MarcoVista().annotations is False              # opt-in
    c = Composicion()
    c.frames.append(MarcoVista(annotations=True))
    assert Composicion.from_dict(c.to_dict()).frames[-1].annotations is True

    win = MainWindow()
    comp = ComposerWindow(win)
    try:
        calls = []
        vp = win.viewport

        def fake_render(w, h, overlays=True, annotations_only=False):
            calls.append((overlays, annotations_only))
            return None
        monkeypatch.setattr(vp, "render_image", fake_render)
        frame = comp.comp.frames[0]
        frame.style = "sombreado"
        frame.annotations = True
        comp.render_frame(frame)
        assert isinstance(comp.annot_cache.get(id(frame)), list)
        frame.annotations = False
        comp.render_frame(frame)
        assert comp.annot_cache.get(id(frame)) == []
        # Never baked into the pixels: the overlay draws them on paper.
        assert calls == [(False, False), (False, False)]
    finally:
        _close(win, comp)


def test_vector_frame_projects_dimensions_and_texts(monkeypatch):
    from core.dimension import Dimension
    from core.textlabel import TextLabel
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    win = MainWindow()
    comp = ComposerWindow(win)
    try:
        scene = win.viewport.scene
        scene.mesh.add_face([QVector3D(-2, 0, 0), QVector3D(2, 0, 0),
                             QVector3D(2, 0, 3), QVector3D(-2, 0, 3)])
        scene.dimensions.append(Dimension(QVector3D(-2, 0, 0),
                                          QVector3D(2, 0, 0),
                                          QVector3D(0, 0, -0.5)))
        scene.text_labels.append(TextLabel(QVector3D(0, 0, 3),
                                           QVector3D(1, 0, 0.5), "Muro"))
        scene.version += 1
        frame = comp.comp.frames[0]
        frame.view_key, frame.style = "std:front", "vectorial"
        frame.w_mm, frame.h_mm, frame.scale_n = 200.0, 100.0, 50.0
        frame.annotations = True
        frame.annot_text_mm = 3.5
        annots = comp.compute_annotations(frame)
        assert all(a[5] == 3.5 for a in annots if a[0] == "text")
        kinds = [a[0] for a in annots]
        assert kinds.count("text") == 2                 # value + label
        assert kinds.count("line") >= 6                 # ext + dim + ticks
        value = next(a for a in annots if a[0] == "text" and "m" in a[4])
        assert value[4] == "4.00 m"
        # Everything lands inside the frame (mm, frame-local).
        for a in annots:
            xs = (a[1], a[3]) if a[0] == "line" else (a[1],)
            assert all(-5 <= x <= frame.w_mm + 5 for x in xs)
        # A frame that opts out carries nothing.
        frame.annotations = False
        comp.render_frame(frame)
        assert comp.annot_cache.get(id(frame)) == []
    finally:
        _close(win, comp)


def test_raster_frame_with_an_image_never_shows_the_placeholder(monkeypatch):
    """The annotation overlay must not steal the placeholder's else-branch:
    a rendered raster frame paints its image, with or without annotations
    (the whole sheet went blank, Marco 2026-09-02)."""
    from PySide6.QtGui import QImage, QPainter
    from views.composer import paint_frame_mm
    seen = []
    monkeypatch.setattr("views.composer._draw_text_mm",
                        lambda *a, **k: seen.append(a[2]))
    frame = MarcoVista(w_mm=100.0, h_mm=50.0, style="sombreado")
    img = QImage(10, 5, QImage.Format_ARGB32)
    img.fill(0xFF336699)
    out = QImage(200, 100, QImage.Format_ARGB32)
    out.fill(0xFFFFFFFF)
    p = QPainter(out)
    p.scale(2, 2)
    paint_frame_mm(p, frame, img, annots=None)
    paint_frame_mm(p, frame, img, annots=[])
    p.end()
    assert not any("render" in str(t) for t in seen)
    assert out.pixel(100, 50) & 0xFFFFFF == 0x336699
    p = QPainter(out)
    paint_frame_mm(p, frame, None, annots=None)
    p.end()
    assert any("render" in str(t) for t in seen)      # no image: placeholder


def test_raster_frame_image_is_made_opaque(monkeypatch):
    """A translucent water face leaves alpha < 1 under bright texels in the
    FBO read-back (labelled premultiplied): invalid data that smooth
    scaling on the canvas turns into red/yellow blotches. The frame keeps
    an opaque copy."""
    from PySide6.QtGui import QImage
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    win = MainWindow()
    comp = ComposerWindow(win)
    try:
        bad = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
        bad.fill(0xCFFFFFFF)                    # alpha 207 under white
        monkeypatch.setattr(win.viewport, "render_image",
                            lambda *a, **k: bad)
        frame = comp.comp.frames[0]
        frame.style = "sombreado"
        comp.render_frame(frame)
        img = comp.render_cache[id(frame)]
        assert not img.hasAlphaChannel()
        assert img.pixel(3, 3) & 0xFFFFFF == 0xFFFFFF
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
