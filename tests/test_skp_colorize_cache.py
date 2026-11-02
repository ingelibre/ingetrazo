# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Colourization reuse preserves encoded pixels, mode, and cache bounds."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer
from PySide6.QtGui import QImage, qRgba

from formats import skp_openskp as skp


@pytest.fixture(autouse=True)
def _empty_cache():
    skp._colorize_cache.clear()
    yield
    skp._colorize_cache.clear()


def _image(red=150):
    image = QImage(3, 2, QImage.Format_RGBA8888)
    image.fill(qRgba(red, 80, 40, 255))
    image.setPixel(0, 0, qRgba(10, 20, 30, 0))
    image.setPixel(1, 0, qRgba(30, 100, 200, 128))
    buffer = QBuffer()
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def test_key_includes_image_color_and_mode(monkeypatch):
    original = skp._colorize_image
    calls = []

    def counted(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(skp, "_colorize_image", counted)
    cases = [(_image(), (20, 180, 30), 0), (_image(), (20, 180, 30), 1),
             (_image(), (120, 20, 30), 0), (_image(170), (20, 180, 30), 0)]
    for data, color, mode in cases:
        expected = original(data, color, mode)
        assert skp._cached_colorize(data, color, mode) == expected
        # Equal bytes in a distinct object and a list colour still hit.
        assert skp._cached_colorize(bytes(bytearray(data)), list(color), mode) == expected
    assert len(calls) == len(cases)


def test_materials_reuse_pixels_without_changing_filenames(tmp_path, monkeypatch):
    data = _image()
    tex = SimpleNamespace(data=data, filename="texture.png", width=1, height=1)
    materials = {mid: SimpleNamespace(texture=tex, color=(20, 180, 30),
                                     colorized=True, colorize_type=1, name=f"m{mid}")
                 for mid in (1, 2)}
    monkeypatch.setattr(skp, "_texture_dir", lambda _: tmp_path)
    original = skp._colorize_image
    expected = original(data, (20, 180, 30), 1)
    calls = []

    def counted(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(skp, "_colorize_image", counted)
    for _ in range(2):
        attrs, _ = skp._material_attrs(SimpleNamespace(materials_by_id=materials), "a.skp")
        assert attrs[1]["texture"]["path"].endswith("1_texture.png")
        assert attrs[2]["texture"]["path"].endswith("2_texture.png")
        assert (tmp_path / "1_texture.png").read_bytes() == expected
        assert (tmp_path / "2_texture.png").read_bytes() == expected
    assert calls == [1]


def test_failures_are_retried_and_results_have_a_byte_budget(monkeypatch):
    calls = []

    def colorize(data, color, mode):
        calls.append(data)
        return data if data == b"bad" else b"result:" + data

    monkeypatch.setattr(skp, "_colorize_image", colorize)
    monkeypatch.setattr(skp, "_COLORIZE_CACHE_LIMIT", 16)
    for _ in range(2):
        assert skp._cached_colorize(b"bad", (1, 2, 3), 0) == b"bad"
    assert calls == [b"bad", b"bad"]
    for data in (b"a", b"b", b"a", b"c", b"b", b"too large to retain"):
        assert skp._cached_colorize(data, (1, 2, 3), 0) == b"result:" + data
        assert sum(map(len, skp._colorize_cache.values())) <= 16
    assert calls[2:] == [b"a", b"b", b"c", b"b", b"too large to retain"]
