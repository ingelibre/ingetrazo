# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #214: a group or component is named in Entity Info, where
everyone looks for it — one undo step, per object."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.group import Group  # noqa: E402
from core.mesh import Mesh  # noqa: E402

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
