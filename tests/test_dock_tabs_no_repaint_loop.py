# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A window left alone paints nothing again.

The tray tab bars keep a gear and a «+» above their scroll arrows, placed
at every paint of the bar. They were raised there in turn, and each raise
restacked the two — a repaint, whose placing raised them again: the bar
and the window repainted at every turn of the event loop, for ever. On
screen it cost little until the window was covered: with the sheet
composer in front, each of those paints waited up to a second for the
display, and opening the composer took 38 s, adding a frame 40 s,
selecting one 20 s (0.6.1: 5 s, 0.02 s, 0.03 s). Here the window is
left alone and its tray tab bars must stay unpainted."""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QTabBar

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


class _Paints(QObject):
    def __init__(self, window):
        super().__init__()
        self.window, self.bars, self.window_paints = window, 0, 0

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Paint:
            if isinstance(obj, QTabBar) and obj.property("ingetrazo_watched"):
                self.bars += 1
            if obj is self.window:
                self.window_paints += 1
        return False


def test_a_window_left_alone_does_not_repaint_its_tray_tabs():
    from views.main_window import MainWindow
    app = QApplication.instance()
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    try:
        # Let it settle: building it paints, of course.
        for _ in range(40):
            app.processEvents()
            time.sleep(0.005)
        bars = [tb for tb in win.findChildren(QTabBar)
                if tb.property("ingetrazo_watched")]
        assert bars, "no tray tab bar to watch"
        spy = _Paints(win)
        app.installEventFilter(spy)
        try:
            for _ in range(60):
                app.processEvents()
                time.sleep(0.005)
        finally:
            app.removeEventFilter(spy)
        # Left alone: a stray paint or two at most, not one per turn.
        assert spy.bars <= 3, spy.bars
        assert spy.window_paints <= 3, spy.window_paints
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
