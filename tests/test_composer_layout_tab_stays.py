# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Editing the page from the Layout tab (border corner radius, one spinbox
click at a time) must not throw the panel over to the item-properties tab:
the rebuild restores the same selection, and only a NEW selection jumps
(Marco, 2026-09-14)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from tests.test_composer_cota_cadena import _FakeViewport
from views.composer import ComposerWindow, FrameItem

_app = QApplication.instance() or QApplication([])


def _composer():
    host = QWidget()
    host.viewport = _FakeViewport()
    composer = ComposerWindow(host)
    composer.comp.border = True
    composer._rebuild_canvas()
    return composer


def _frame_item(composer):
    return next(it for it in composer.canvas.items() if isinstance(it, FrameItem))


def test_a_page_edit_from_the_layout_tab_keeps_the_layout_tab():
    composer = _composer()
    _frame_item(composer).setSelected(True)       # a real click: jumps
    assert composer._tabs.currentIndex() == 2
    composer._tabs.setCurrentIndex(0)             # back to Layout
    composer.border_radius.setValue(composer.border_radius.value() + 0.5)
    assert composer.comp.border_radius_mm == composer.border_radius.value()
    assert composer._tabs.currentIndex() == 0     # still on Layout
    assert _frame_item(composer).isSelected()     # selection survived


def test_selecting_another_item_still_jumps_to_properties():
    composer = _composer()
    _frame_item(composer).setSelected(True)
    composer._tabs.setCurrentIndex(0)
    composer.canvas.clearSelection()
    _frame_item(composer).setSelected(True)       # a fresh selection
    assert composer._tabs.currentIndex() == 2
