# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet images with opacity, a cut-out shape, a feathered edge and a fit
mode (Marco, 2026-09-05: «poder poner transparencia… mostrar en círculo o
algo así con bordes que se desvanezcan»)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage, QPainter, QVector3D
from PySide6.QtWidgets import QApplication, QWidget

from core.composition import Composicion, ImagenItem
from views.composer import composited_image, paint_image_mm

_app = QApplication.instance() or QApplication([])


def _photo(w=200, h=100):
    """Left half red, right half blue — so crops are visible."""
    img = QImage(w, h, QImage.Format_ARGB32)
    p = QPainter(img)
    p.fillRect(0, 0, w // 2, h, QColor(255, 0, 0))
    p.fillRect(w // 2, 0, w - w // 2, h, QColor(0, 0, 255))
    p.end()
    return img


def _paint(item, image, k=4):
    out = QImage(int(item.w_mm * k), int(item.h_mm * k), QImage.Format_RGB32)
    out.fill(QColor(255, 255, 255))
    p = QPainter(out)
    p.scale(k, k)
    paint_image_mm(p, item, image)
    p.end()
    return out


def test_a_plain_image_is_drawn_as_is_and_opacity_blends_with_the_paper():
    photo = _photo()
    item = ImagenItem(w_mm=40, h_mm=20)
    assert composited_image(photo, item) is photo          # no work needed
    out = _paint(item, photo)
    assert out.pixelColor(20, 40) == QColor(255, 0, 0)
    item.opacity = 0.5
    out = _paint(item, photo)
    c = out.pixelColor(20, 40)
    assert 120 <= c.green() <= 135 and c.red() == 255    # half red, half white


def test_an_ellipse_cuts_the_corners_and_a_feather_fades_inward():
    photo = _photo(200, 200)
    item = ImagenItem(w_mm=40, h_mm=40, shape="ellipse")
    out = _paint(item, photo)
    assert out.pixelColor(2, 2) == QColor(255, 255, 255)   # corner: paper
    assert out.pixelColor(70, 80) == QColor(255, 0, 0)     # inside: photo (red half)
    item.feather_mm = 8.0
    out = _paint(item, photo)
    # along the row through the centre, the left edge fades in: whiter
    # near the outline, full colour deeper inside
    edge = out.pixelColor(4, 80)
    mid = out.pixelColor(18, 80)
    core = out.pixelColor(50, 80)
    assert edge.green() > mid.green() > core.green() == 0


def test_rounded_corners_and_fit_modes():
    photo = _photo(200, 100)                              # 2:1
    item = ImagenItem(w_mm=40, h_mm=40, shape="rounded", radius_mm=10)
    out = _paint(item, photo)
    assert out.pixelColor(1, 1) == QColor(255, 255, 255)   # rounded away
    assert out.pixelColor(70, 20) == QColor(255, 0, 0)     # edge middle: photo
    # stretch: the whole 2:1 photo squashed into the square (red left half)
    item.shape = "rect"
    out = _paint(item, photo)
    assert out.pixelColor(70, 80) == QColor(255, 0, 0)
    assert out.pixelColor(90, 80) == QColor(0, 0, 255)
    # cover: the middle of the photo fills the square, cropped
    item.fit = "cover"
    out = _paint(item, photo)
    assert out.pixelColor(70, 80) == QColor(255, 0, 0)
    assert out.pixelColor(90, 80) == QColor(0, 0, 255)
    assert out.pixelColor(5, 80) == QColor(255, 0, 0)      # still photo at the side
    # contain: the photo sits letterboxed, paper above and below
    item.fit = "contain"
    out = _paint(item, photo)
    assert out.pixelColor(80, 8) == QColor(255, 255, 255)
    assert out.pixelColor(40, 80) == QColor(255, 0, 0)


def test_outline_and_roundtrip_and_cache():
    photo = _photo(100, 100)
    item = ImagenItem(w_mm=30, h_mm=30, shape="ellipse", border=True,
                      border_mm=2.0, border_color="#00ff00")
    out = _paint(item, photo)
    assert out.pixelColor(1, 60) == QColor(0, 255, 0)      # the outline, left
    a = composited_image(photo, item)
    b = composited_image(photo, item)
    assert a is b                                          # cached
    c = Composicion()
    c.images.append(ImagenItem(path="x.png", opacity=0.4, shape="rounded",
                               radius_mm=6, feather_mm=2, fit="cover",
                               border=True))
    back = Composicion.from_dict(c.to_dict()).images[0]
    assert (back.opacity, back.shape, back.radius_mm, back.feather_mm,
            back.fit, back.border) == (0.4, "rounded", 6, 2, "cover", True)
    legacy = Composicion.from_dict({"images": [{"path": "y.png"}]}).images[0]
    assert legacy.opacity == 1.0 and legacy.shape == "rect"


def test_the_panel_edits_the_image_look():
    from tests.test_composer_canvas import _FakeViewport
    from views.composer import ComposerWindow, ImageItem
    host = QWidget()
    host.viewport = _FakeViewport()
    composer = ComposerWindow(host)
    composer.comp.images.append(ImagenItem(x_mm=30, y_mm=30))
    composer._rebuild_canvas()
    item = next(it for it in composer.canvas.items() if isinstance(it, ImageItem))
    item.setSelected(True)
    composer.on_selection_changed()
    assert composer.props.currentIndex() == 3
    composer.img_shape.setCurrentIndex(composer.img_shape.findData("ellipse"))
    composer.img_feather.setValue(3.0)
    composer.img_fit.setCurrentIndex(composer.img_fit.findData("cover"))
    composer.img_opacity.setValue(60.0)
    m = item.model
    assert (m.shape, m.feather_mm, m.fit) == ("ellipse", 3.0, "cover")
    assert m.opacity == pytest.approx(0.6)
    assert not composer.img_radius.isEnabled()
    composer.img_shape.setCurrentIndex(composer.img_shape.findData("rounded"))
    assert composer.img_radius.isEnabled()
