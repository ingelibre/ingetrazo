# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A toolbar repack does not leave a maximized window small (#800).

Started from Explorer on Windows, an extension's toolbars re-seated the
bars while Qt still held the normal size; the new minimum height made Qt
resize the window, which dropped the maximized state, and Windows put the
flag back on a window left 1296 × 901 in the corner. After a repack of a
maximized window, ``_keep_maximized`` re-maximizes one that no longer
fills its screen — and leaves a window that does alone."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _window(monkeypatch, frame, state):
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    calls = []
    monkeypatch.setattr(win, "frameGeometry", lambda: frame)
    monkeypatch.setattr(win, "windowState", lambda: state)
    monkeypatch.setattr(win, "setWindowState", lambda s: calls.append(s))
    return win, calls


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_a_maximized_window_left_small_is_maximized_again(monkeypatch):
    win, calls = _window(monkeypatch, QRect(0, 0, 1, 1), Qt.WindowMaximized)
    avail = win.screen().availableGeometry()
    small = QRect(avail.x() - 8, avail.y() - 8,
                  int(avail.width() * 0.6), int(avail.height() * 0.6))
    monkeypatch.setattr(win, "frameGeometry", lambda: small)
    win._keep_maximized()
    assert calls == [Qt.WindowNoState, Qt.WindowMaximized]
    _close(win)


def test_a_window_that_fills_the_screen_is_left_alone(monkeypatch):
    from views.main_window import MainWindow  # noqa: F401
    win, calls = _window(monkeypatch, QRect(0, 0, 1, 1), Qt.WindowMaximized)
    monkeypatch.setattr(win, "frameGeometry",
                        lambda: win.screen().availableGeometry())
    win._keep_maximized()
    assert calls == []
    _close(win)


def test_the_repack_asks_for_the_check_only_on_windows(monkeypatch):
    import sys
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    asked = []
    monkeypatch.setattr(win, "windowState", lambda: Qt.WindowMaximized)
    monkeypatch.setattr(win, "_keep_maximized", lambda: asked.append(1))
    monkeypatch.setattr(sys, "platform", "linux")
    win._pack_toolbars()
    for _ in range(3):
        _app.processEvents()
    assert asked == []
    monkeypatch.setattr(sys, "platform", "win32")
    win._pack_toolbars()
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(700, loop.quit)
    loop.exec()
    assert len(asked) == 2
    _close(win)
