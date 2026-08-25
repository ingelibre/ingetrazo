# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Esc escalates: value buffer → sticky constraints (axis lock / reference)
→ in-progress tool action → selection. The axis-lock release is the "Esc
should stop constraining" report: the window-level Esc QAction is what
actually fires, and it never dropped the arrow-key lock."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication(sys.argv[:1])


@pytest.fixture
def window():
    from views.main_window import MainWindow
    win = MainWindow()
    yield win
    # A dirty window pops a modal save prompt on close, which hangs offscreen.
    win._saved_version = win.viewport.scene.version
    win.close()


class _BusyTool:
    """Quacks busy for Viewport._tool_busy (an unfinished chain)."""
    start_point = object()
    cancelled = False

    def on_cancel(self, viewport):
        self.cancelled = True

    def on_deactivate(self, viewport):
        pass


def test_esc_releases_axis_lock_first(window):
    vp = window.viewport
    vp.axis_lock = "x"
    tool = _BusyTool()
    vp.active_tool = tool

    window._cancel_tool()                    # 1st Esc: drop the lock only
    assert vp.axis_lock is None
    assert tool.cancelled is False           # the chain in progress survives

    window._cancel_tool()                    # 2nd Esc: now cancel the action
    assert tool.cancelled is True
    vp.active_tool = None


def test_esc_releases_reference_mode(window):
    vp = window.viewport
    vp.reference_edge = object()
    vp.reference_mode = "parallel"
    window._cancel_tool()
    assert vp.reference_mode is None and vp.reference_edge is None


def test_esc_clears_value_buffer_before_constraints(window):
    vp = window.viewport
    vp._value_buffer = "2.5"
    vp.axis_lock = "z"
    window._cancel_tool()                    # 1st Esc: clear typed value
    assert vp._value_buffer == ""
    assert vp.axis_lock == "z"               # lock survives that press
    window._cancel_tool()                    # 2nd Esc: release the lock
    assert vp.axis_lock is None


def test_esc_without_constraints_still_clears_selection(window):
    vp = window.viewport
    f = vp.scene.mesh.add_face(_square())
    vp.scene.selection.add(f)
    window._cancel_tool()
    assert not vp.scene.selection


def test_viewport_release_constraints_reports_whether_it_did(window):
    vp = window.viewport
    assert vp.release_constraints() is False
    vp.axis_lock = "y"
    assert vp.release_constraints() is True
    assert vp.release_constraints() is False


def _square():
    from PySide6.QtGui import QVector3D
    return [QVector3D(0, 0, 0), QVector3D(1, 0, 0),
            QVector3D(1, 1, 0), QVector3D(0, 1, 0)]
