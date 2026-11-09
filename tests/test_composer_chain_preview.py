# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Chain / baseline dimension preview: the rubber band is a ghost of the cota
the next click places (extension lines, ends, live value), and Shift
straightens the run at once — on the key, without moving the mouse."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from tests.test_composer_cota_cadena import _composer
from views.composer import _CotaGhostItem

_app = QApplication.instance() or QApplication([])


def _ghost(view):
    if view._preview is None:
        return None
    found = [c for c in view._preview.childItems()
             if isinstance(c, _CotaGhostItem)]
    assert len(found) <= 1
    return found[0].model if found else None


def _chain_view():
    composer, host = _composer()
    composer._set_tool_mode("cota_cadena")
    return composer, composer._view, host


def _same(ghost, real):
    for name in ("x_mm", "y_mm", "dx_mm", "dy_mm", "sep_mm"):
        assert getattr(real, name) == pytest.approx(getattr(ghost, name))
    assert real.axis == ghost.axis


class TestGhostPreview:
    def test_each_phase_shows_the_cota_the_click_will_place(self):
        composer, view, _host = _chain_view()
        view._chain_click(QPointF(20, 50), None)
        view._update_chain_preview(QPointF(50, 50))
        assert _ghost(view).dx_mm == pytest.approx(30)   # value shown live
        view._chain_click(QPointF(50, 50), None)
        view._update_chain_preview(QPointF(35, 40))      # the offset phase
        ghost = _ghost(view)
        view._chain_click(QPointF(35, 40), None)
        _same(ghost, composer.comp.cotas[0])
        view._update_chain_preview(QPointF(90, 50))      # the next segment
        ghost = _ghost(view)
        view._chain_click(QPointF(90, 50), None)
        _same(ghost, composer.comp.cotas[1])

    def test_a_forced_horizontal_offset_previews_horizontal(self):
        # The old preview drew the line parallel to the DIAGONAL a→b while
        # the cota placed was horizontal.
        composer, view, _host = _chain_view()
        view._chain_click(QPointF(20, 50), None)
        view._chain_click(QPointF(50, 60), None)
        view._track(QPointF(35, 35), Qt.ShiftModifier)
        ghost = _ghost(view)
        assert ghost.axis == "h"
        view._chain_click(QPointF(35, 35), None)
        _same(ghost, composer.comp.cotas[0])

    def test_the_ghost_goes_with_the_run(self):
        composer, view, _host = _chain_view()
        view._chain_click(QPointF(20, 50), None)
        view._chain_click(QPointF(50, 50), None)
        view._chain_click(QPointF(35, 40), None)
        view._update_chain_preview(QPointF(90, 50))
        view.viewport().grab()                           # paints without error
        view._chain_click(QPointF(90, 50), None)
        view._chain_click(QPointF(90, 50), None)         # ends the chain
        assert not any(isinstance(i, _CotaGhostItem)
                       for i in view.scene().items())


class TestShiftAtOnce:
    def test_the_shift_key_straightens_and_frees_without_a_mouse_move(self):
        _composer_, view, _host = _chain_view()
        view._chain_click(QPointF(20, 50), None)
        view._last_raw = QPointF(50, 60)
        view._track(view._last_raw, Qt.NoModifier)
        assert _ghost(view).axis == ""
        view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Shift,
                                     Qt.ShiftModifier))
        assert _ghost(view).axis == "h"
        view.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, Qt.Key_Shift,
                                       Qt.NoModifier))
        assert _ghost(view).axis == ""

    def test_the_offset_phase_follows_the_cursor_like_dimlinear(self):
        _composer_, view, _host = _chain_view()
        view._chain_click(QPointF(20, 50), None)
        view._chain_click(QPointF(50, 60), None)
        view._track(QPointF(35, 30), Qt.ShiftModifier)   # pulled out above
        assert view._chain_axis == "h"
        view._track(QPointF(80, 55), Qt.ShiftModifier)   # pulled out right
        assert view._chain_axis == "v"
        view._track(QPointF(35, 30), Qt.NoModifier)      # released: free
        assert view._chain_axis == ""

    def test_a_straight_run_stays_on_its_line(self):
        composer, view, _host = _chain_view()
        view._chain_click(QPointF(20, 50), None)
        view._chain_click(QPointF(50, 60), None)
        view._track(QPointF(35, 30), Qt.ShiftModifier)
        view._chain_click(QPointF(35, 30), None)
        assert composer.comp.cotas[0].axis == "h"
        view._track(QPointF(95, 90), Qt.NoModifier)
        assert view._chain_axis == "h"
        view._track(QPointF(95, 90), Qt.ShiftModifier)
        assert view._chain_axis == "h"

    def test_a_free_run_still_straightens_one_segment_live(self):
        _composer_, view, _host = _chain_view()
        view._chain_click(QPointF(20, 50), None)
        view._chain_click(QPointF(50, 50), None)
        view._chain_click(QPointF(35, 40), None)         # placed free
        view._track(QPointF(90, 58), Qt.ShiftModifier)
        assert view._chain_axis == "h"
        view._track(QPointF(90, 58), Qt.NoModifier)
        assert view._chain_axis == ""
