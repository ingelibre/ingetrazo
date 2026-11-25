# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Layers rows are never rebuilt under an open name editor (#1528):
the rebuild waits for the editor to close, and neither it nor the name
typed is lost."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, qInstallMessageHandler
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from core import layers as L
from core.layers import Layer
from views import layers_panel as LP

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def panel():
    from PySide6.QtCore import QSettings
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    w.layers_dock.show()
    w.layers_dock.raise_()
    scene = w.viewport.scene
    scene.layer_folders = ["Fa", "Fb"]
    scene.layers += [Layer("La", folder="Fa"), Layer("Lb", folder="Fa")]
    p = w.layers_dock.panel
    p.refresh()
    _app.processEvents()
    assert p.isVisible()
    yield p
    w._saved_version = scene.version
    w.close()
    QSettings().remove("ui/window_state")
    QSettings().remove("ui/window_geometry")


@pytest.fixture
def complaints():
    """What Qt says of an editor whose row went from under it."""
    seen = []

    def take(_kind, _ctx, text):
        if "editor that does not belong" in text or "editing failed" in text:
            seen.append(text)
    before = qInstallMessageHandler(take)
    yield seen
    qInstallMessageHandler(before)


def _editor(panel):
    return next((e for e in panel.tree.viewport().findChildren(QLineEdit)
                 if not e.isHidden()), None)


def _open(panel, name, kind=LP.KIND_LAYER):
    panel.tree.editItem(panel.item_for(name, kind), LP.COL_NAME)
    return _editor(panel)


def _type(editor, text):
    editor.selectAll()
    QTest.keyClicks(editor, text)


def _settle():
    for _ in range(5):
        _app.processEvents()


def _up_to_date(panel):
    scene = panel._scene()
    rows = {n for _k, n, _d in panel.display_outline()}
    return (rows == {ly.name for ly in scene.layers} | set(L.folders_of(scene))
            and panel._drawn_signature == panel._signature()
            and panel._waiting is None)


def test_a_touch_waits_for_the_editor(panel, complaints):
    editor = _open(panel, "Fa", LP.KIND_FOLDER)
    _type(editor, "Walls")
    panel.set_visible(["La"], False)
    panel._refresh_after_change()
    panel.refresh()
    _settle()
    assert _editor(panel) is editor and editor.text() == "Walls"
    QTest.keyClick(editor, Qt.Key_Return)
    _settle()
    assert complaints == []
    assert panel._scene().layer("La").folder == "Walls"
    assert not panel._scene().layer("La").visible
    assert _up_to_date(panel)


def test_a_change_of_the_model_waits_for_the_editor(panel, complaints):
    scene = panel._scene()
    panel.on_scene_changed()                # its rebuild is on the way …
    scene.layers.append(Layer("New"))
    editor = _open(panel, "La")             # … when a name is opened
    _type(editor, "Doors")
    _settle()
    assert _editor(panel) is editor
    QTest.keyClick(editor, Qt.Key_Escape)   # nothing renamed, still drawn
    _settle()
    assert complaints == []
    assert scene.layer("La") is not None and scene.layer("Doors") is None
    assert _up_to_date(panel)


def test_tab_opens_the_next_cell_and_nothing_is_lost(panel, complaints):
    scene = panel._scene()
    editor = _open(panel, "La")
    _type(editor, "One")
    QTest.keyClick(editor, Qt.Key_Tab)
    _settle()
    editor = _editor(panel)
    assert editor is not None               # the next cell's, still open
    # The same row again, its rebuild still waiting.
    panel.item_for("La").setText(LP.COL_NAME, "Three")
    _settle()
    assert _editor(panel) is editor
    QTest.keyClick(editor, Qt.Key_Return)
    _settle()
    assert complaints == []
    assert [ly.name for ly in scene.layers[-2:]] == ["Three", "Lb"]
    assert _up_to_date(panel)


def test_a_button_takes_the_name_being_typed(panel, complaints):
    """A button need not take the focus: the name goes in, the new row is
    there with its own name open."""
    scene = panel._scene()
    _type(_open(panel, "La"), "Slabs")
    new = panel.add_layer()
    _settle()
    assert scene.layer("Slabs") is not None
    editor = _editor(panel)
    assert editor is not None and editor.text() == new
    QTest.keyClick(editor, Qt.Key_Return)
    _settle()
    assert complaints == []
    assert _up_to_date(panel)
