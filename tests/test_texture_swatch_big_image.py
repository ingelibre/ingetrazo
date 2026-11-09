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
