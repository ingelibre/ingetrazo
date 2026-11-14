# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""@pacaeiro, #47 point 1: «Activate Paint tool. Press Alt and release it.
Icon changed but we're still on Paint mode.» The first Alt release hands
the keyboard to the menu bar, so the viewport never heard the next press:
every other tap the pointer stayed a bucket. Alt is now heard at
application level, wherever the key event lands."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenuBar  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

import pytest  # noqa: E402

from views.viewport import Viewport  # noqa: E402


@pytest.fixture(autouse=True)
def _only_this_test_s_viewports():
    """The Alt watcher tells every live viewport, and the first one in
    Paint takes the tap. A MainWindow an earlier file left alive (they are
    never destroyed, see scripts/pytest_batches.py) still in Paint took it
    and toggled ITS eyedropper button instead: the tap test failed in a
    batch and passed alone (Windows round 0.6.2). Each test hears only the
    viewports it builds; the others come back after it."""
    import weakref

    from views.viewport import _AltWatch
    Viewport(None)                      # the watcher exists from here on
    watch = _AltWatch._instance
    kept = watch._viewports
    watch._viewports = weakref.WeakSet()
    yield
    for vp in kept:
        watch._viewports.add(vp)


def _paint_viewport():
    from tools.paint import PaintTool
    # Windows closed by earlier tests linger in the Alt-tap watcher until
    # collected, and one still holding Paint could take the tap.
    import gc
    gc.collect()
    vp = Viewport(None)
    vp.flash_status = lambda *a, **k: None
    tool = PaintTool()
    tool.icon = "paint"                  # as MainWindow tags its tools
    vp.active_tool = tool
    return vp


def _key(target, press: bool):
    t = QEvent.KeyPress if press else QEvent.KeyRelease
    mods = Qt.AltModifier if press else Qt.NoModifier
    QApplication.sendEvent(target, QKeyEvent(t, Qt.Key_Alt, mods))


def test_alt_taps_on_the_menu_bar_still_reach_the_viewport():
    """The pointer follows the key even while the menu bar holds focus."""
    vp = _paint_viewport()
    shown = []
    vp._apply_tool_cursor = lambda: shown.append(vp._alt_down)
    bar = QMenuBar()                    # where the focus goes after a tap
    _key(bar, True)
    assert vp._alt_down is True
    _key(bar, False)
    assert vp._alt_down is False


def test_a_tap_toggles_the_eyedropper_and_it_stays():
    """The current convention (Marco: «se alterna con Alt, no es que se
    mantenga presionado»): tap = eyedropper on, it stays after the release;
    tap again = off."""
    from tools.paint import PaintTool
    PaintTool.sample_armed = False
    vp = _paint_viewport()
    bar = QMenuBar()
    try:
        _key(bar, True)
        _key(bar, False)
        assert PaintTool.sample_armed is True      # stays after the release
        _key(bar, True)
        _key(bar, False)
        assert PaintTool.sample_armed is False     # tapped again: off
    finally:
        PaintTool.sample_armed = False


def test_alt_tab_is_not_a_tap():
    """Alt+Tab all day (@pacaeiro, #26) must not arm the eyedropper."""
    from tools.paint import PaintTool
    PaintTool.sample_armed = False
    vp = _paint_viewport()
    bar = QMenuBar()
    try:
        _key(bar, True)
        QApplication.sendEvent(bar, QKeyEvent(QEvent.KeyPress, Qt.Key_Tab,
                                              Qt.AltModifier))
        _key(bar, False)
        assert PaintTool.sample_armed is False
    finally:
        PaintTool.sample_armed = False
