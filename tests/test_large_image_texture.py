# SPDX-License-Identifier: GPL-3.0-or-later
"""Large imported scans remain visible without replacing their source file."""
from __future__ import annotations

import hashlib
import struct
import zlib

from PySide6.QtGui import QImage, QImageReader

from views.viewport._support import _decoded_texture


def _png_chunk(kind, data):
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data)))


def _large_rgb_png(path):
    # A real PNG over Qt's 256 MiB decoded-image limit, written a row at a
    # time so the fixture itself never allocates hundreds of megabytes.
    width, height = 9000, 8500
    row = b"\0" + b"\xff\xff\xff" * width
    compressor = zlib.compressobj(1)
    data = bytearray()
    for _ in range(height):
        data.extend(compressor.compress(row))
    data.extend(compressor.flush())
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                         8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", data)
        + _png_chunk(b"IEND", b""))


def test_scan_above_qt_limit_decodes_for_display_and_keeps_the_original(
        tmp_path):
    path = tmp_path / "first-floor.png"
    _large_rgb_png(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    previous = QImageReader.allocationLimit()
    try:
        QImageReader.setAllocationLimit(256)
        assert QImage(str(path)).isNull()  # the old renderer's blank image
        result = _decoded_texture(str(path))
        assert result is not None
        image, cutout = result
        assert (image.width(), image.height()) == (8192, 7737)
        assert image.pixelColor(0, 0).alpha() == 255
        assert not cutout
        assert QImageReader.allocationLimit() == 256
    finally:
        QImageReader.setAllocationLimit(previous)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
