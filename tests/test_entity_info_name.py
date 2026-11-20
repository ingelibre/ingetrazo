# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #214: a group or component is named in Entity Info, where
everyone looks for it — one undo step, per object."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.group import Group  # noqa: E402
from core.layers import Layer  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core.section import SectionPlane  # noqa: E402

_app = QApplication.instance() or QApplication([])


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


@pytest.fixture
def window():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _panel(window):
    from views.tray import EntityInfoPanel
    return window.findChild(EntityInfoPanel)


def _group(scene, name, x=0.0):
    m = Mesh()
    m.add_face([V(x, 0), V(x + 1, 0), V(x + 1, 1), V(x, 1)])
    g = Group(m, name=name)
    scene.groups.append(g)
    return g


def test_the_field_shows_only_for_one_group(window):
    scene = window.viewport.scene
    panel = _panel(window)
    a, b = _group(scene, "Cámara"), _group(scene, "Brida", 3)
    scene.selection.add(a)
    panel.refresh()
    assert panel._name_edit.isVisible()
    assert panel._name_edit.text() == "Cámara"
    scene.selection.add(b)                       # two: no single name
    panel.refresh()
    assert not panel._name_edit.isVisible()
    scene.selection.clear()
    scene.selection.add(b)                       # another one: its name
    panel.refresh()
    assert panel._name_edit.text() == "Brida"


def test_renaming_is_one_undo_step(window):
    scene = window.viewport.scene
    panel = _panel(window)
    g = _group(scene, "Group")
    scene.selection.add(g)
    panel.refresh()
    panel._name_edit.setText("Cámara de vacío")
    panel._on_name_edited()
    assert g.name == "Cámara de vacío"
    assert window.viewport.history.undo()
    assert g.name == "Group"


def test_an_empty_name_is_not_taken(window):
    scene = window.viewport.scene
    panel = _panel(window)
    g = _group(scene, "Tapa")
    scene.selection.add(g)
    panel.refresh()
    panel._name_edit.setText("   ")
    panel._on_name_edited()
    assert g.name == "Tapa" and panel._name_edit.text() == "Tapa"


def test_section_name_and_symbol_accept_duplicates_and_undo(window):
    scene = window.viewport.scene
    panel = _panel(window)
    a = SectionPlane(V(0, 0), V(0, 0, 1), name="A", symbol="A")
    b = SectionPlane(V(1, 0), V(0, 0, 1), name="B", symbol="B")
    scene.section_planes.extend([a, b])
    scene.layers.append(Layer("Cuts"))
    scene.select([b])
    panel.refresh()
    assert panel._name_edit.isVisible()
    assert panel._symbol_edit.isVisible()
    assert panel._layer_box.isVisible()

    panel._name_edit.setFocus()
    panel._name_edit.selectAll()
    QTest.keyClicks(panel._name_edit, "A")
    QTest.keyClick(panel._name_edit, Qt.Key_Return)
    assert (b.name, b.symbol) == ("A", "B")
    panel._symbol_edit.setFocus()
    panel._symbol_edit.selectAll()
    QTest.keyClicks(panel._symbol_edit, "A")
    QTest.keyClick(panel._symbol_edit, Qt.Key_Return)
    assert (a.name, a.symbol) == (b.name, b.symbol) == ("A", "A")

    assert window.viewport.history.undo()
    panel.refresh()
    assert (b.name, b.symbol) == ("A", "B")
    assert panel._symbol_edit.text() == "B"
    assert window.viewport.history.undo()
    panel.refresh()
    assert (b.name, b.symbol) == ("B", "B")
    assert window.viewport.history.redo()
    assert window.viewport.history.redo()
    panel.refresh()
    assert (b.name, b.symbol) == ("A", "A")
    panel._layer_box.setCurrentIndex(panel._layer_box.findText("Cuts"))
    assert b.layer == "Cuts"
    assert window.viewport.history.undo()
    assert b.layer != "Cuts"


def test_section_fields_reject_empty_and_hide_for_other_selections(window):
    scene = window.viewport.scene
    panel = _panel(window)
    plane = SectionPlane(V(0, 0), V(0, 0, 1), name="Plan", symbol="A")
    scene.section_planes.append(plane)
    scene.select([plane])
    panel.refresh()
    panel._name_edit.setText("  ")
    panel._on_name_edited()
    panel._symbol_edit.clear()
    panel._on_symbol_edited()
    assert (plane.name, plane.symbol) == ("Plan", "A")
    assert (panel._name_edit.text(), panel._symbol_edit.text()) == ("Plan", "A")

    group = _group(scene, "Group")
    scene.select([group])
    panel.refresh()
    assert panel._name_edit.isVisible()
    assert not panel._symbol_edit.isVisible()
    scene.select([group, plane])
    panel.refresh()
    assert not panel._name_edit.isVisible()
    assert not panel._symbol_edit.isVisible()


def test_stale_section_edit_does_not_change_previous_selection(window):
    scene = window.viewport.scene
    panel = _panel(window)
    a = SectionPlane(V(0, 0), V(0, 0, 1), name="A", symbol="A")
    b = SectionPlane(V(1, 0), V(0, 0, 1), name="B", symbol="B")
    scene.section_planes.extend([a, b])
    scene.select([a])
    panel.refresh()
    panel._name_edit.setText("Other")
    scene.select([b])
    panel._on_name_edited()
    assert (a.name, b.name) == ("A", "B")
    panel.refresh()
    assert panel._name_edit.text() == "B"
