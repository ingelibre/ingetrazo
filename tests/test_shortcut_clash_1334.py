# SPDX-License-Identifier: GPL-3.0-or-later
"""An extension's panel that takes one of the window's keys (#1334).

The Node Editor gives its graph Ctrl+S and Ctrl+Shift+S with window-wide
QShortcuts. With its panel open, Qt found two owners for the key and ran
neither: Ctrl+S stopped saving the model. The owner nearest the focus wins
now: in the panel the panel's, anywhere else the window's.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDockWidget, QLineEdit

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

import core.extensions as extensions                              # noqa: E402


class _Hits:
    def __init__(self):
        self.calls = []

    def save(self, *_a):
        self.calls.append("model")

    def save_as(self, *_a):
        self.calls.append("model as")

    def graph(self):
        self.calls.append("graph")

    def graph_as(self):
        self.calls.append("graph as")


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [tmp_path])
    from views.main_window import MainWindow
    hits = _Hits()
    monkeypatch.setattr(MainWindow, "_on_save", hits.save)
    monkeypatch.setattr(MainWindow, "_on_save_as", hits.save_as)
    w = MainWindow()
    w.show()
    QTest.qWaitForWindowExposed(w)
    dock = QDockWidget("Node editor", w)
    field = QLineEdit()
    dock.setWidget(field)
    # As the extension does it: window-wide shortcuts on its own widget.
    QShortcut(QKeySequence.StandardKey.Save, field).activated.connect(
        hits.graph)
    QShortcut(QKeySequence("Ctrl+Shift+S"), field).activated.connect(
        hits.graph_as)
    w.addDockWidget(Qt.RightDockWidgetArea, dock)
    dock.show()
    QApplication.processEvents()
    yield w, field, hits
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def _press(widget, mods):
    widget.setFocus()
    QApplication.processEvents()
    QTest.keyClick(widget, Qt.Key_S, mods)
    QApplication.processEvents()


def test_ctrl_s_saves_the_model_with_the_panel_open(win):
    w, _field, hits = win
    _press(w.viewport, Qt.ControlModifier)
    assert hits.calls == ["model"]
    _press(w.viewport, Qt.ControlModifier | Qt.ShiftModifier)
    assert hits.calls == ["model", "model as"]


def test_inside_the_panel_the_key_is_the_panels(win):
    _w, field, hits = win
    _press(field, Qt.ControlModifier)
    _press(field, Qt.ControlModifier | Qt.ShiftModifier)
    assert hits.calls == ["graph", "graph as"]


def test_a_hidden_panel_leaves_the_key_to_the_window(win):
    w, field, hits = win
    field.parentWidget().hide()
    _press(w.viewport, Qt.ControlModifier)
    assert hits.calls == ["model"]
