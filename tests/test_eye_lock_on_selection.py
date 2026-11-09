# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The eye and the padlock of one of several selected rows act on all of
them, as the material panel does. The press used to select that one row
first, so only it was hidden or locked; it now acts at once and leaves the
selection alone. Real mouse presses on the tree's viewport."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.mesh import Mesh
from views.outliner import COL_EYE, COL_LOCK, COL_NAME


def _setup():
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    scene.groups.clear()
    groups = []
    for i, name in enumerate(("A", "B", "C")):
        m = Mesh()
        m.add_face([V(i * 2, 0, 0), V(i * 2 + 1, 0, 0), V(i * 2 + 1, 1, 0),
                    V(i * 2, 1, 0)])
        g = Group(m, name=name)
        scene.groups.append(g)
        groups.append(g)
    scene.version += 1
    panel = win.project_browser.outliner
    panel.tree.resize(600, 300)
    panel.refresh()
    return win, scene, panel, groups


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _press(panel, item, col, modifiers=Qt.NoModifier):
    tree = panel.tree
    head = tree.header()
    r = tree.visualItemRect(item)
    x = head.sectionViewportPosition(col) + head.sectionSize(col) // 2
    pt = QPointF(x, r.center().y())
    glob = QPointF(tree.viewport().mapToGlobal(pt.toPoint()))
    for kind, buttons in ((QEvent.MouseButtonPress, Qt.LeftButton),
                          (QEvent.MouseButtonRelease, Qt.NoButton)):
        QApplication.sendEvent(tree.viewport(), QMouseEvent(
            kind, pt, glob, Qt.LeftButton, buttons, modifiers))
    QApplication.processEvents()


@pytest.mark.parametrize("col, attr", [(COL_EYE, "hidden"),
                                       (COL_LOCK, "locked")])
def test_on_a_selected_row_it_acts_on_every_selected_row(col, attr):
    win, scene, panel, (a, b, c) = _setup()
    try:
        root = panel.tree.topLevelItem(0)
        root.child(0).setSelected(True)
        root.child(1).setSelected(True)
        _press(panel, root.child(1), col)
        assert getattr(a, attr) and getattr(b, attr)
        assert not getattr(c, attr, False)
    finally:
        _close(win)


@pytest.mark.parametrize("col, attr", [(COL_EYE, "hidden"),
                                       (COL_LOCK, "locked")])
def test_on_a_row_outside_the_selection_it_acts_on_that_row_alone(col, attr):
    win, scene, panel, (a, b, c) = _setup()
    try:
        root = panel.tree.topLevelItem(0)
        root.child(0).setSelected(True)
        root.child(1).setSelected(True)
        _press(panel, root.child(2), col)
        assert getattr(c, attr)
        assert not getattr(a, attr, False) and not getattr(b, attr, False)
        # and the press did not select it
        assert not root.child(2).isSelected()
    finally:
        _close(win)


@pytest.mark.parametrize("col, attr", [(COL_EYE, "hidden"),
                                       (COL_LOCK, "locked")])
def test_hidden_or_locked_rows_selected_together_come_back_together(col,
                                                                    attr):
    win, scene, panel, (a, b, c) = _setup()
    try:
        for g in (a, b):
            setattr(g, attr, True)
        scene.version += 1
        panel.refresh()
        root = panel.tree.topLevelItem(0)
        panel.tree.clearSelection()
        _press(panel, root.child(0), COL_NAME, Qt.ControlModifier)
        _press(panel, root.child(1), COL_NAME, Qt.ControlModifier)
        assert {i.text(COL_NAME) for i in panel.tree.selectedItems()} == \
            {"A", "B"}
        _press(panel, root.child(1), col)
        assert not getattr(a, attr) and not getattr(b, attr)
    finally:
        _close(win)


def test_one_press_is_one_undo_step():
    win, scene, panel, (a, b, c) = _setup()
    try:
        root = panel.tree.topLevelItem(0)
        root.child(0).setSelected(True)
        root.child(1).setSelected(True)
        steps = len(win.viewport.history.undo_stack)
        _press(panel, root.child(0), COL_EYE)
        assert len(win.viewport.history.undo_stack) == steps + 1
        win.viewport.history.undo()
        assert not a.hidden and not b.hidden
    finally:
        _close(win)


# --- hidden or locked rows stay picked in the Browser ------------------------

def _names(panel):
    return sorted(i.text(COL_NAME) for i in panel.tree.selectedItems())


@pytest.mark.parametrize("attr", ["hidden", "locked"])
def test_a_hidden_or_locked_row_clicked_stays_selected(attr):
    """The view cannot select it, and the row was deselected at once."""
    win, scene, panel, (a, b, c) = _setup()
    try:
        setattr(a, attr, True)
        scene.version += 1
        panel.refresh()
        root = panel.tree.topLevelItem(0)
        _press(panel, root.child(0), COL_NAME)
        assert _names(panel) == ["A"]
        assert a not in scene.selection           # the view: nothing
        panel.refresh()
        assert _names(panel) == ["A"]              # still, after a refresh
    finally:
        _close(win)


def test_rows_hidden_with_the_eye_stay_picked_and_come_back_selected():
    win, scene, panel, (a, b, c) = _setup()
    try:
        root = panel.tree.topLevelItem(0)
        _press(panel, root.child(1), COL_NAME)
        _press(panel, root.child(2), COL_NAME, Qt.ControlModifier)
        _press(panel, root.child(1), COL_EYE)
        panel.refresh()
        assert b.hidden and c.hidden
        assert _names(panel) == ["B", "C"]          # still picked here
        _press(panel, root.child(1), COL_EYE)       # a second press
        panel.refresh()
        assert not b.hidden and not c.hidden
        assert _names(panel) == ["B", "C"]
        assert set(scene.selection) == {b, c}       # and in the view now
    finally:
        _close(win)


def test_a_selection_made_in_the_view_drops_the_kept_rows():
    win, scene, panel, (a, b, c) = _setup()
    try:
        a.hidden = True
        scene.version += 1
        panel.refresh()
        root = panel.tree.topLevelItem(0)
        _press(panel, root.child(0), COL_NAME)
        assert _names(panel) == ["A"]
        scene.selection.clear()
        scene.selection.add(c)                      # picked in the view
        scene.bump_view()
        panel.refresh()
        assert _names(panel) == ["C"]
    finally:
        _close(win)
