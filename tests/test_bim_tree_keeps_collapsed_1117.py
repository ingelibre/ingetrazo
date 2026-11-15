# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The takeoff table keeps the branches the user folded (#1117).

Any change of content rebuilds the table, and opening a group is one: every
folded branch of the tree came open again on picking a row."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.bim import tag_group  # noqa: E402
from core.group import Group  # noqa: E402
from core.mesh import Mesh  # noqa: E402


def _box(x):
    m = Mesh()
    p = [V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0),
         V(x, 0, 1), V(x + 1, 0, 1), V(x + 1, 1, 1), V(x, 1, 1)]
    for idx in ((3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4),
                (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        m.add_face([p[i] for i in idx])
    return m


def _model(scene):
    """floor1 ( walls ( W1 ) ), floor2 ( W2 ), with the walls tagged."""
    floors = []
    for i, name in enumerate(("floor1", "floor2")):
        leaf = Group(_box(i * 3))
        leaf.name = f"W{i + 1}"
        tag_group(leaf, "IfcWall", leaf.name)
        outer = Group(Mesh(), name=name)
        if i == 0:
            walls = Group(Mesh(), name="walls")
            walls.children.append(leaf)
            outer.children.append(walls)
        else:
            outer.children.append(leaf)
        scene.groups.append(outer)
        floors.append(outer)
    scene.version += 1
    return floors


def _rows(panel):
    rows = {}
    it = QTreeWidgetItemIterator(panel.tree)
    while it.value() is not None:
        rows[it.value().text(1) or it.value().text(0)] = it.value()
        it += 1
    return rows


def _window():
    from views.main_window import MainWindow
    return MainWindow()


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_opening_a_group_leaves_the_folded_branches_folded():
    win = _window()
    try:
        vp = win.viewport
        _model(vp.scene)
        panel = win.bim_tray.bim
        panel.refresh()
        rows = _rows(panel)
        assert rows["walls"].isExpanded() and rows["floor1"].isExpanded()
        rows["walls"].setExpanded(False)
        rows["floor2"].setExpanded(False)
        height = panel.tree.height()

        cv = vp.scene.content_version
        panel._on_pick_object(rows["W1"], 0)    # opens the groups around it
        panel.refresh()
        assert vp.scene.content_version != cv   # the table was rebuilt ...
        rows = _rows(panel)
        assert not rows["walls"].isExpanded()   # ... with the folds in place
        assert not rows["floor2"].isExpanded()
        assert rows["floor1"].isExpanded()
        assert panel.tree.height() == height    # and no taller for it
    finally:
        _close(win)


def test_a_new_branch_comes_open_and_a_folded_tagged_group_stays_folded():
    win = _window()
    try:
        vp = win.viewport
        floors = _model(vp.scene)
        tag_group(floors[1], "IfcBuildingStorey", "tagged floor")
        vp.scene.version += 1
        panel = win.bim_tray.bim
        panel.refresh()
        rows = _rows(panel)
        rows["tagged floor"].setExpanded(False)  # a tagged group's own row

        extra = Group(_box(9))
        tag_group(extra, "IfcWall", "W3")
        outer = Group(Mesh(), name="floor3")
        outer.children.append(extra)
        vp.scene.groups.append(outer)
        vp.scene.version += 1
        panel.refresh()
        rows = _rows(panel)
        assert not rows["tagged floor"].isExpanded()
        assert rows["floor3"].isExpanded()
    finally:
        _close(win)
