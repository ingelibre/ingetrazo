# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The status bar's measurement and coordinate boxes hold their widest
width while their number runs (views/status_hold.py): a new number asks
the bar for no layout, so the window under it is not repainted with it
(19-11, Line in a group of the Plaza: ~5 ms in one frame of six)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow
from PySide6.QtTest import QTest

from views.status_hold import QWIDGETSIZE_MAX, is_held, release, set_text_held


class _Layouts(QObject):
    def __init__(self):
        super().__init__()
        self.n = 0

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.LayoutRequest:
            self.n += 1
        return False


def _bar():
    win = QMainWindow()
    lab = QLabel("")
    lab.setMinimumWidth(130)
    win.statusBar().addPermanentWidget(lab)
    win.resize(800, 300)
    win.show()
    QTest.qWait(30)
    spy = _Layouts()
    win.statusBar().installEventFilter(spy)
    return win, lab, spy


def _settle():
    for _ in range(3):
        QApplication.processEvents()


def test_a_running_number_asks_the_bar_for_no_layout():
    win, lab, spy = _bar()
    set_text_held(lab, "1.00 m", 130)            # takes hold: one layout
    _settle()
    assert is_held(lab) and lab.width() == 130
    spy.n = 0
    for k in range(2, 30):
        set_text_held(lab, f"{k}.{k:02d} m", 130)
        _settle()
    assert lab.text() == "29.29 m"
    assert spy.n == 0, "a new number laid the bar out again"
    # The same with a plain setText: the bar is laid out again each time.
    release(lab, 130)
    _settle()
    spy.n = 0
    for k in range(2, 6):
        lab.setText(f"{k}.{k:02d} cm")
        _settle()
    assert spy.n > 0
    win.close()


def test_it_grows_never_shrinks_and_lets_go_on_an_empty_text():
    win, lab, _spy = _bar()
    set_text_held(lab, "1 m", 130)
    long = "123456789.123456789 m (and more)"
    set_text_held(lab, long, 130)
    _settle()
    wide = lab.width()
    assert wide >= lab.sizeHint().width() > 130
    set_text_held(lab, "2 m", 130)
    _settle()
    assert lab.width() == wide and lab.text() == "2 m"     # kept
    set_text_held(lab, "", 130)
    _settle()
    assert not is_held(lab)
    assert lab.minimumWidth() == 130 and lab.maximumWidth() == QWIDGETSIZE_MAX
    win.close()


def test_a_label_not_laid_out_just_takes_the_text():
    lab = QLabel("")
    set_text_held(lab, "3 m", 130)
    assert lab.text() == "3 m" and not is_held(lab)


def test_the_main_window_box_lets_go_when_the_tool_changes():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.show()
        QTest.qWait(50)
        win._activate_tool("line")
        QTest.qWait(10)
        box = win._vcb_value
        assert box.isVisible()
        win._on_measurement("1.00 m")
        assert is_held(box) and box.text() == "1.00 m"
        win._on_measurement("12.00 m")
        assert is_held(box) and box.text() == "12.00 m"
        win._activate_tool("select")
        win._refresh_vcb()
        assert not is_held(box)
        assert box.minimumWidth() == 130
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
