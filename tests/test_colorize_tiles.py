# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Tiled pixel transforms match the original full-image encoded output."""
import numpy as np
import pytest
from PySide6.QtCore import QBuffer
from PySide6.QtGui import QImage

from core import texture
from core.texture import rgb_to_hls, hls_to_rgb, COLORIZE_SHIFT


# Frozen full-image oracle: preserve the exact global reduction and pixel math.
def _whole_image_colorize(data, target_rgb, ctype=COLORIZE_SHIFT):
    """Re-tint a shared texture the way the .skp format defines a
    colourized material copy ("[Name]1", ``type="2"``).

    ``ctype`` 0 ("shift") moves every pixel's hue/lightness/saturation by
    the delta between the image average and the material colour; ``1``
    ("tint") replaces hue/saturation outright, keeping the per-pixel
    lightness variation. Alpha is preserved (the chain-link cutout must
    survive). Returns PNG bytes, or ``data`` unchanged on any failure."""
    try:
        import numpy as np
        from PySide6.QtCore import QBuffer
        from PySide6.QtGui import QImage
        img = QImage.fromData(data)
        if img.isNull():
            return data
        img = img.convertToFormat(QImage.Format.Format_RGBA8888)
        w, h = img.width(), img.height()
        buf = np.frombuffer(img.constBits(), dtype=np.uint8,
                            count=h * img.bytesPerLine())
        px = buf.reshape(h, img.bytesPerLine())[:, : w * 4].reshape(h, w, 4)
        rgb = px[..., :3].astype(np.float64) / 255.0
        alpha = px[..., 3]
        vis = alpha > 0
        avg = rgb[vis].mean(axis=0) if vis.any() else rgb.mean(axis=(0, 1))
        h0, l0, s0 = rgb_to_hls(avg.reshape(1, 3))
        ht, lt, st = rgb_to_hls(
            np.array([[c / 255.0 for c in target_rgb[:3]]]))
        hue, lum, sat = rgb_to_hls(rgb)
        if ctype == 1:
            hue = np.full_like(hue, float(ht[0]))
            sat = np.full_like(sat, float(st[0]))
        else:
            hue = (hue + (float(ht[0]) - float(h0[0]))) % 1.0
            sat = np.clip(sat + (float(st[0]) - float(s0[0])), 0.0, 1.0)
        lum = np.clip(lum + (float(lt[0]) - float(l0[0])), 0.0, 1.0)
        out = np.clip(hls_to_rgb(hue, lum, sat) * 255.0 + 0.5,
                      0, 255).astype(np.uint8)
        result = np.dstack([out, alpha])
        tinted = QImage(result.tobytes(), w, h, w * 4,
                        QImage.Format.Format_RGBA8888)
        qbuf = QBuffer()
        qbuf.open(QBuffer.OpenModeFlag.WriteOnly)
        tinted.save(qbuf, "PNG")
        return bytes(qbuf.data())
    except Exception:
        return data


@pytest.mark.parametrize("alpha", ["transparent", "opaque", "mixed"])
@pytest.mark.parametrize("mode", [0, 1])
@pytest.mark.parametrize("color", [(12, 190, 71), (0, 0, 0), (255, 255, 255)])
def test_tiled_transforms_keep_exact_png_bytes(monkeypatch, alpha, mode, color):
    rng = np.random.default_rng(24)
    pixels = rng.integers(0, 256, (37, 29, 4), dtype=np.uint8)
    if alpha != "mixed":
        pixels[:, :, 3] = 0 if alpha == "transparent" else 255
    image = QImage(pixels.tobytes(), 29, 37, 29 * 4, QImage.Format_RGBA8888)
    buffer = QBuffer()
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, "PNG")
    data = bytes(buffer.data())
    expected = _whole_image_colorize(data, color, mode)
    assert expected is not data
    calls = []
    original = texture.rgb_to_hls

    def counted(rgb):
        calls.append(rgb.shape)
        return original(rgb)

    monkeypatch.setattr(texture, "_COLORIZE_TILE_PIXELS", 64)
    monkeypatch.setattr(texture, "rgb_to_hls", counted)
    assert texture.colorize_image(data, color, mode) == expected
    tiles = calls[2:]
    assert len(tiles) > 1
    assert all(shape[0] <= 64 and shape[1] == 3 for shape in tiles)
