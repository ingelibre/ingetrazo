# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""File ▸ Export ▸ 360° Image: six views from the eye joined into one
equirectangular panorama, marked for panorama viewers, the camera given
back as it was.

The joining is checked with synthetic faces whose every pixel says the
direction it looks along: read back from the panorama, each pixel must
say the direction its longitude and latitude name — the orientation of
each face and the joins between them in one go."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QImage, QVector3D
from PySide6.QtWidgets import QApplication

from core import panorama
from core.camera import OrbitCamera

_app = QApplication.instance() or QApplication([])
V = QVector3D


def _faces_from_camera(camera, eye, basis, side, paint):
    """The six faces as ``panorama_export`` takes them, each pixel painted
    by ``paint(world_directions)`` — no rendering."""
    from views.panorama_export import point_camera, view_rotation
    full, fov = panorama.face_render(side)
    t = (np.arange(full) + 0.5) / full * 2.0 - 1.0
    tan = t * full / side
    tx, ty = np.meshgrid(tan, -tan)                  # row 0 at the top
    faces = []
    for direction in panorama.face_directions(basis):
        point_camera(camera, eye, direction, fov)
        rot = view_rotation(camera)
        cam = np.stack([tx, ty, -np.ones_like(tx)], axis=-1)
        cam /= np.linalg.norm(cam, axis=-1, keepdims=True)
        world = cam @ rot                             # R^T · c, row-wise
        faces.append((rot, paint(world)))
    return faces


def _encode(world):
    rgb = np.clip(np.rint((world + 1.0) * 127.5), 0, 255).astype(np.uint8)
    return np.concatenate([rgb, np.full(rgb.shape[:2] + (1,), 255,
                                        np.uint8)], axis=-1)


def _box(mesh, x0, x1, y0, y1, z0, z1, **attrs):
    c = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
              (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([c[i] for i in q]).attrs.update(attrs)


def _expected(width, basis):
    h = width // 2
    return panorama.directions(width, h, slice(0, h), basis)


# ---- Sizes --------------------------------------------------------------

def test_the_qualities_start_at_2k_and_are_twice_as_wide_as_tall():
    assert [w for w, _ in panorama.QUALITIES] == [2048, 4096, 6144, 8192]
    assert panorama.DEFAULT_WIDTH == 4096
    assert panorama.panorama_size(4096) == (4096, 2048)
    # Never under 2K, whatever is asked.
    assert panorama.panorama_size(640) == (2048, 1024)


def test_each_face_has_the_panorama_s_detail_and_a_border():
    side = panorama.face_size(4096)
    assert side % 8 == 0 and side >= 4096 / math.pi
    full, fov = panorama.face_render(side)
    assert full > side and fov > 90.0
    # The middle ``side`` pixels are exactly 90°.
    assert math.isclose(math.tan(math.radians(fov) / 2.0), full / side)


# ---- Pointing the faces -------------------------------------------------

@pytest.mark.parametrize("direction", [(0, 0, 1), (0, 0, -1), (1, 0, 0),
                                       (0, -1, 0)])
def test_a_face_looks_exactly_along_its_direction(direction):
    """Straight up and down too, which ``look_from`` keeps 1° off."""
    from views.panorama_export import point_camera
    cam = OrbitCamera()
    eye = V(3, -4, 1.6)
    point_camera(cam, eye, np.array(direction, float), 92.0)
    f = cam.forward()
    assert (f - V(*direction)).length() < 1e-6
    assert (cam.eye() - eye).length() < 1e-4
    assert cam.aspect == 1.0 and cam.fov_deg == 92.0 and cam.perspective


# ---- Joining ------------------------------------------------------------

@pytest.mark.parametrize("forward", [(1.0, 0.0), (-0.3, 0.8)])
def test_every_pixel_of_the_panorama_looks_where_it_should(forward):
    width = 2048
    side = panorama.face_size(width)
    basis = panorama.heading_basis(forward)
    cam = OrbitCamera()
    faces = _faces_from_camera(cam, V(0, 0, 1.6), basis, side, _encode)
    pixels = panorama.equirectangular(faces, width, basis, side)
    got = pixels[:, :, :3].astype(np.float64) / 127.5 - 1.0
    want = _expected(width, basis)
    err = np.linalg.norm(got - want, axis=-1)
    # Quantised to 8 bits: about 1/127 per component.
    assert err.max() < 0.03, err.max()


def test_the_middle_is_the_view_s_heading_and_right_is_to_the_right():
    width = 2048
    side = panorama.face_size(width)
    basis = panorama.heading_basis((0.0, 1.0))         # looking north
    colours = {}

    def paint(world):
        # Which way each pixel looks, as the main axis it leans to.
        k = np.argmax(np.abs(world), axis=-1)
        s = np.take_along_axis(world, k[..., None], -1)[..., 0] > 0
        code = (k * 2 + s).astype(np.uint8) * 30
        return np.stack([code, code, code, np.full_like(code, 255)], -1)

    faces = _faces_from_camera(OrbitCamera(), V(0, 0, 0), basis, side, paint)
    pixels = panorama.equirectangular(faces, width, basis, side)
    h = width // 2
    for name, (x, y) in {"front": (width // 2, h // 2),
                         "right": (3 * width // 4, h // 2),
                         "left": (width // 4, h // 2),
                         "back": (2, h // 2), "up": (width // 2, 2),
                         "down": (width // 2, h - 3)}.items():
        colours[name] = int(pixels[y, x, 0]) // 30
    # axis*2 + positive: y+ (north) = 3, x+ (east) = 1, x- = 0, y- = 2.
    assert colours == {"front": 3, "right": 1, "left": 0, "back": 2,
                       "up": 5, "down": 4}


# ---- The mark viewers read ----------------------------------------------

def test_the_jpeg_and_the_png_carry_the_panorama_mark_and_still_open():
    from views.panorama_export import encode
    pixels = np.zeros((64, 128, 4), np.uint8)
    pixels[..., 0] = 200
    pixels[..., 3] = 255
    for suffix in (".jpg", ".png"):
        data = encode(pixels, suffix)
        assert b'GPano:ProjectionType="equirectangular"' in data
        assert b'GPano:FullPanoWidthPixels="128"' in data
        img = QImage.fromData(data)
        assert not img.isNull() and (img.width(), img.height()) == (128, 64)
        assert QImage.fromData(data).pixelColor(5, 5).red() > 180


# ---- The sky by direction -----------------------------------------------

def test_the_panorama_sky_matches_the_level_view_straight_ahead():
    """A level view shows a direction rising ``s`` at NDC ``y = s`` (90°
    field): the panorama's sky is that tone, wherever the direction is."""
    from views.viewport import Viewport
    sky, hor, gnd = (0.4, 0.6, 0.9), (0.95, 0.95, 0.9), (0.5, 0.45, 0.4)
    for horizon in (hor, None):
        # The level view: horizon at y = 0, sky at 0 and 1, ground at -1.
        level = Viewport._sky_gradient(sky, horizon, gnd, 0.0)
        at = lambda s: Viewport._sky_color_at_slope(sky, horizon, gnd, s)  # noqa: E731
        assert np.allclose(at(0.0), level[0])
        assert np.allclose(at(1.0), level[1])
        assert np.allclose(at(-1.0), level[3])
        far_up = Viewport._sky_color_at_slope(sky, horizon, gnd, 1e6)
        assert np.allclose(far_up, sky)
        far_down = Viewport._sky_color_at_slope(sky, horizon, gnd, -1e6)
        assert np.allclose(far_down, gnd)


def test_the_sky_grid_has_a_row_on_the_horizon():
    from views.viewport import Viewport
    rows = Viewport._sky_grid_rows(0.123, 8)
    assert 0.123 in rows and rows == sorted(rows)
    assert rows[0] == -1.0 and rows[-1] == 1.0
    assert Viewport._sky_grid_rows(2.0, 8) == [-1.0 + i / 4 for i in range(9)]


# ---- Rendering and giving the camera back -------------------------------

class _FakeView:
    def __init__(self):
        self.camera = OrbitCamera()
        self.asked = []

    def render_image(self, w, h, **kw):
        assert self._export_panorama is True
        self._draw_style_watermarks()           # a no-op while exporting
        self.asked.append((w, h, kw.get("overlays"),
                           QVector3D(self.camera.forward())))
        img = QImage(w, h, QImage.Format_RGBA8888)
        img.fill(0xFF336699)
        return img

    def _draw_style_watermarks(self, *a, **k):
        raise AssertionError("watermarks drawn into a panorama face")

    def update(self):
        pass


def test_the_camera_comes_back_exactly_even_when_locked(tmp_path):
    from views.panorama_export import export_panorama
    vp = _FakeView()
    cam = vp.camera
    cam.target, cam.distance = V(2, 3, 1), 7.0
    cam.yaw, cam.pitch, cam.fov_deg = 0.7, 0.2, 55.0
    cam.shift_y, cam.roll_deg, cam.frame_aspect = 0.1, 4.0, 1.5
    cam.two_point = True
    cam.locked = True
    before = {k: (QVector3D(v) if isinstance(v, QVector3D) else v)
              for k, v in cam.__dict__.items()}
    w, h = export_panorama(vp, tmp_path / "p.jpg", 2048)
    assert (w, h) == (2048, 1024)
    assert len(vp.asked) == 6
    full, _ = panorama.face_render(panorama.face_size(2048))
    assert all(a[:3] == (full, full, False) for a in vp.asked)
    # Six different ways, straight up and down among them.
    zs = sorted(round(a[3].z(), 6) for a in vp.asked)
    assert zs == [-1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    assert cam.__dict__.keys() == before.keys()
    for k, v in before.items():
        assert getattr(cam, k) == v, k
    assert "_export_panorama" not in vp.__dict__
    assert "_draw_style_watermarks" not in vp.__dict__
    data = (tmp_path / "p.jpg").read_bytes()
    assert b"GPano" in data
    assert QImage.fromData(data).size().width() == 2048


def test_a_failed_face_still_gives_the_camera_back(tmp_path):
    from views.panorama_export import PanoramaError, export_panorama
    vp = _FakeView()
    vp.render_image = lambda *a, **k: None
    yaw = vp.camera.yaw
    with pytest.raises(PanoramaError):
        export_panorama(vp, tmp_path / "p.jpg", 2048)
    assert vp.camera.yaw == yaw
    assert not (tmp_path / "p.jpg").exists()


# ---- In the window ------------------------------------------------------

@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(900, 600)
    w.show()
    _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def test_the_export_menu_offers_the_360_image(win):
    from PySide6.QtWidgets import QMenu
    labels = [a.text() for m in win.findChildren(QMenu)
              if m.title() == "Export" for a in m.actions()]
    assert "360° Image (JPG / PNG)…" in labels


def test_a_real_panorama_has_no_joins_in_the_sky(win, tmp_path):
    """Rendered for real: the red box ahead in the middle, the blue one
    behind at the edges, and the sky's tone running on smoothly across the
    joins between faces, the camera where it was."""
    vp = win.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        pytest.skip("no OpenGL context on this platform")
    from views.panorama_export import export_panorama
    mesh = vp.scene.mesh
    _box(mesh, 8, 10, -1, 1, 0, 3, color=(0.9, 0.1, 0.1))     # ahead (+x)
    _box(mesh, -10, -8, -1, 1, 0, 3, color=(0.1, 0.2, 0.9))   # behind
    vp.scene.version += 1
    cam = vp.camera
    cam.perspective = True
    cam.place(V(0, 0, 1.5), V(5, 0, 1.5))
    eye, fwd = cam.eye(), cam.forward()
    path = tmp_path / "p.jpg"
    w, h = export_panorama(vp, path, 2048)
    assert (cam.eye() - eye).length() < 1e-6
    assert (cam.forward() - fwd).length() < 1e-6
    img = QImage(str(path))
    assert (img.width(), img.height()) == (2048, 1024)
    mid = img.pixelColor(w // 2, h // 2 - 20)
    assert mid.red() > 150 and mid.blue() < 100, mid.name()
    back = img.pixelColor(3, h // 2 - 20)
    assert back.blue() > 150 and back.red() < 100, back.name()
    # The sky, all the way round: each row one tone. Painted by its height
    # on each face's screen, it waved where the faces meet (8 levels apart
    # on the same row), above all at the joins with the face looking up.
    from views.panorama_export import image_array
    sky = image_array(img).astype(int)[5:int(h * 0.39), :, :3]
    spread = (sky.max(axis=1) - sky.min(axis=1)).max()
    assert spread <= 3, int(spread)
