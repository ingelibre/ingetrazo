# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Delete from the Outliner: a row goes with every group it holds, as
Delete does on the view's selection — the Delete key on the tree or
«Delete» in its right-click menu, one undo step either way."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.group import Group  # noqa: E402
from core.i18n import tr  # noqa: E402
from core.mesh import Mesh  # noqa: E402

_app = QApplication.instance() or QApplication([])

_QUADS = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6),
          (0, 2, 6, 4), (1, 5, 7, 3)]


def _box(at=(0.0, 0.0, 0.0), size=0.1) -> Mesh:
    mesh = Mesh()
    x0, y0, z0 = at
    c = [QVector3D(x0 + dx * size, y0 + dy * size, z0 + dz * size)
         for dz in (0, 1) for dy in (0, 1) for dx in (0, 1)]
    for q in _QUADS:
        mesh.add_face([c[k] for k in q])
    return mesh


def _group(name, at=(0.0, 0.0, 0.0)) -> Group:
    return Group(_box(at), name=name)


def _container(name, kids) -> Group:
    g = Group(name=name)
    g.adopt(kids)
    g.component = False
    return g


def _building():
    """Building ▸ Level 1 ▸ (Wall, Slab), plus a loose Tree beside it."""
    wall, slab = _group("Wall", (0, 0, 0)), _group("Slab", (1, 0, 0))
    level1 = _container("Level 1", [wall, slab])
    building = _container("Building", [level1])
    tree = _group("Tree", (5, 0, 0))
    return building, level1, wall, tree


def _window_with(*groups):
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    scene.groups[:] = groups        # without the template's scale figure
    scene.version += 1
    panel = win.project_browser.outliner
    panel.refresh()
    return win, scene, panel


def _close(win):
    win.viewport.scene.end_group_edit()
    win._saved_version = win.viewport.scene.version


def _pick(panel, *groups):
    # Current row first: setCurrentItem alone would select it ALONE.
    panel.tree.setCurrentItem(panel._items[id(groups[-1])])
    for g in groups:
        panel._items[id(g)].setSelected(True)


def test_deleting_a_row_takes_its_subgroups_in_one_undo_step():
    building, level1, wall, tree = _building()
    win, scene, panel = _window_with(building, tree)
    assert panel.delete_groups([building])
    assert scene.groups == [tree]
    assert id(level1) not in panel._items and id(wall) not in panel._items
    win.viewport.history.undo()
    assert scene.groups == [building, tree]
    assert building.children == [level1] and wall in level1.children
    _close(win)


def test_the_delete_key_deletes_the_picked_rows():
    building, _level1, _wall, tree = _building()
    win, scene, panel = _window_with(building, tree)
    _pick(panel, tree)
    QTest.keyClick(panel.tree, Qt.Key_Delete)
    assert scene.groups == [building]
    _close(win)


def test_a_row_inside_a_picked_row_goes_with_it():
    # Building and the Wall inside it both picked: Building goes once,
    # whole; undo puts the Wall back inside it, not beside it.
    building, level1, wall, tree = _building()
    win, scene, panel = _window_with(building, tree)
    assert panel.delete_groups([wall, building])
    assert scene.groups == [tree]
    win.viewport.history.undo()
    assert scene.groups == [building, tree] and wall in level1.children
    _close(win)


def test_a_nested_row_alone_leaves_its_parent():
    building, level1, wall, tree = _building()
    win, scene, panel = _window_with(building, tree)
    assert panel.delete_groups([wall])
    assert wall not in level1.children and len(level1.children) == 1
    assert scene.groups == [building, tree]
    _close(win)


def test_a_locked_row_is_refused():
    building, _level1, _wall, tree = _building()
    tree.locked = True
    win, scene, panel = _window_with(building, tree)
    assert not panel.delete_groups([tree])
    assert scene.groups == [building, tree]
    _close(win)


def test_a_row_inside_a_locked_group_is_refused():
    building, level1, wall, tree = _building()
    building.locked = True
    win, scene, panel = _window_with(building, tree)
    assert not panel.delete_groups([wall])
    assert wall in level1.children
    _close(win)


def test_deleting_the_open_group_goes_back_to_the_model():
    building, level1, _wall, tree = _building()
    win, scene, panel = _window_with(building, tree)
    panel.open_item(panel._items[id(level1)])
    assert scene.edit_group is level1
    assert panel.delete_groups([building])
    assert scene.edit_group is None
    assert scene.groups == [tree]
    _close(win)


def _menu_pick(panel, item, text=None):
    """The row's right-click menu, read open: its entry texts — and, with
    ``text``, that entry triggered as a click would."""
    found = []

    def read():
        m = QApplication.activePopupWidget()
        if m is None:
            QTimer.singleShot(10, read)
            return
        found.extend(a.text() for a in m.actions())
        chosen = [a for a in m.actions() if a.text() == text]
        m.close()
        if chosen:
            chosen[0].trigger()
    QTimer.singleShot(0, read)
    panel._on_context_menu(panel.tree.visualItemRect(item).center())
    return found


def test_the_right_click_menu_offers_delete():
    building, _level1, _wall, tree = _building()
    win, scene, panel = _window_with(building, tree)
    assert tr("Delete") in _menu_pick(panel, panel._items[id(tree)])
    _close(win)


def test_delete_from_the_menu_takes_the_picked_rows():
    building, _level1, _wall, tree = _building()
    win, scene, panel = _window_with(building, tree)
    _pick(panel, building, tree)
    _menu_pick(panel, panel._items[id(tree)], tr("Delete"))
    QTest.qWait(50)                 # the action runs on the next turn
    assert scene.groups == []
    win.viewport.history.undo()     # both back in one step
    assert scene.groups == [building, tree]
    _close(win)
