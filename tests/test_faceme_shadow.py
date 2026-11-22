# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The shadow of a face-me figure (Marco, 21-11, with the engineer that
opens every new document and the sun on).

1. A model holding only the figure threw no shadow until something was
   drawn: the sun's map is fitted round the model's box, and the box
   leaves the figures out (they are drawn per frame, not from their mesh).
2. Orbiting, the shadow did not start at the feet: the figure was cast
   turned toward the sun round the picture's middle, while on screen it
   faces the camera and the cutout's feet stand off that middle — the
   shadow met one shoe at best. A figure beside a small drawing also fell
   partly outside the map, and the map fitted to the settled view (#958)
   cut it differently at each camera.

Expected behaviour (checked frame by frame): the shadow is the figure AS
DRAWN — facing the camera, turned round its feet — so both feet of the
shadow meet both shoes at any orbit and the shadow stretches from the
soles away from the sun (a thin line when the camera sees the figure
edge-on from the sun's side). The model's own map stays camera-
independent and is not redrawn while orbiting: the figures have a small
map of their own.

The GL checks need a real context (run them with QT_QPA_PLATFORM=xcb);
offscreen has none and skips them."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QColor, QImage, QVector3D, QVector4D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])
V = QVector3D
# Off the drawing axes: their coloured lines would cross the shadow.
FEET = V(0.37, 0.29, 0.0)


def _wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _cutout(path, feet_right: bool):
    """A 100 × 200 cutout, opaque everywhere — or only on its right half
    (the person off the picture's middle: feet at u = 0.75)."""
    img = QImage(100, 200, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0) if feet_right else QColor(90, 60, 40, 255))
    if feet_right:
        for y in range(200):
            for x in range(50, 100):
                img.setPixelColor(x, y, QColor(90, 60, 40, 255))
    img.save(str(path))
    return str(path)


@pytest.fixture
def view(tmp_path):
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.resize(900, 700)
        win.show()
        _app.processEvents()
        vp = win.viewport
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        vp.scene.groups[:] = []           # the new document's own figure
        vp.scene.version += 1
        sh = vp.scene.shadows
        sh.enabled = True
        sh.month, sh.day = 3, 21
        vp._tmp = tmp_path
        yield vp
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def _add_figure(vp, feet_right=False, height=2.0):
    from core.group import make_billboard_group
    path = _cutout(vp._tmp / f"fig{int(feet_right)}.png", feet_right)
    g = make_billboard_group(path, height, "figure", 0.5, position=FEET)
    vp.scene.groups.append(g)
    vp.scene.version += 1
    return g


def _frame(vp, settle=False):
    """Draw a frame — with the whole-model map, or (``settle``) after the
    view has stayed put, with the map fitted to it (#958)."""
    if not settle:
        vp._shadow_fit = None
        vp._settle_shadow_fit = lambda *a: None      # instance override
    try:
        vp.update()
        _wait(120)
        if settle:
            _wait(vp.SHADOW_SETTLE_MS + 300)
            vp.update()
            _wait(150)
    finally:
        if not settle:
            del vp._settle_shadow_fit


def _orbit(vp, yaw_deg, pitch_deg=35.0, dist=6.0,
           target=FEET + V(0, 0, 0.8)):
    cam = vp.camera
    cam.perspective = True
    cam.target = target
    cam.distance = dist
    cam.yaw = math.radians(yaw_deg)
    cam.pitch = math.radians(pitch_deg)


def _map_footprint(vp, xs, ys, z=-0.005, figures=True):
    """The ground cells the figures' map (or the model's) just drawn with
    puts in shadow — read from the packed depth the way basic.frag reads
    it (no PCF)."""
    fbo = vp._fig_shadow_fbo if figures else vp._frame_shadow
    assert fbo is not None
    vp.makeCurrent()
    img = fbo.toImage().convertToFormat(QImage.Format_RGBA8888)
    vp.doneCurrent()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(
        img.height(), img.bytesPerLine())[:, :img.width() * 4].reshape(
        img.height(), img.width(), 4).astype(np.float64)
    depth = a[..., 0] / 255 + a[..., 1] / 65025 + a[..., 2] / 16581375
    m = np.array(vp._shadow_vp.data(), np.float64).reshape(4, 4).T
    gx, gy = np.meshgrid(xs, ys)
    p = m @ np.stack([gx.ravel(), gy.ravel(), np.full(gx.size, z),
                      np.ones(gx.size)])
    u, v, d = p[0] * .5 + .5, p[1] * .5 + .5, p[2] * .5 + .5
    size = img.width()
    col = np.clip((u * size).astype(int), 0, size - 1)
    row = np.clip(((1 - v) * size).astype(int), 0, size - 1)
    inside = (u > 0) & (u < 1) & (v > 0) & (v < 1)
    recv = vp._shadow_biases(vp._shadow_vp)[2]
    return (inside & (depth[row, col] < d - recv)).reshape(gx.shape)


def _top_down(vp, hour, half=1.6, yaw=0.0):
    """A parallel camera straight down on the feet, ``half`` metres each
    side of them; returns (image, world → pixel)."""
    vp.scene.shadows.hour = hour
    vp.scene.version += 1
    cam = vp.camera
    cam.perspective = False
    cam.target = V(FEET)
    cam.yaw = math.radians(yaw)
    cam.pitch = math.radians(89.0)
    cam.distance = half / math.tan(math.radians(cam.fov_deg) / 2.0)
    _frame(vp, settle=True)
    img = vp.grabFramebuffer().convertToFormat(QImage.Format_RGBA8888)
    mvp = cam.projection_matrix() * cam.view_matrix()

    def px(p):
        c = mvp.map(QVector4D(p.x(), p.y(), p.z(), 1.0))
        return ((c.x() / c.w() * .5 + .5) * img.width(),
                (1 - (c.y() / c.w() * .5 + .5)) * img.height())
    return img, px


def _fbo_bytes(fbo):
    img = fbo.toImage()            # held: constBits() views its memory
    return bytes(img.constBits())


def _lum(img):
    a = np.frombuffer(img.constBits(), np.uint8).reshape(
        img.height(), img.bytesPerLine())[:, :img.width() * 4].reshape(
        img.height(), img.width(), 4)
    rgb = a[..., :3].astype(np.float32)
    return rgb.mean(axis=2), rgb.max(axis=2) - rgb.min(axis=2)


# ---- 1. a lone figure casts --------------------------------------------------

def test_a_model_with_only_the_figure_has_a_shadow(view):
    _add_figure(view)
    view.scene.shadows.hour = 15
    view.scene.version += 1
    _orbit(view, -60)
    _frame(view)
    assert view._frame_shadow is not None, "no sun map for a lone figure"
    d = view._frame_sun
    t = 1.0 / d[2]                    # the shadow of the figure's middle
    xs = np.linspace(-3, 3, 121) + FEET.x()
    ys = np.linspace(-3, 3, 121) + FEET.y()
    shade = _map_footprint(view, xs, ys)
    assert shade.sum() > 50
    # ...and it lies where the sun throws it, away from the sun.
    gx, gy = np.meshgrid(xs, ys)
    cx, cy = gx[shade].mean(), gy[shade].mean()
    assert (cx - FEET.x()) * d[0] + (cy - FEET.y()) * d[1] < 0
    assert math.hypot(cx - FEET.x() + d[0] * t,
                      cy - FEET.y() + d[1] * t) < 0.6


# ---- 2. it holds still while the camera orbits -------------------------------

def test_orbiting_keeps_the_model_map_and_redraws_only_the_figures(view):
    """The model's map is kept while the camera orbits — the figures are
    not in it — and the figures' own map follows the camera."""
    _add_figure(view, feet_right=True)
    mesh = view.scene.mesh
    mesh.add_face([V(2, 2, 0), V(3, 2, 0), V(3, 2, 1), V(2, 2, 1)])
    view.scene.shadows.hour = 15
    view.scene.version += 1
    calls = {"model": 0}
    real = view._render_shadow_map

    def counted(*a, **k):
        calls["model"] += 1
        return real(*a, **k)
    view._render_shadow_map = counted
    maps, figs = [], []
    for yaw in (-60, 40, 150):
        _orbit(view, yaw)
        _frame(view)
        view.makeCurrent()
        maps.append(_fbo_bytes(view._frame_shadow))
        figs.append(_fbo_bytes(view._fig_shadow_fbo))
        view.doneCurrent()
    assert calls["model"] == 1, calls
    assert maps[0] == maps[1] == maps[2]
    assert figs[0] != figs[1] != figs[2]
    # The figure is not in the model's map: a model of the wall alone.
    xs = np.linspace(-1.5, 1.5, 61) + FEET.x()
    ys = np.linspace(-1.5, 1.5, 61) + FEET.y()
    assert not _map_footprint(view, xs, ys, figures=False).any()
    assert _map_footprint(view, xs, ys).sum() > 20


def test_the_fitted_map_keeps_the_whole_figure_shadow(view):
    """Once the view settles, the map fitted to it (#958) holds all of
    the figure's shadow — it once cut it, differently at each camera."""
    _add_figure(view)
    view.scene.mesh.add_face([V(3, 3, 0), V(5, 3, 0), V(5, 5, 0),
                              V(3, 5, 0)])
    view.scene.shadows.hour = 9
    view.scene.version += 1
    xs = np.linspace(-3.0, 3.0, 301) + FEET.x()
    ys = np.linspace(-3.0, 3.0, 301) + FEET.y()
    for yaw in (0, 90, 180, 270):
        _orbit(view, yaw, pitch_deg=30, dist=5.0)
        _frame(view)
        whole = _map_footprint(view, xs, ys)
        _frame(view, settle=True)
        assert view._shadow_fit is not None, "the view did not settle"
        fit = _map_footprint(view, xs, ys)
        assert whole.sum() > 200
        both = (fit & whole).sum()
        # The two maps differ in their texels along the shadow's rim only.
        assert both / whole.sum() > 0.85, (yaw, both / whole.sum())
        assert both / max(fit.sum(), 1) > 0.85, (yaw, both / fit.sum())


@pytest.mark.parametrize("hour", (9, 12, 17))
def test_both_feet_of_the_shadow_meet_the_drawn_feet(view, hour):
    """Straight down on a figure whose feet stand off the picture's middle
    (only its right half is opaque, u 0.5…1), at several cameras: just
    past the drawn base, away from the sun, the ground is in shadow all
    along the opaque half — the shoes — and lit along the clear half and
    on the sun's side."""
    g = _add_figure(view, feet_right=True)
    # The cutout itself, seen almost edge-on from straight above, is a
    # strip a few centimetres deep across the feet: left out of the
    # picture so the ground under it shows (the figures' shadow pass does
    # not go through the drawing).
    view._draw_billboards = lambda: None
    checked = 0
    for yaw in range(0, 360, 45):
        img, px = _top_down(view, hour, yaw=yaw)
        d = view._frame_sun
        lum, sat = _lum(img)
        ground = float(np.median(lum))
        away = V(-d[0], -d[1], 0.0).normalized()
        c0, c1 = view._billboard_quad(g)[0][:2]
        base = (c1 - c0).normalized()
        if abs(base.x() * away.y() - base.y() * away.x()) < 0.5:
            continue          # seen edge-on from the sun: a thin line
        checked += 1

        def dark(p):
            x, y = px(p)
            r, c = int(round(y)), int(round(x))
            return lum[r, c] < ground - 25 and sat[r, c] < 12

        def at(t, out):
            return c0 + (c1 - c0) * t + away * out
        for t in (0.55, 0.75, 0.95):
            for cm in (1.0, 3.0):
                assert dark(at(t, cm / 100)), (yaw, t, cm)
        for t in (0.05, 0.25, 0.45):
            assert not dark(at(t, 0.03)), (yaw, t)
        assert not dark(at(0.75, -0.06)), (yaw, "shadow on the sun's side")
    assert checked >= 3


def test_the_quad_turns_round_the_feet():
    """No GL: whatever it faces, the quad keeps the feet of its cutout on
    the anchor (here the cutout's feet stand at u = 0.75)."""
    from views.viewport.billboards import BillboardMixin

    class Stub(BillboardMixin):
        def _billboard_extent(self, g):
            return (V(1, 2, 0), 1.0, 2.0, "x.png")

        def _figure_feet_u(self, path):
            return 0.75

    s = Stub()
    for ang in range(0, 360, 30):
        face = V(math.cos(math.radians(ang)), math.sin(math.radians(ang)), 0)
        c0, c1, _c2, _c3 = s._billboard_quad(object(), face_dir=face)[0]
        feet = c0 + (c1 - c0) * 0.75
        assert (feet - V(1, 2, 0)).length() < 1e-6


def test_feet_are_found_in_the_cutout(tmp_path):
    from views.viewport.billboards import _feet_of
    u, v = _feet_of(_cutout(tmp_path / "a.png", True))
    assert u == pytest.approx(0.75, abs=0.01) and v == pytest.approx(0.0025)
    u, _v = _feet_of(_cutout(tmp_path / "b.png", False))
    assert u == pytest.approx(0.5, abs=0.01)
    assert _feet_of(str(tmp_path / "missing.png")) == (0.5, 0.0)


# ---- 4. a model without figures keeps its shadow -----------------------------

def test_a_model_without_figures_keeps_its_sun_map(view):
    mesh = view.scene.mesh
    p = [V(0, 0, 0), V(2, 0, 0), V(2, 1, 0), V(0, 1, 0),
         V(0, 0, 3), V(2, 0, 3), V(2, 1, 3), V(0, 1, 3)]
    for idx in ((3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([p[i] for i in idx])
    view.scene.shadows.hour = 15
    view.scene.version += 1
    _orbit(view, -60)
    _frame(view)
    lo, hi = view.scene.bounds()
    slo, shi = view._shadow_bounds()
    assert (slo, shi) == (lo, hi)
    d = view._frame_sun
    assert view._shadow_vp == view._light_vp(d, lo, hi)
    mvp = view.camera.projection_matrix() * view.camera.view_matrix()
    assert view._figure_shadows_in_view(mvp, d,
                                        view._light_view(d, lo, hi)[0]) == []
    assert view._fig_shadow_key is None      # no figures' map drawn


def test_the_figure_snaps_at_its_feet_at_any_orbit(tmp_path):
    """The one snap a figure offers is its feet — where it was placed —
    whatever the camera, also for a cutout drawn off its picture's middle
    (it was the middle of the quad's base, which turns with the camera:
    «la inferencia de la imagen del ingeniero no la hace bien», 22-11).
    And a Move drag's preview carries it along."""
    from core.group import make_billboard_group
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        vp.scene.groups[:] = []
        g = make_billboard_group(_cutout(tmp_path / "f.png", True), 2.0,
                                 "figure", 0.5, position=FEET)
        vp.scene.groups.append(g)
        vp.scene.version += 1
        for yaw in range(0, 360, 40):
            _orbit(vp, yaw)
            snaps = vp._billboard_snap_edges()
            assert len(snaps) == 1
            assert (snaps[0].a - FEET).length() < 1e-6, yaw
            c0, c1 = vp._billboard_quad(g)[0][:2]
            assert (c0 + (c1 - c0) * 0.75 - FEET).length() < 1e-5, yaw
        vp._preview_groups = {id(g)}
        vp._preview_matrix = None
        vp._preview_offset = V(1.0, 2.0, 0.0)
        try:
            assert (vp._billboard_snap_edges()[0].a
                    - (FEET + V(1, 2, 0))).length() < 1e-6
        finally:
            vp._preview_groups = set()
            vp._preview_offset = V(0, 0, 0)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_dragging_a_figure_leaves_the_model_map_alone(view):
    """A Move drag of the figure alone redraws only the figures' map: the
    model's map was redrawn as the drag began and again as it ended
    (158 times while Marco dragged the engineer across the plaza, 22-11).
    A drag of a model's group still redraws it."""
    from core.group import Group
    from core.mesh import Mesh
    fig = _add_figure(view)
    m = Mesh()
    m.add_face([V(2, 2, 0), V(3, 2, 0), V(3, 2, 1), V(2, 2, 1)])
    box = Group(m, name="wall")
    view.scene.groups.append(box)
    view.scene.shadows.hour = 15
    view.scene.version += 1
    _orbit(view, -60)
    _frame(view)
    calls = {"model": 0}
    real = view._render_shadow_map

    def counted(*a, **k):
        calls["model"] += 1
        return real(*a, **k)
    view._render_shadow_map = counted
    figs = []
    view.begin_groups_preview([fig])
    for i in range(4):
        view.set_groups_preview_offset(V(0.2 * i, 0.1 * i, 0.0))
        _frame(view)
        view.makeCurrent()
        figs.append(_fbo_bytes(view._fig_shadow_fbo))
        view.doneCurrent()
    view.end_groups_preview()
    _frame(view)
    assert calls["model"] == 0, calls
    assert len(set(figs)) == 4               # its own shadow follows it
    view.begin_groups_preview([box])
    _frame(view)
    view.end_groups_preview()
    _frame(view)
    assert calls["model"] >= 1


def test_the_fitted_map_keeps_a_figure_shadow_seen_without_the_figure(view):
    """Looking down at the far end of a long shadow, the figure itself out
    of the picture: the map fitted to the view (#958) is drawn round what
    the view shows, and the bare ground the shadow lies on is not in the
    depth it is measured from — the figure's shadow must be held in it
    all the same."""
    _add_figure(view)
    view.scene.shadows.hour = 16
    view.scene.version += 1
    _frame(view)
    d = view._frame_sun
    away = V(-d[0], -d[1], 0.0).normalized()
    spot = FEET + away * 2.6
    side = V(-away.y(), away.x(), 0.0)
    a = spot + side * 1.0 + away * 0.6
    view.scene.mesh.add_face([a, a + away * 0.3, a + away * 0.3 + side * 0.3,
                              a + side * 0.3])
    view.scene.version += 1
    cam = view.camera
    cam.perspective = False
    cam.target = V(spot)
    cam.yaw = 0.0
    cam.pitch = math.radians(89.0)
    cam.distance = 0.9 / math.tan(math.radians(cam.fov_deg) / 2.0)
    xs = np.linspace(-0.8, 0.8, 161) + spot.x()
    ys = np.linspace(-0.8, 0.8, 161) + spot.y()
    _frame(view)
    whole = _map_footprint(view, xs, ys)
    _frame(view, settle=True)
    assert view._shadow_fit is not None, "the view did not settle"
    fit = _map_footprint(view, xs, ys)
    assert whole.sum() > 200
    assert (fit & whole).sum() / whole.sum() > 0.85
