# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The wheel over the composer's item properties scrolls the panel; a field
answers it only when it has the focus (#1163)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPoint, QPointF, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication,
                               QComboBox, QScrollArea, QSlider)

_app = QApplication.instance() or QApplication([])


def _settle(ms=40):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _composer(monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    win._show_new_sheet()
    return win, win._composer


def _close(win):
    win._composer.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def _notch(widget, delta=-120):
    """A real wheel notch over the widget, through its window: only those
    make Qt walk up to the parents, as it does for the mouse."""
    window = widget.window()
    point = widget.mapTo(window, widget.rect().center())
    QTest.wheelEvent(window.windowHandle(), QPointF(point), QPoint(0, delta))
    _settle()


def _field_in_sight(comp, kind):
    """The frame's properties in a short panel, which then has to scroll,
    and a field of them under the pointer."""
    comp.show()
    _settle()
    comp._tabs.setCurrentWidget(comp.props)
    comp.props.setCurrentIndex(1)
    comp.props.setFixedHeight(180)
    _settle(80)
    scroll = comp.props.currentWidget()
    assert isinstance(scroll, QScrollArea)
    bar = scroll.verticalScrollBar()
    assert bar.maximum() > 0
    area = scroll.viewport().rect()
    for field in scroll.findChildren(kind):
        centre = field.mapTo(scroll.viewport(), field.rect().center())
        if field.isVisible() and field.isEnabled() and area.contains(centre):
            if kind is QComboBox and field.count() < 2:
                continue
            if kind is QAbstractSpinBox:
                field.setValue((field.minimum() + field.maximum()) / 2)
            return bar, field
    raise AssertionError(f"no {kind.__name__} in sight")


def test_the_wheel_over_a_spin_box_scrolls_the_panel(monkeypatch):
    win, comp = _composer(monkeypatch)
    try:
        bar, spin = _field_in_sight(comp, QAbstractSpinBox)
        before = spin.value()
        assert bar.value() == 0
        _notch(spin)
        assert bar.value() > 0                  # the panel moved ...
        assert spin.value() == before           # ... and the field did not
        assert not spin.hasFocus()              # nor took the focus
    finally:
        _close(win)


def test_the_wheel_over_a_combo_scrolls_the_panel(monkeypatch):
    win, comp = _composer(monkeypatch)
    try:
        bar, combo = _field_in_sight(comp, QComboBox)
        combo.setCurrentIndex(0)
        _notch(combo)
        assert bar.value() > 0
        assert combo.currentIndex() == 0
    finally:
        _close(win)


def test_a_focused_field_still_answers_the_wheel(monkeypatch):
    win, comp = _composer(monkeypatch)
    try:
        bar, spin = _field_in_sight(comp, QAbstractSpinBox)
        before = spin.value()
        spin.setFocus()
        comp.activateWindow()
        _settle()
        assert spin.hasFocus()
        _notch(spin)
        assert spin.value() != before
        assert bar.value() == 0
    finally:
        _close(win)


def test_every_field_of_the_side_panel_is_guarded(monkeypatch):
    from PySide6.QtCore import Qt
    win, comp = _composer(monkeypatch)
    try:
        panel = comp._tabs
        fields = [f for kind in (QAbstractSpinBox, QComboBox, QSlider)
                  for f in panel.findChildren(kind)]
        assert len(fields) > 50
        assert all(f.focusPolicy() == Qt.StrongFocus for f in fields)
    finally:
        _close(win)
