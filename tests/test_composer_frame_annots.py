# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet cotas pick by their drawn lines, Esc drops the selection, and a
frame can carry the model's own dimensions and leader texts."""
from __future__ import annotations

import pytest

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QKeyEvent, QVector3D

from core.composition import (CotaItem, Composicion, MarcoVista,
                              mm_to_px)


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
        # ext + dim lines + the two ends: arrows by default, ticks (two
        # more lines) when the document says so
        assert kinds.count("line") >= 4 and kinds.count("arrow") == 2
        scene.dimension_style["ends"] = "tick"
        kinds = [a[0] for a in comp.compute_annotations(frame)]
        assert kinds.count("line") >= 6 and kinds.count("arrow") == 0
        scene.dimension_style["ends"] = "arrow"
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
    img = QImage(mm_to_px(frame.w_mm), mm_to_px(frame.h_mm),
                 QImage.Format_ARGB32)
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


def test_a_grown_raster_frame_keeps_the_picture_undistorted():
    """#80: the render is drawn at the size it was rendered for and merely
    clipped to the frame, so a frame that grows shows paper where the
    picture does not reach instead of stretching the drawing."""
    from PySide6.QtGui import QImage, QPainter
    from views.composer import paint_frame_mm
    frame = MarcoVista(w_mm=100.0, h_mm=50.0, style="sombreado")
    img = QImage(mm_to_px(100.0), mm_to_px(50.0), QImage.Format_ARGB32)
    img.fill(0xFF336699)                    # the picture as it was rendered
    frame.w_mm = 200.0                      # the frame grew to twice as wide
    out = QImage(400, 100, QImage.Format_ARGB32)
    out.fill(0xFFFFFFFF)
    p = QPainter(out)
    p.scale(2, 2)
    paint_frame_mm(p, frame, img, annots=None)
    p.end()
    assert out.pixel(50, 50) & 0xFFFFFF == 0x336699     # inside the picture
    assert out.pixel(300, 50) & 0xFFFFFF == 0xFFFFFF    # grown part: paper


@pytest.mark.parametrize("image_format", [QImage.Format_ARGB32_Premultiplied,
                                        QImage.Format_RGBA8888_Premultiplied,
                                        QImage.Format_ARGB32])
@pytest.mark.parametrize("rgb", [0xFFFFFF, 0x336699, 0xFFCC33])
def test_raster_frame_image_is_made_opaque(monkeypatch, image_format, rgb):
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
        bad = QImage(8, 8, QImage.Format_ARGB32)
        bad.fill(0xCF000000 | rgb)
        if image_format == QImage.Format_RGBA8888_Premultiplied:
            bad = bad.convertToFormat(QImage.Format_RGBA8888)
        bad.reinterpretAsFormat(image_format)  # simulate the FBO format label
        monkeypatch.setattr(win.viewport, "render_image",
                            lambda *a, **k: bad)
        frame = comp.comp.frames[0]
        frame.style = "sombreado"
        comp.render_frame(frame)
        img = comp.render_cache[id(frame)]
        assert not img.hasAlphaChannel()
        assert img.pixel(3, 3) & 0xFFFFFF == rgb
        assert bad.hasAlphaChannel()          # cached conversion owns its copy
        assert bad.format() == image_format
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


@pytest.mark.parametrize("fail", [False, True])
def test_saved_scene_restores_complete_live_state_even_on_error(monkeypatch, fail):
    from types import SimpleNamespace
    from core.group import Group
    from core.layers import Layer
    from core.saved_views import SavedView, shown_state
    from core.section import SectionPlane
    from core.style import Style

    win, comp = _composer(monkeypatch)
    try:
        vp = win.viewport
        scene, cam = vp.scene, vp.camera
        parent, child = Group(name="Envelope"), Group(name="Partition")
        parent.children.append(child)
        scene.groups.append(parent)
        parent.hidden, child.hidden = True, False
        scene.layers.append(Layer("Construction", visible=False))
        scene.tile_layer = SimpleNamespace(visible=True)
        scene.terrain = SimpleNamespace(visible=False)
        scene.photo_mesh = SimpleNamespace(visible=True)
        plane = SectionPlane(QVector3D(), QVector3D(0, 0, 1), active=True)
        scene.section_planes.append(plane)
        scene.show_section_planes = False
        scene.show_section_cuts = True
        scene.show_hidden_objects, scene.show_hidden_geometry = True, False
        scene.display_style = Style()
        scene.shadows.enabled = True
        cam.two_point = True
        before = SavedView.capture("Before", scene, cam).to_dict()
        shown = shown_state(scene)
        camera_extra = (cam.aspect, QVector3D(cam.up))
        style = scene.display_style
        shadows = scene.shadows
        version = scene.version
        geom, circles = object(), object()
        comp._geom_cache, comp._circles_cache = geom, circles
        saved = SavedView(
            "Detail", target=(5, 6, 7), two_point=False,
            hidden_objects=[child.uid], hidden_layers=[],
            hidden_shown={"objects": False, "geometry": True},
            section={"active": None, "planes_shown": True, "cuts_shown": False},
            style=Style(face_mode="wireframe").to_dict(),
            georef={"map": False, "terrain": True, "survey": False},
            shadows={"enabled": False})
        scene.saved_views.append(saved)
        frame = MarcoVista(view_key="scene:Detail")

        def inspect_detail():
            assert not parent.hidden and child.hidden
            assert not cam.two_point
            assert scene.show_hidden_objects is False
            assert scene.show_hidden_geometry is True
            assert scene.layer("Construction").visible
            assert scene.active_section() is None
            assert scene.display_style.face_mode == "wireframe"
            assert not scene.tile_layer.visible and scene.terrain.visible
            assert not scene.photo_mesh.visible
            assert comp._geom_cache is None and comp._circles_cache is None
            if fail:
                raise RuntimeError("render failed")
            return "rendered"

        if fail:
            with pytest.raises(RuntimeError, match="render failed"):
                comp._with_frame_camera(frame, inspect_detail)
        else:
            assert comp._with_frame_camera(frame, inspect_detail) == "rendered"
        assert SavedView.capture("Before", scene, cam).to_dict() == before
        assert shown_state(scene) == shown
        assert (cam.aspect, cam.up) == camera_extra
        assert scene.display_style is style and scene.shadows is shadows
        assert scene.version == version
        assert comp._geom_cache is geom and comp._circles_cache is circles
        assert comp._with_frame_camera(
            MarcoVista(view_key="__current__"), lambda: shown_state(scene)) == shown
    finally:
        _close(win, comp)
