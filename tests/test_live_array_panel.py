# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Entity Info edits a live array (core/array.py): select it and its
copies, step and mode are fields; changing one lays the copies out again
in one undo step. Any other group shows no such fields."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.array import MakeArrayCommand, move_recipe, rotate_recipe  # noqa: E402
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


def _pillar():
    m = Mesh()
    m.add_face([V(0, 0), V(0.3, 0), V(0.3, 0.3), V(0, 0.3)])
    return Group(m, name="Lama")


def _panel(window):
    from views.tray import EntityInfoPanel
    panel = window.findChild(EntityInfoPanel)
    panel.refresh()
    return panel


def _array(window, recipe):
    scene = window.viewport.scene
    g = _pillar()
    scene.groups.append(g)
    window.viewport.history.execute(MakeArrayCommand([g], recipe))
    return scene.groups[-1]


def test_the_fields_show_an_array_and_change_it(window):
    arr = _array(window, move_recipe(V(0, 1.5), 4, "x"))
    panel = _panel(window)
    assert panel._array is arr and not panel._array_row.isHidden()
    assert panel._copies_box.value() == 4
    assert panel._distance_box.value() == pytest.approx(1.5)
    panel._copies_box.setValue(9)
    assert arr.array["count"] == 9 and len(arr.children) == 10
    panel._distance_box.setValue(1.0)
    assert arr.array["step"] == pytest.approx([0.0, 1.0, 0.0])
    panel._mode_box.setCurrentIndex(1)              # Divide
    assert arr.array["mode"] == "/"
    window.viewport.history.undo()
    assert arr.array["mode"] == "x"
    window.viewport.history.undo()
    window.viewport.history.undo()
    assert arr.array["count"] == 4 and len(arr.children) == 5


def test_a_polar_array_shows_its_angle(window):
    arr = _array(window, rotate_recipe(V(0, 0), V(0, 0, 1), 30.0, 3, "x"))
    panel = _panel(window)
    assert panel._step_stack.currentWidget() is panel._angle_box
    assert panel._angle_box.value() == pytest.approx(30.0)
    panel._angle_box.setValue(45.0)
    assert arr.array["angle"] == pytest.approx(45.0)


def test_a_plain_group_shows_no_array_fields(window):
    scene = window.viewport.scene
    g = _pillar()
    scene.groups.append(g)
    scene.selection.clear()
    scene.selection.add(g)
    panel = _panel(window)
    assert panel._array is None and panel._array_row.isHidden()


def test_full_turn_spreads_a_polar_array_round(window):
    """The «Full turn» box: 7 copies → 8 posts every 45°, without doing
    360 ÷ 8 by hand; the total is said next to it."""
    from core.array import is_full_turn
    arr = _array(window, rotate_recipe(V(0, 0), V(0, 0, 1), 30.0, 7, "x"))
    panel = _panel(window)
    assert not panel._full_turn_box.isHidden()
    assert "8" in panel._array_total.text()
    panel._full_turn_box.setChecked(True)
    assert is_full_turn(arr.array)
    assert not panel._angle_box.isEnabled()
    panel._full_turn_box.setChecked(False)          # nothing jumps
    assert arr.array["mode"] == "x"
    assert arr.array["angle"] == pytest.approx(45.0)


def test_a_straight_array_has_no_full_turn_box(window):
    _array(window, move_recipe(V(0, 1.5), 4, "x"))
    panel = _panel(window)
    assert panel._full_turn_box.isHidden()
    assert "5" in panel._array_total.text()


def test_the_panel_counts_what_is_there(window):
    """Copies deleted by hand inside the array: the total says so; with
    none left the array fields go (no copies, no array)."""
    from core.array import copies_of
    from core.history import DeleteGroupCommand
    arr = _array(window, move_recipe(V(0, 1.5), 4, "x"))
    scene, history = window.viewport.scene, window.viewport.history
    scene.begin_group_edit(arr)
    history.execute(DeleteGroupCommand(copies_of(arr)[0]))
    scene.end_group_edit()
    scene.selection.clear()
    scene.selection.add(arr)
    panel = _panel(window)
    assert "4" in panel._array_total.text() and "1" in panel._array_total.text()
    scene.begin_group_edit(arr)
    for c in copies_of(arr):
        history.execute(DeleteGroupCommand(c))
    scene.end_group_edit()
    scene.selection.clear()
    scene.selection.add(arr)
    panel = _panel(window)
    assert panel._array is None and panel._array_row.isHidden()
