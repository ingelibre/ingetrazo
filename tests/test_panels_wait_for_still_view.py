# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Side panels wait for the view to settle before their deferred refresh
(night of 19-11): opening a group of the Plaza, the layer counts and the
in-model lists landed ~0.2 s inside the first orbit. While the camera moves
(or the middle button is held) the refresh waits; once it has been still
for a moment it runs, with what it always showed."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    try:
        yield w
    finally:
        w._saved_version = w.viewport.scene.version
        w.close()


def test_view_busy_follows_the_camera_and_the_middle_button(win):
    vp = win.viewport
    vp._note_camera()
    vp._cam_moved_t = None
    vp._note_camera()                       # unchanged: not a move
    assert vp._cam_moved_t is None and not vp.view_busy()
    vp.camera.yaw += math.radians(5)
    vp._note_camera()
    assert vp.view_busy()
    vp._cam_moved_t -= vp.VIEW_STILL_S + 0.01
    assert not vp.view_busy()
    vp._middle_drag_active = True
    assert vp.view_busy()
    vp._middle_drag_active = False
    assert not vp.view_busy()


def _layers(win):
    from views.layers_panel import LayersPanel
    return next(p for p in win.findChildren(LayersPanel))


def test_the_layer_counts_wait_while_the_view_moves(win, monkeypatch):
    vp = win.viewport
    panel = _layers(win)
    ran = []
    real = panel.update_counts
    monkeypatch.setattr(panel, "update_counts",
                        lambda: (ran.append(1), real())[1])
    busy = [True]
    monkeypatch.setattr(vp, "view_busy", lambda: busy[0])
    panel._count_timer.start(0)
    QTest.qWait(400)
    assert ran == [] and panel._count_timer.isActive()
    busy[0] = False
    QTest.qWait(300)
    assert ran == [1] and not panel._count_timer.isActive()


def test_the_in_model_lists_wait_while_the_view_moves(win, monkeypatch):
    from views.tray import ComponentsPanel
    vp = win.viewport
    comps = next(p for p in win.findChildren(ComponentsPanel))
    ran = []
    monkeypatch.setattr(comps, "refresh_in_model", lambda: ran.append("c"))
    monkeypatch.setattr(comps, "_draw_visible_thumbs",
                        lambda: ran.append("t"))
    busy = [True]
    monkeypatch.setattr(vp, "view_busy", lambda: busy[0])
    from PySide6.QtCore import QTimer
    comps._in_model_timer = QTimer(comps)
    comps._in_model_timer.setSingleShot(True)
    comps._in_model_timer.timeout.connect(comps._in_model_when_still)
    comps._in_model_timer.start(0)
    comps._schedule_thumbs()
    QTest.qWait(400)
    assert ran == []
    busy[0] = False
    QTest.qWait(300)
    assert sorted(ran) == ["c", "t"]


def test_a_panel_runs_at_once_when_the_view_is_still(win):
    from views.viewport import wait_for_still_view
    from PySide6.QtCore import QTimer
    t = QTimer()
    t.setSingleShot(True)
    win.viewport._cam_moved_t = None
    assert wait_for_still_view(win.viewport, t) and not t.isActive()
    assert wait_for_still_view(None, t)


def test_the_pointer_in_the_view_counts_as_busy(win):
    import time
    vp = win.viewport
    vp._cam_moved_t = None
    vp._hand_t = time.monotonic()
    assert vp.view_busy()
    vp._hand_t -= vp.VIEW_STILL_S + 0.01
    assert not vp.view_busy()


def test_a_panel_never_waits_past_the_cap(win, monkeypatch):
    import views.viewport as vv
    from views.viewport import wait_for_still_view
    from PySide6.QtCore import QTimer
    monkeypatch.setattr(win.viewport, "view_busy", lambda: True)
    t = QTimer()
    t.setSingleShot(True)
    assert not wait_for_still_view(win.viewport, t)
    t.stop()
    t._waiting_since -= vv.WAIT_MAX_S + 0.1
    assert wait_for_still_view(win.viewport, t)
    assert t._waiting_since is None          # the next wait starts afresh
    assert not wait_for_still_view(win.viewport, t)
