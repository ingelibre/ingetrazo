# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The composer's selection survives a canvas rebuild.

Every rebuild (the auto-render pass after a scale or size edit, a page
change, a title-block field…) recreates the canvas items, and the selection
lived on the items: each property change in the panel meant clicking the
frame again before the next one (Marco, 2026-09-05)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QWidget

from tests.test_composer_canvas import _FakeViewport
from views.composer import CajetinItem, ComposerWindow, FrameItem

_app = QApplication.instance() or QApplication([])


def _composer():
    host = QWidget()
    host.viewport = _FakeViewport()
    V = QVector3D
    host.viewport.scene.mesh.add_face(
        [V(0, 0, 0), V(6, 0, 0), V(6, 0, 3), V(0, 0, 3)])
    composer = ComposerWindow(host)
    return composer, host


def _item_for(composer, model):
    return next(it for it in composer.canvas.items()
                if getattr(it, "model", None) is model)


def test_the_selected_frame_stays_selected_through_a_rebuild():
    composer, host = _composer()
    frame = composer.comp.frames[0]
    _item_for(composer, frame).setSelected(True)
    assert composer._selected_item().model is frame

    composer._rebuild_canvas()                    # what every property edit ends in
    assert isinstance(composer._selected_item(), FrameItem)
    assert composer._selected_item().model is frame

    composer._stale.add(id(frame))                # the auto-render pass after a scale change
    composer._auto_render = True
    composer._auto_render_stale()
    assert composer._selected_item() is not None
    assert composer._selected_item().model is frame


def test_the_selected_title_block_stays_selected_too():
    composer, host = _composer()
    composer._on_add_cajetin()
    composer._rebuild_canvas()                    # the add is a deferred rebuild
    caj = composer.comp.cajetin
    _item_for(composer, caj).setSelected(True)
    composer.caj_w.setValue(220.0)                # a panel edit, like Marco's
    composer._rebuild_canvas()
    assert isinstance(composer._selected_item(), CajetinItem)
    assert composer._selected_item().model is caj
