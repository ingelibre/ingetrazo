# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A 360° panorama as the style's backdrop: the HDR reader, the way to the
screen, the direction lookup, and the picture travelling in the document.

Every picture here is generated: a tiny equirectangular panorama with one
colour per quarter of the horizon, so a direction tells which colour it
must land on."""
from __future__ import annotations

import math
import os
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QSettings, QSize
from PySide6.QtGui import QImage, QVector3D as V
from PySide6.QtWidgets import QApplication

from core import panorama_backdrop as pb
from core.scene import Scene
from core.style import Style

_app = QApplication.instance() or QApplication([])

#: The quarters of the horizon, by the picture's columns (see direction_uv):
#: the middle faces +Y (north), the right quarter +X (east).
NORTH, EAST, SOUTH, WEST = (220, 40, 40), (40, 200, 60), (230, 210, 40), (40, 70, 220)
SKY, GROUND = (250, 250, 250), (20, 20, 20)


def quarters(width=64, height=32) -> np.ndarray:
    """A uint8 panorama: a white band at the top, black at the bottom and,
    in between, one colour per quarter of the horizon."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    u = (np.arange(width) + 0.5) / width
    for lo, hi, colour in ((0.375, 0.625, NORTH), (0.625, 0.875, EAST),
                           (0.125, 0.375, WEST)):
        img[:, (u >= lo) & (u < hi)] = colour
    img[:, (u < 0.125) | (u >= 0.875)] = SOUTH
    img[: height // 8] = SKY
    img[height - height // 8:] = GROUND
    return img


def save_png(pixels: np.ndarray, path) -> str:
    h, w = pixels.shape[:2]
    data = np.ascontiguousarray(pixels)
    assert QImage(data.data, w, h, w * 3, QImage.Format_RGB888).save(str(path))
    return str(path)


def rle_hdr(rgb: np.ndarray) -> bytes:
    """A run-length Radiance file, the way real writers store it — runs
    where values repeat, literals elsewhere — so the reader's main path is
    exercised (write_hdr writes flat pixels)."""
    flat = pb.write_hdr(rgb)
    head, _, body = flat.partition(b"+X %d\n" % rgb.shape[1])
    h, w = rgb.shape[:2]
    pixels = np.frombuffer(body, dtype=np.uint8).reshape(h, w, 4)
    out = bytearray(head + b"+X %d\n" % w)
    for y in range(h):
        out += bytes((2, 2, w >> 8, w & 0xFF))
        for c in range(4):
            line = pixels[y, :, c].tobytes()
            x = 0
            while x < w:
                run = 1
                while x + run < w and run < 127 and line[x + run] == line[x]:
                    run += 1
                if run >= 3:
                    out += bytes((128 + run, line[x]))
                    x += run
                    continue
                n = 1
                while (x + n < w and n < 128
                       and not (x + n + 2 < w and line[x + n] == line[x + n + 1]
                                == line[x + n + 2])):
                    n += 1
                out += bytes((n,)) + line[x:x + n]
                x += n
    return bytes(out)


def light(width=64, height=32) -> np.ndarray:
    """Float light values: a bright sun spot (far beyond white) on a dim
    gradient — what an HDR sky looks like."""
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    rgb = np.stack([0.05 + x / width, 0.1 + y / height,
                    np.full_like(x, 0.3)], axis=-1)
    rgb[4:6, 30:34] = (40.0, 38.0, 30.0)
    return rgb


# --- The HDR reader ---------------------------------------------------------

def test_a_flat_hdr_reads_back_its_light_values():
    rgb = light()
    back = pb.read_hdr(pb.write_hdr(rgb))
    assert back.shape == rgb.shape
    # RGBE shares one exponent per pixel: each channel is within one step
    # of 8 bits of the pixel's brightest channel.
    peak = rgb.max(axis=2, keepdims=True)
    assert np.all(np.abs(back - rgb) <= peak / 128)


def test_a_run_length_hdr_reads_like_the_flat_one():
    rgb = light(width=80, height=12)
    rgb[:, 10:50] = (2.0, 2.0, 2.0)               # long runs
    assert np.array_equal(pb.read_hdr(rle_hdr(rgb)),
                          pb.read_hdr(pb.write_hdr(rgb)))


@pytest.mark.parametrize("data", [
    b"P6\n2 2\n255\n" + b"\0" * 12,                 # not a Radiance file
    b"#?RADIANCE\nFORMAT=32-bit_rle_xyze\n\n-Y 1 +X 1\n\0\0\0\0",
    b"#?RADIANCE\n\n+Y 1 +X 1\n\0\0\0\0",          # flipped orientation
    b"#?RADIANCE\n\n-Y 4 +X 4\n\0\0\0",             # cut short
])
def test_a_bad_hdr_is_refused_not_misread(data):
    with pytest.raises(ValueError):
        pb.read_hdr(data)


def test_hdr_files_count_as_images_for_the_document():
    from core.texture import is_image_bytes
    assert is_image_bytes(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n")
    assert is_image_bytes(b"#?RGBE\n")


# --- To the screen ----------------------------------------------------------

def test_the_tone_curve_keeps_black_rolls_off_highlights_and_follows_exposure():
    values = np.array([[[0.0] * 3, [0.18] * 3, [1.0] * 3, [50.0] * 3]],
                      dtype=np.float32)
    plain = pb.tone_map(values)[0, :, 0].astype(int)
    assert plain[0] == 0
    assert plain[0] < plain[1] < plain[2] < plain[3]
    assert plain[3] >= 250                        # a sun is white, not clipped grey
    assert plain[2] < 250                         # 1.0 is not yet white
    brighter = pb.tone_map(values, 1.0)[0, :, 0].astype(int)
    darker = pb.tone_map(values, -1.0)[0, :, 0].astype(int)
    assert darker[1] < plain[1] < brighter[1]


def test_load_pixels_reads_both_kinds_and_keeps_the_top_up(tmp_path):
    png = save_png(quarters(), tmp_path / "pano.png")
    pixels = pb.load_pixels(png)
    assert pixels.shape == (32, 64, 3)
    assert tuple(pixels[0, 0]) == SKY and tuple(pixels[-1, 0]) == GROUND
    hdr = tmp_path / "pano.hdr"
    hdr.write_bytes(rle_hdr(light()))
    assert pb.is_hdr_file(hdr) and not pb.is_hdr_file(png)
    shown = pb.load_pixels(str(hdr))
    assert shown.dtype == np.uint8 and shown.shape == (32, 64, 3)
    assert shown[5, 31].min() > 240               # the sun spot
    assert (pb.load_pixels(str(hdr), 2.0).astype(int).sum()
            > shown.astype(int).sum())


def test_a_wide_panorama_is_shrunk_for_the_gpu(tmp_path):
    hdr = tmp_path / "wide.hdr"
    hdr.write_bytes(pb.write_hdr(light(width=256, height=128)))
    assert pb.load_pixels(str(hdr), max_width=64).shape == (32, 64, 3)
    png = save_png(np.zeros((128, 256, 3), np.uint8), tmp_path / "wide.png")
    assert pb.load_pixels(png, max_width=64).shape == (32, 64, 3)


# --- Directions -------------------------------------------------------------

@pytest.mark.parametrize("direction, rotation, u, v", [
    ((0, 1, 0), 0, 0.5, 0.5),          # north: the picture's middle
    ((1, 0, 0), 0, 0.75, 0.5),         # east: to the right, as seen inside
    ((-1, 0, 0), 0, 0.25, 0.5),        # west: to the left
    ((0, -1, 0), 0, 0.0, 0.5),         # south: the picture's edge
    ((0, 0, 1), 0, None, 1.0),         # zenith: the top row
    ((0, 0, -1), 0, None, 0.0),        # nadir: the bottom row
    ((0, 1, 0), 90, 0.75, 0.5),        # turned a quarter counter-clockwise
])
def test_direction_uv(direction, rotation, u, v):
    got_u, got_v = pb.direction_uv(direction, rotation)
    if u is not None:
        assert min(abs(got_u - u), 1 - abs(got_u - u)) < 1e-9
    assert got_v == pytest.approx(v)


# --- In the style and the document ------------------------------------------

def test_a_style_without_a_panorama_saves_as_before():
    assert "panorama" not in Style().to_dict()


def test_the_panorama_roundtrips_in_the_style(tmp_path):
    style = Style(panorama=str(tmp_path / "p.hdr"), panorama_rotation=35.0,
                  panorama_exposure=-1.5)
    raw = style.to_dict()
    assert raw["panorama"]["texture"] == {"path": str(tmp_path / "p.hdr")}
    back = Style.from_dict(raw)
    assert (back.panorama, back.panorama_rotation, back.panorama_exposure) == \
        (str(tmp_path / "p.hdr"), 35.0, -1.5)


@pytest.mark.parametrize("raw", [
    "sky.hdr", {"texture": "sky.hdr"}, {"texture": {}},
    {"rotation": 10}, {"texture": {"embed": "textures/lost.hdr"}},
])
def test_a_malformed_or_lost_panorama_leaves_the_gradient(raw):
    style = Style.from_dict({"panorama": raw})
    assert style.panorama == ""


def test_out_of_range_values_are_clamped():
    back = Style.from_dict({"panorama": {"texture": {"path": "a.png"},
                                         "rotation": 9999, "exposure": "x"}})
    assert back.panorama_rotation == 360.0 and back.panorama_exposure == 0.0


def test_the_panorama_belongs_to_the_background_category():
    from core.style_mix import mix_style_category
    source = Style(panorama="sky.hdr", panorama_rotation=20.0,
                   panorama_exposure=1.0)
    mixed = mix_style_category(Style(), source, "background")
    assert (mixed.panorama, mixed.panorama_rotation,
            mixed.panorama_exposure) == ("sky.hdr", 20.0, 1.0)
    assert mix_style_category(Style(), source, "edges").panorama == ""


def test_the_picture_travels_inside_the_document(tmp_path):
    """Saved, the original deleted (another machine), opened: the style
    still has its panorama, from the document itself."""
    from formats import igz
    from core.camera import OrbitCamera
    from core.saved_views import SavedView
    hdr = tmp_path / "plaza.hdr"
    data = rle_hdr(light())
    hdr.write_bytes(data)
    scene = Scene()
    scene.mesh.add_edge(V(), V(1, 0, 0))
    scene.display_style = Style(panorama=str(hdr), panorama_rotation=30.0)
    scene.saved_views.append(SavedView.capture("Patio", scene, OrbitCamera()))
    igz.save_scene(scene, tmp_path / "doc.igz")
    with zipfile.ZipFile(tmp_path / "doc.igz") as z:
        members = [n for n in z.namelist() if n.startswith("textures/")]
        info = z.getinfo(members[0])
    assert len(members) == 1 and members[0].endswith("plaza.hdr")
    # An HDR is deflated (PNG/JPG stay stored: they are compressed already).
    assert info.compress_type == zipfile.ZIP_DEFLATED
    assert scene.display_style.panorama == str(hdr)     # the live style intact
    hdr.unlink()
    loaded = Scene()
    igz.load_into(loaded, tmp_path / "doc.igz")
    path = loaded.display_style.panorama
    assert path and path != str(hdr)
    assert open(path, "rb").read() == data
    assert loaded.display_style.panorama_rotation == 30.0
    loaded.display_style = Style()
    loaded.saved_views[0].apply(loaded, OrbitCamera())
    assert loaded.display_style.panorama == path


def test_the_style_sample_shows_the_view_ahead(tmp_path):
    from views.style_preview import style_preview
    png = save_png(quarters(), tmp_path / "pano.png")
    plain = style_preview(Style(), QSize(100, 80)).toImage()
    sample = style_preview(Style(panorama=png), QSize(100, 80)).toImage()
    assert sample.pixelColor(6, 30).getRgb()[:3] == NORTH
    assert plain.pixelColor(6, 30).getRgb()[:3] != NORTH
    turned = style_preview(Style(panorama=png, panorama_rotation=90.0),
                           QSize(100, 80)).toImage()
    assert turned.pixelColor(6, 30).getRgb()[:3] == EAST


# --- In the Styles panel (and the Styles window, which shows the same one) --

@pytest.mark.parametrize("path, label", [
    ("C:/x/9b6af3b51466a02d-cielo-sintetico.hdr", "cielo-sintetico.hdr"),
    ("/x/plaza.png", "plaza.png"),
    ("/x/a-very-long-name-for-a-sunny-afternoon-sky.hdr", None),
])
def test_the_panel_names_the_picture_as_the_user_knows_it(path, label):
    got = pb.panorama_label(path)
    if label is not None:
        assert got == label
    else:
        assert len(got) == 24 and "…" in got and got.endswith(".hdr")


@pytest.fixture
def styles_panel(tmp_path, monkeypatch):
    import core.style as styles
    from tests.test_styles_window import _Window
    from views.tray import StylesPanel
    monkeypatch.setattr(styles, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))
    window = _Window()
    panel = StylesPanel(window)
    window.panel = panel
    yield window, panel
    panel.close()
    panel.deleteLater()


def test_a_long_picture_name_does_not_widen_the_styles_window(styles_panel,
                                                              tmp_path):
    """In the 400 px Styles window the cache's hashed file name pushed the
    colour swatches and the «×» out of sight behind a scroll bar."""
    window, panel = styles_panel
    panel.refresh()
    before = panel.minimumSizeHint().width()
    name = "9b6af3b51466a02d-" + "a-very-long-panorama-name" * 3 + ".png"
    window.viewport.scene.display_style = Style(
        panorama=save_png(quarters(), tmp_path / name))
    panel.refresh()
    assert panel._panorama_btn.text() == pb.panorama_label(name)
    assert panel.minimumSizeHint().width() <= before
    assert panel._panorama_clear.isEnabled()
    assert not panel._panorama_exposure.isEnabled()      # not an HDR


def test_choose_and_remove_from_the_panel(styles_panel, tmp_path, monkeypatch):
    from views import tray
    window, panel = styles_panel
    hdr = tmp_path / "sky.hdr"
    hdr.write_bytes(pb.write_hdr(light()))
    monkeypatch.setattr(tray.file_dialogs, "getOpenFileName",
                        lambda *a, **k: (str(hdr), ""))
    window.viewport.scene.display_style = Style(sky=False)
    panel.refresh()
    panel._pick_panorama()
    style = window.viewport.scene.display_style
    assert style.panorama == str(hdr) and style.sky          # sky turned on
    assert panel._panorama_exposure.isEnabled()
    panel._panorama_rotation.setValue(45.0)
    assert style.panorama_rotation == 45.0
    panel._clear_panorama()
    assert style.panorama == "" and style.panorama_rotation == 0.0
    assert panel._panorama_btn.text() == "Choose…"
