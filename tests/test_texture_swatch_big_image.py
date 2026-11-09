# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #460 (@tomlai-git): an image added as a texture painted fine but
showed no swatch in the Materials panel. ``QImage(path)`` refuses images
over Qt's allocation limit (256 MB by default); the viewport lifts it, the
swatch did not."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage, QImageReader  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_an_image_over_the_allocation_limit_still_gets_a_swatch(tmp_path):
    from views.tray import _texture_pixmap
    path = tmp_path / "artwork.png"
    img = QImage(1000, 1000, QImage.Format_RGB32)
    img.fill(QColor(200, 30, 30))
    assert img.save(str(path))
    old = QImageReader.allocationLimit()
    QImageReader.setAllocationLimit(1)        # 1 MB: the image is ~4 MB
    try:
        assert QImage(str(path)).isNull()     # what used to happen
        pm = _texture_pixmap(path)
        assert pm is not None and not pm.isNull()
        assert QImageReader.allocationLimit() == 1   # the limit is put back
    finally:
        QImageReader.setAllocationLimit(old)


def test_an_unreadable_file_gives_no_swatch(tmp_path):
    from views.tray import _texture_pixmap
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not an image")
    assert _texture_pixmap(bad) is None


def test_a_translucent_texture_swatch_is_split_diagonally(tmp_path):
    from views.tray import _texture_pixmap
    path = tmp_path / "red.png"
    img = QImage(44, 44, QImage.Format_RGB32)
    img.fill(QColor(255, 0, 0))
    assert img.save(str(path))

    image = _texture_pixmap(path, opacity=0.25).toImage()
    translucent_half = image.pixelColor(5, 5)
    opaque_half = image.pixelColor(38, 38)
    # Above the rising diagonal: texture at its real opacity over the
    # checkerboard. Below it: the same texture opaque.
    assert translucent_half.green() > 20
    assert opaque_half.red() > 240 and opaque_half.green() < 10
    assert image.pixelColor(22, 22) != translucent_half


def test_texture_menu_icons_use_the_same_diagonal_preview(tmp_path):
    from views.outliner import _paint_icon
    path = tmp_path / "blue.png"
    img = QImage(44, 44, QImage.Format_RGB32)
    img.fill(QColor(0, 0, 255))
    assert img.save(str(path))

    image = _paint_icon({"texture": {"path": str(path)},
                         "opacity": 0.25}, 44).pixmap(44, 44).toImage()
    assert image.pixelColor(5, 5).red() > 20
    opaque_half = image.pixelColor(38, 38)
    assert opaque_half.blue() > 240 and opaque_half.red() < 10
