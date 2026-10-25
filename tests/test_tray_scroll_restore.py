# SPDX-License-Identifier: GPL-3.0-or-later
"""A deferred scroll restore must not touch a scroll bar that was deleted."""
import shiboken6
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QScrollBar

from views.tray import _restore_scrollbar_later


def test_restore_skips_a_deleted_bar():
    QApplication.instance() or QApplication([])
    bar = QScrollBar()
    bar.setRange(0, 100)
    _restore_scrollbar_later(bar, 40)
    shiboken6.delete(bar)
    assert not shiboken6.isValid(bar)
    QCoreApplication.processEvents()      # fires the timer: must not raise
    QCoreApplication.processEvents()


def test_restore_sets_a_live_bar():
    QApplication.instance() or QApplication([])
    bar = QScrollBar()
    bar.setRange(0, 100)
    _restore_scrollbar_later(bar, 40)
    assert bar.value() == 0
    QCoreApplication.processEvents()
    QCoreApplication.processEvents()
    assert bar.value() == 40
