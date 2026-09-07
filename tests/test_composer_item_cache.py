# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet items keep a paint cache, so dragging one is a blit and not a
redraw of every 300-dpi frame render (Marco, 2026-09-07: «siento algo de lag
en composiciones cuando arrastro un objeto»). Measured on his Yanque sheet
with four frames: 11.2 → 1.1 ms per mouse move.

The cache is dropped for an item that would need a pixmap bigger than the
budget (zoomed right in), and anything that changes WHAT an item draws has
to go through ``refresh_items`` — a cached item does not repaint just
because its region was invalidated.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QGraphicsItem, QWidget

from core.composition import Cajetin, TextoItem
from tests.test_composer_canvas import _FakeViewport
from views.composer import (_ITEM_CACHE_MAX_PX, ComposerWindow, FrameItem,
                            _SheetItem)

_app = QApplication.instance() or QApplication([])
V = QVector3D


def _composer():
    host = QWidget()
    host.viewport = _FakeViewport()
    host.viewport.scene.mesh.add_face(
        [V(0, 0, 0), V(6, 0, 0), V(6, 0, 3), V(0, 0, 3)])
    comp = ComposerWindow(host)
    comp.comp.cajetin = Cajetin()
    comp.comp.texts.append(TextoItem(text="Lámina"))
    comp._rebuild_canvas()
    return comp, host


def _items(comp):
    return [it for it in comp.canvas.items() if isinstance(it, _SheetItem)]


def test_every_item_is_painted_through_a_cache():
    comp, _host = _composer()
    try:
        items = _items(comp)
        assert items and any(isinstance(it, FrameItem) for it in items)
        assert all(it.cacheMode() == QGraphicsItem.DeviceCoordinateCache
                   for it in items)
    finally:
        comp.close()


def test_zooming_right_in_gives_the_cache_up_and_zooming_out_takes_it_back():
    comp, _host = _composer()
    try:
        frame = comp.comp.frames[0]
        frame.w_mm, frame.h_mm = 380.0, 270.0        # the whole sheet
        comp._rebuild_canvas()
        big = next(it for it in _items(comp) if isinstance(it, FrameItem))
        assert big.cacheMode() == QGraphicsItem.DeviceCoordinateCache
        comp.set_zoom(1600.0)
        scale = comp._view.transform().m11()
        r = big.boundingRect()
        assert (r.width() * scale) * (r.height() * scale) > _ITEM_CACHE_MAX_PX
        assert big.cacheMode() == QGraphicsItem.NoCache      # over budget
        comp.set_zoom(100.0)
        assert big.cacheMode() == QGraphicsItem.DeviceCoordinateCache
    finally:
        comp.close()


def test_refresh_items_repaints_the_items_themselves():
    """The cached items must be told when their CONTENT changed; the three
    callers of that are the stale badge, the bound scale labels and the
    terrain profiles."""
    comp, _host = _composer()
    try:
        seen = []
        for it in _items(comp):
            it.update = lambda *a, _it=it: seen.append(_it)   # noqa: E731
        comp.refresh_items()
        assert len(seen) == len(_items(comp))
    finally:
        comp.close()


def test_the_stale_badge_reaches_a_cached_frame():
    comp, _host = _composer()
    try:
        seen = []
        for it in _items(comp):
            it.update = lambda *a, _it=it: seen.append(_it)   # noqa: E731
        comp._on_model_version(comp._last_model_version + 1)
        assert comp.is_stale(comp.comp.frames[0])
        assert any(isinstance(it, FrameItem) for it in seen)
    finally:
        comp.close()
