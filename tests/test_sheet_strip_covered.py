# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The model window's sheet strip waits while the composer covers it.

Each sheet tab clicked in the composer renamed the model window's strip
(it shows the last sheet opened), and repainting a window the composer
hides waits on the compositor: ~1 s, twice, for every change of sheet in
the final plaza (19-11; 0.1 s with the strip left alone). The strip now
catches up when the model window comes back; side by side it follows at
once."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from PySide6.QtCore import QEvent, QRect
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _fake(composer=None, active=False, rect=QRect(0, 0, 1000, 800),
          minimized=False, visible=True):
    return SimpleNamespace(
        _composer=composer, isActiveWindow=lambda: active,
        isMinimized=lambda: minimized, isVisible=lambda: visible,
        frameGeometry=lambda: rect)


def _composer(rect, active=True, visible=True, minimized=False):
    return SimpleNamespace(isVisible=lambda: visible,
                           isMinimized=lambda: minimized,
                           isActiveWindow=lambda: active,
                           frameGeometry=lambda: rect)


def _covered(win):
    from views.main_window import MainWindow
    return MainWindow._covered_by_composer(win)


def test_covered_only_when_the_composer_is_in_use_over_it():
    over = _composer(QRect(0, 0, 1000, 800))
    assert _covered(_fake(over))
    # Nearly all of it (a title bar's offset) still counts.
    assert _covered(_fake(_composer(QRect(0, 30, 1000, 800))))
    # Side by side, on another monitor, or half over it: it shows.
    assert not _covered(_fake(_composer(QRect(1000, 0, 1000, 800))))
    assert not _covered(_fake(_composer(QRect(500, 0, 1000, 800))))
    # The model window in use, the composer hidden, minimized or idle.
    assert not _covered(_fake(over, active=True))
    assert not _covered(_fake(_composer(QRect(0, 0, 1000, 800), visible=False)))
    assert not _covered(_fake(_composer(QRect(0, 0, 1000, 800), minimized=True)))
    assert not _covered(_fake(_composer(QRect(0, 0, 1000, 800), active=False)))
    assert not _covered(_fake(None))
    # The model window minimized under the composer: nobody sees it.
    assert _covered(_fake(_composer(QRect(5000, 0, 10, 10)), minimized=True))


def test_the_strip_waits_and_catches_up():
    from core.composition import Composicion as Composition
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        sc = win.viewport.scene
        sc.compositions.extend([Composition(name="L-01"),
                                Composition(name="L-02")])
        calls = []
        real = win._sheet_tabs.refresh
        win._sheet_tabs.refresh = lambda *a, **k: (calls.append(a), real(*a, **k))
        covered = [True]
        win._covered_by_composer = lambda: covered[0]
        win._refresh_sheet_tabs()
        assert calls == [] and win._sheet_strip_pending
        # Still covered: an activation change elsewhere does not repaint.
        win.changeEvent(QEvent(QEvent.ActivationChange))
        assert calls == []
        covered[0] = False
        win.changeEvent(QEvent(QEvent.ActivationChange))
        assert len(calls) == 1 and not win._sheet_strip_pending
        # Nothing pending: a later activation leaves the strip alone.
        win.changeEvent(QEvent(QEvent.ActivationChange))
        assert len(calls) == 1
        # Uncovered: the strip follows at once.
        win._refresh_sheet_tabs()
        assert len(calls) == 2
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_covered_model_window_does_not_paint():
    """While the composer covers it the model window paints nothing; it
    paints again once uncovered (a sheet's first render repainted its
    toolbars six times, ~1 s each, 19-11)."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        covered = [True]
        win._covered_by_composer = lambda: covered[0]
        win.sync_covered_paint()
        assert not win.updatesEnabled()
        win.sync_covered_paint()                    # idempotent
        assert not win.updatesEnabled()
        covered[0] = False
        win.changeEvent(QEvent(QEvent.ActivationChange))
        assert win.updatesEnabled()
        # The viewport's repaint waits while covered and comes back after.
        covered[0] = True
        win.update_viewport_when_seen()
        assert win._viewport_pending
        covered[0] = False
        win.changeEvent(QEvent(QEvent.WindowStateChange))
        assert not win._viewport_pending and win.updatesEnabled()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_composer_tells_the_model_window():
    """Moving, resizing, hiding or (de)activating the composer re-asks
    whether the model window is covered."""
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    win = MainWindow()
    comp = None
    try:
        comp = ComposerWindow(win)
        asked = []
        win.sync_covered_paint = lambda: asked.append(1)
        from PySide6.QtCore import QPoint, QSize
        from PySide6.QtGui import QMoveEvent, QResizeEvent, QHideEvent
        comp.moveEvent(QMoveEvent(QPoint(5, 5), QPoint(0, 0)))
        comp.resizeEvent(QResizeEvent(QSize(800, 600), QSize(700, 500)))
        comp.hideEvent(QHideEvent())
        comp.changeEvent(QEvent(QEvent.ActivationChange))
        assert len(asked) == 4
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
