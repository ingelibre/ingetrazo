# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Ambient occlusion of the 3D view (#954): off, the picture is the one it
always was; on, the foot of a box on a floor darkens and the open floor
does not; a flat face seen obliquely gets no vertical bands (#989); the
foliage mark rides the recorded instanced passes (the native replay gained
glStencilFunc for it, in the same order on both sides).

The rendering cases need a GL context; skipped where there is none."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QImage, QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from views import ambient_occlusion as ao  # noqa: E402
import views.viewport as viewport  # noqa: E402


def test_it_is_off_unless_asked(monkeypatch):
    monkeypatch.delenv("INGETRAZO_AO", raising=False)
    assert ao.settings_from_env() is None
    monkeypatch.setenv("INGETRAZO_AO", "0")
    assert ao.settings_from_env() is None


def test_the_settings_are_kept_in_range(monkeypatch):
    monkeypatch.setenv("INGETRAZO_AO", "1")
    monkeypatch.setenv("INGETRAZO_AO_RADIUS", "-3")
    monkeypatch.setenv("INGETRAZO_AO_SAMPLES", "500")
    monkeypatch.setenv("INGETRAZO_AO_INTENSITY", "nada")
    s = ao.settings_from_env()
    assert s["radius"] > 0 and s["samples"] == 64 and s["intensity"] == 1.0


def test_the_tape_records_the_foliage_mark_for_the_native_replay():
    calls = []
    tape = viewport._GlTape()
    tape.stencil_func(lambda *a: calls.append(a), viewport.GL_ALWAYS,
                      viewport.AO_FOLIAGE_BIT, 0xFF)
    assert calls == [(viewport.GL_ALWAYS, viewport.AO_FOLIAGE_BIT, 0xFF)]
    assert tape.ops[-1][:4] == (tape.STENCIL, viewport.GL_ALWAYS,
                                viewport.AO_FOLIAGE_BIT, 0xFF)
    # GlReplay takes the entry points in opcode order.
    assert viewport._TAPE_FUNCS[tape.STENCIL] == b"glStencilFunc"
    assert len(viewport._TAPE_FUNCS) == tape.STENCIL + 1


def _lum(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    buf = np.frombuffer(img.constBits(), np.uint8)
    px = buf.reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4]
    return px.reshape(img.height(), img.width(), 4)[..., :3].astype(
        np.float32).mean(axis=2)


@pytest.fixture
def box_on_floor():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.show()
        _app.processEvents()
        vp = win.viewport
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        V = QVector3D
        scene = vp.scene
        scene.mesh.add_face([V(-10, -10, 0), V(10, -10, 0), V(10, 10, 0),
                             V(-10, 10, 0)])
        p = [V(-1, -1, 0), V(1, -1, 0), V(1, 1, 0), V(-1, 1, 0),
             V(-1, -1, 2), V(1, -1, 2), V(1, 1, 2), V(-1, 1, 2)]
        for idx in ((4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                    (2, 3, 7, 6), (3, 0, 4, 7)):
            scene.mesh.add_face([p[i] for i in idx])
        scene.version += 1
        vp.camera.set_view("iso")
        vp.camera.fit_to(V(-4, -4, 0), V(4, 4, 2))
        for _ in range(5):
            _app.processEvents()
        yield vp
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


@pytest.fixture
def step_block():
    """The report's step (#989): a slab with a wall set back on it. Seen
    from an oblique camera, the wall's left face is a flat surface whose AO
    used to come out in vertical bands."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.resize(900, 700)
        win.show()
        _app.processEvents()
        vp = win.viewport
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        V = QVector3D
        scene = vp.scene

        def box(x0, x1, y0, y1, z0, z1):
            p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0),
                 V(x0, y1, z0), V(x0, y0, z1), V(x1, y0, z1),
                 V(x1, y1, z1), V(x0, y1, z1)]
            for idx in ((4, 5, 6, 7), (0, 3, 2, 1), (0, 1, 5, 4),
                        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
                scene.mesh.add_face([p[i] for i in idx])

        box(-3, 3, -2, 2, 0, 2)
        box(-3, 0, 0, 2, 2, 5)
        scene.version += 1
        vp.camera.set_view("iso")
        vp.camera.yaw = math.radians(-135.0)
        vp.camera.pitch = math.radians(20.0)
        vp.camera.fit_to(V(-3.2, -2.2, 0), V(3.2, 2.2, 5.2))
        for _ in range(5):
            _app.processEvents()
        # The export is 900x700; give the camera that aspect so the face's
        # projected corners below land where the pixels do.
        vp.camera.set_aspect(900, 700)
        yield vp
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def _render(vp, monkeypatch, on: str) -> np.ndarray:
    monkeypatch.setenv("INGETRAZO_AO", on)
    monkeypatch.setenv("INGETRAZO_AO_RADIUS", "0.5")
    return _lum(vp.render_image(400, 300, overlays=False))


def _render_at(vp, monkeypatch, on: str, w: int, h: int) -> np.ndarray:
    monkeypatch.setenv("INGETRAZO_AO", on)
    monkeypatch.setenv("INGETRAZO_AO_RADIUS", "0.5")
    return _lum(vp.render_image(w, h, overlays=False))


def _pixel(vp, p: QVector3D, w: int, h: int) -> tuple[float, float]:
    """Where a world point lands in the exported image, in pixels."""
    m = vp.camera.projection_matrix() * vp.camera.view_matrix()
    q = m.map(p)
    return ((q.x() * 0.5 + 0.5) * w, (1.0 - (q.y() * 0.5 + 0.5)) * h)


def test_the_foot_of_a_box_darkens_and_the_open_floor_does_not(
        box_on_floor, monkeypatch):
    vp = box_on_floor
    off = _render(vp, monkeypatch, "0")
    on = _render(vp, monkeypatch, "1")
    if getattr(vp, "_ao", None) is not None and vp._ao.broken:
        pytest.skip(f"this driver refuses the pass: {vp._ao.broken}")
    darker = off - on
    assert (darker > 8).mean() > 0.002          # the corner band shows
    assert (on > off + 1).mean() < 0.001        # it never lightens
    assert (np.abs(darker) < 1).mean() > 0.6    # most of the picture is as it was
    # Off again: the very same picture as before it was ever on.
    assert np.array_equal(_render(vp, monkeypatch, "0"), off)


def test_wireframe_has_none(box_on_floor, monkeypatch):
    vp = box_on_floor
    vp.plano_style = "lineas"                   # the wireframe face mode
    assert np.array_equal(_render(vp, monkeypatch, "0"),
                          _render(vp, monkeypatch, "1"))


def test_a_flat_face_seen_obliquely_gets_no_vertical_bands(
        step_block, monkeypatch):
    """#989: the half-size AO pass read the full-size depth at texel corners,
    so a flat face's normal wobbled and the face self-occluded in bands."""
    vp = step_block
    off = _render_at(vp, monkeypatch, "0", 900, 700)
    on = _render_at(vp, monkeypatch, "1", 900, 700)
    if getattr(vp, "_ao", None) is not None and vp._ao.broken:
        pytest.skip(f"this driver refuses the pass: {vp._ao.broken}")
    darker = off - on
    assert darker.max() > 5.0                  # the pass did something
    # The upper wall's left face (x = -3): flat, vertical, seen obliquely.
    V = QVector3D
    corners = [V(-3, 0, 2), V(-3, 2, 2), V(-3, 2, 5), V(-3, 0, 5)]
    pts = np.array([_pixel(vp, c, 900, 700) for c in corners])
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    # Inset well clear of the face's edges and of the corner darkening.
    ix = (x1 - x0) * 0.28
    iy = (y1 - y0) * 0.22
    region = darker[int(y0 + iy):int(y1 - iy),
                    int(x0 + ix):int(x1 - ix)]
    assert region.size > 1000
    # One flat face has ONE occlusion value; the bug swung it ~28 levels.
    assert np.ptp(region) < 4.0, (region.min(), region.max(), region.mean())


# ---- The style's switch (Styles panel) -------------------------------------

def test_the_style_carries_it_and_every_preset_has_it_off():
    from core.style import BUILTIN_STYLES, Style
    assert all(not p.ambient_occlusion for p in BUILTIN_STYLES)
    s = Style(ambient_occlusion=True, ao_distance=1.25, ao_intensity=1.5)
    back = Style.from_dict(s.to_dict())
    assert (back.ambient_occlusion, back.ao_distance, back.ao_intensity) \
        == (True, 1.25, 1.5)


def test_a_file_from_before_reads_it_off_and_bad_values_are_kept_in_range():
    from core.style import AO_DISTANCE_RANGE, Style
    old = Style().to_dict()
    for k in ("ambient_occlusion", "ao_distance", "ao_intensity"):
        old.pop(k)
    assert not Style.from_dict(old).ambient_occlusion
    odd = Style.from_dict({"ambient_occlusion": True, "ao_distance": 1e9,
                           "ao_intensity": "mucho"})
    assert odd.ao_distance == AO_DISTANCE_RANGE[1] and odd.ao_intensity == 1.0


def test_the_frame_follows_the_style_unless_the_environment_forces_it(
        monkeypatch):
    from core.style import Style
    monkeypatch.delenv("INGETRAZO_AO", raising=False)
    assert ao.settings_for(Style()) is None
    got = ao.settings_for(Style(ambient_occlusion=True, ao_distance=2.0,
                                ao_intensity=0.5))
    assert got["radius"] == 2.0 and got["intensity"] == 0.5
    monkeypatch.setenv("INGETRAZO_AO", "0")
    assert ao.settings_for(Style(ambient_occlusion=True)) is None


def test_the_panel_switch_edits_the_active_style():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        panel = win.styles_panel
        style = win.viewport.scene.display_style
        panel.refresh()
        assert not panel._ao.isChecked() and not panel._ao_dist.isEnabled()
        panel._ao.setChecked(True)
        assert style.ambient_occlusion and panel._ao_dist.isEnabled()
        panel._ao_int.setValue(15)
        panel._ao_dist.setValue(2.0)
        assert style.ao_intensity == 1.5 and style.ao_distance == 2.0
        panel._ao.setChecked(False)
        assert not style.ambient_occlusion and not panel._ao_int.isEnabled()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- Stable (0.5.11): silhouettes, sky and flat faces ------------------------

def test_the_sky_round_a_silhouette_is_never_darkened(monkeypatch):
    """The occlusion is worked out at half size. Stretched back without
    looking at depth, the dark value of a frame's corner leaked onto the
    sky next to it: a dark, toothed halo round every slat and column (the
    Windows round of 0.5.10.1). Every pixel that shows sky with nothing in
    the model must show the very same sky with the occlusion on."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.show()
        _app.processEvents()
        vp = win.viewport
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        V = QVector3D
        vp.camera.set_view("iso")
        vp.camera.fit_to(V(-3, -3, 0), V(3, 3, 3))
        for _ in range(3):
            _app.processEvents()
        empty = _render(vp, monkeypatch, "0")
        # A frame of three posts and a lintel: inner corners, against sky.
        mesh = vp.scene.mesh

        def box(x0, y0, z0, x1, y1, z1):
            p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
                 V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
            for idx in ((3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4),
                        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
                mesh.add_face([p[i] for i in idx])

        for x in (-2.0, 0.0, 2.0):
            box(x - 0.15, -0.15, 0, x + 0.15, 0.15, 2.4)
        box(-2.3, -0.2, 2.4, 2.3, 0.2, 2.7)
        vp.scene.version += 1
        off = _render(vp, monkeypatch, "0")
        on = _render(vp, monkeypatch, "1")
        if getattr(vp, "_ao", None) is not None and vp._ao.broken:
            pytest.skip(f"this driver refuses the pass: {vp._ao.broken}")
        sky = empty == off
        assert sky.mean() > 0.3
        assert (off - on > 8).mean() > 0.0005      # the corners still darken
        assert np.array_equal(on[sky], off[sky])
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_an_error_left_pending_by_someone_else_does_not_switch_it_off(
        box_on_floor, monkeypatch):
    """Opening a big file left a GL error pending from its texture uploads;
    the pass read it as its own depth resolve failing and stayed off for
    the whole session, with the box ticked (Marco, playa Yanque)."""
    vp = box_on_floor
    off = _render(vp, monkeypatch, "0")
    real = vp._apply_ambient_occlusion

    def after_a_stray_error(*args, **kwargs):
        vp._gl.glEnable(0x7FFF)                 # GL_INVALID_ENUM, left pending
        return real(*args, **kwargs)

    monkeypatch.setattr(vp, "_apply_ambient_occlusion", after_a_stray_error)
    on = _render(vp, monkeypatch, "1")
    if vp._ao.broken and vp._ao.broken != "depth resolve refused":
        pytest.skip(f"this driver refuses the pass: {vp._ao.broken}")
    assert not vp._ao.broken
    assert ((off - on) > 8).mean() > 0.002      # it did darken the corner
