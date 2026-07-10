# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""TileFetcher (Track G, G1): cache-first behaviour and the zoom guard,
exercised without touching the network."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtCore import Qt

from georef.tiles import PRESETS, TileCache
from georef.tile_fetcher import TileFetcher, default_cache_dir


_app = QGuiApplication.instance() or QGuiApplication([])


def _png_bytes(color=Qt.GlobalColor.red) -> bytes:
    img = QImage(4, 4, QImage.Format.Format_RGB32)
    img.fill(color)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def test_cache_hit_returns_image_synchronously(tmp_path):
    cache = TileCache(tmp_path)
    cache.put("osm", 5, 6, 7, _png_bytes())
    fetcher = TileFetcher(cache)

    got = fetcher.request(PRESETS["osm"], 5, 6, 7)
    assert got is not None
    assert not got.isNull()
    assert got.width() == 4 and got.height() == 4


def test_zoom_out_of_range_refused(tmp_path):
    fetcher = TileFetcher(TileCache(tmp_path))
    osm = PRESETS["osm"]
    assert fetcher.request(osm, 0, 0, osm.max_zoom + 1) is None
    assert fetcher.request(osm, 0, 0, -1) is None


def test_cache_miss_returns_none_and_starts_inflight(tmp_path):
    # No network in tests: a miss returns None and registers an in-flight
    # request (which we immediately cancel so nothing actually hits the wire).
    fetcher = TileFetcher(TileCache(tmp_path))
    got = fetcher.request(PRESETS["osm"], 1, 1, 5)
    assert got is None
    assert len(fetcher._inflight) == 1
    fetcher.cancel_all()
    assert fetcher._inflight == {}


def test_duplicate_request_coalesces(tmp_path):
    fetcher = TileFetcher(TileCache(tmp_path))
    fetcher.request(PRESETS["osm"], 2, 2, 5)
    fetcher.request(PRESETS["osm"], 2, 2, 5)
    assert len(fetcher._inflight) == 1
    fetcher.cancel_all()


def test_default_cache_dir_ends_in_tiles():
    assert default_cache_dir().name == "tiles"


def test_downloads_are_capped_and_queued(tmp_path):
    # Asking for many tiles at once must not start them all — only up to the
    # concurrency limit run; the rest queue (prevents the network flood/hang).
    fetcher = TileFetcher(TileCache(tmp_path))
    osm = PRESETS["osm"]
    for x in range(30):
        fetcher.request(osm, x, 0, 5)
    assert len(fetcher._inflight) == fetcher._MAX_INFLIGHT
    assert len(fetcher._queue) == 30 - fetcher._MAX_INFLIGHT
    fetcher.cancel_all()
    assert fetcher._inflight == {} and fetcher._queue == []
