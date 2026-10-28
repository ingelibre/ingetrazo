# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Browser and the Layers tab as one kind of list (views/side_tree.py):
the same drag picture, the same drop marks, the same cells that act without
touching the selection, and the target column that shows a group alone.

Every model here is generated, as in tests/test_outliner.py.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core import outliner
from core.group import Group
from core.mesh import Mesh
from views.outliner import (COL_EYE, COL_ISOLATE, COL_NAME, MARK_SIZE,
                            mark_icon, node_icon)

_app = QApplication.instance() or QApplication([])

_QUADS = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6),
          (0, 2, 6, 4), (1, 5, 7, 3)]


def _box(at=(0.0, 0.0, 0.0), size=0.1) -> Mesh:
    from PySide6.QtGui import QVector3D
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
    """Building ▸ Level 1 ▸ (Wall, Slab) and Level 2 ▸ (Wall), plus a
    loose Tree beside it."""
    wall1, slab = _group("Wall", (0, 0, 0)), _group("Slab", (1, 0, 0))
    level1 = _container("Level 1", [wall1, slab])
    level2 = _container("Level 2", [_group("Wall", (0, 0, 3))])
    building = _container("Building", [level1, level2])
    tree = _group("Tree", (5, 0, 0))
    return building, tree


def _window_with(*groups):
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    scene = win.viewport.scene
    scene.groups[:] = groups
    scene.version += 1
    panel = win.project_browser.outliner
    panel.refresh()
    panel.tree.expandAll()
    _app.processEvents()
    return win, scene, panel


def _close(win):
    win.viewport.scene.end_group_edit()
    win._saved_version = win.viewport.scene.version


def _row(panel, group):
    return panel._items[id(group)]


def _mark_point(panel, group, column=COL_EYE) -> QPoint:
    """The middle of a row's cell, in viewport coordinates."""
    tree = panel.tree
    rect = tree.visualItemRect(_row(panel, group))
    x = tree.columnViewportPosition(column) + tree.columnWidth(column) // 2
    return QPoint(x, rect.center().y())


def _drag_move(tree, pos):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QDragMoveEvent

    class _Move(QDragMoveEvent):
        def source(self):
            return tree

    ev = _Move(pos, Qt.MoveAction, QMimeData(), Qt.LeftButton,
               Qt.NoModifier)
    tree.dragMoveEvent(ev)
    return ev


def _drop(tree, pos):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QDropEvent

    class _Drop(QDropEvent):
        def source(self):
            return tree

    ev = _Drop(QPointF(pos), Qt.MoveAction, QMimeData(), Qt.LeftButton,
               Qt.NoModifier)
    tree.dropEvent(ev)
    _app.processEvents()
    return ev


# ---- One list for both tabs ------------------------------------------------

def test_the_browser_and_layers_trees_share_the_side_tree():
    from views.layers_panel import _LayerTree
    from views.outliner import _Tree
    from views.side_tree import SideTree
    assert issubclass(_Tree, SideTree)
    assert issubclass(_LayerTree, SideTree)


# ---- What a drag carries ---------------------------------------------------

def test_a_drag_carries_the_rows_see_through_and_stacked():
    groups = [_group(f"Node {i}", (i, 0, 0)) for i in range(9)]
    win, _scene, panel = _window_with(*groups)
    try:
        tree = panel.tree
        for g in groups[:8]:
            _row(panel, g).setSelected(True)
        pm, rows = tree.drag_pixmap()
        h = tree.visualItemRect(_row(panel, groups[0])).height()
        assert [r.text(COL_NAME) for r in rows] == [g.name for g in groups[:8]]
        # Drawn one under the other, then the rest counted on one more row.
        assert round(pm.height() / pm.devicePixelRatio()) == (
            tree.DRAG_ROWS + 1) * h
        img = pm.toImage()
        # The rows are see-through; the «+1 more» line under them is drawn
        # solid, to be read — sampled, its letters fell on a sample point
        # with the CI's font. Only the rows' band is sampled here.
        rows_bottom = round(tree.DRAG_ROWS * h * pm.devicePixelRatio())
        alphas = {img.pixelColor(x, y).alpha()
                  for x in range(5, img.width() - 5, 7)
                  for y in range(3, rows_bottom - 3, 3)}
        assert alphas and max(alphas) < 255
        foot = {img.pixelColor(x, y).alpha()
                for x in range(5, img.width() - 5)
                for y in range(rows_bottom + 2, img.height() - 3)}
        assert max(foot) == 255                     # the count reads solid
    finally:
        _close(win)


# ---- Where a drop lands ----------------------------------------------------

def test_a_drop_says_into_or_beside_and_outlines_what_it_covers():
    building, tree = _building()
    win, _scene, panel = _window_with(building, tree)
    try:
        level1, level2 = building.children
        t = panel.tree
        middle = t.visualItemRect(_row(panel, level1)).center()
        ev = _drag_move(t, middle)
        assert ev.isAccepted()
        assert t.drop_hint == (("into", _row(panel, level1)),)
        box = t.drop_rect(t.drop_hint[0])
        assert box.top() <= t.visualItemRect(_row(panel, level1)).center().y()
        assert box.top() <= t.visualItemRect(
            _row(panel, level1.children[1])).center().y()
        assert (t.visualItemRect(_row(panel, level2)).center().y()
                > box.bottom())
        assert t.drop_text(t.drop_hint[0]) == "Into «Level 1»"

        top = t.visualItemRect(_row(panel, level1)).top() + 1
        x = t.visualItemRect(_row(panel, level1)).center().x()
        _drag_move(t, QPoint(x, top))
        assert t.drop_hint == (("beside", _row(panel, level1)),)
        assert t.drop_text(t.drop_hint[0]) == "Beside «Level 1»"

        t.collapseAll()
        _app.processEvents()
        last = max(t.visualItemRect(t.topLevelItem(i)).bottom()
                   for i in range(t.topLevelItemCount()))
        assert last + 5 < t.viewport().height()
        _drag_move(t, QPoint(5, last + 5))
        assert t.drop_hint == (None,)
        assert t.drop_rect(None) == t.viewport().rect()
        assert t.drop_text(None) == "At the top level"
        t.grab()                               # paints outline and pill
        t._clear_hint()
        assert t.drop_hint is None
    finally:
        _close(win)


def test_a_drop_reparents_in_one_undo_step():
    building, tree = _building()
    _level1, level2 = building.children
    win, scene, panel = _window_with(building, tree)
    try:
        t = panel.tree
        _row(panel, tree).setSelected(True)
        steps = len(win.viewport.history.undo_stack)
        pos = t.visualItemRect(_row(panel, level2)).center()
        _drop(t, pos)
        assert tree in level2.children
        assert len(win.viewport.history.undo_stack) == steps + 1
        win.viewport.history.undo()
        panel.refresh()
        assert tree in scene.groups
        assert _row(panel, tree).parent() is panel.tree.topLevelItem(0)
    finally:
        _close(win)


# ---- The cells that act without selecting ----------------------------------

def test_a_wobble_on_an_eye_selects_nothing():
    building, tree = _building()
    win, _scene, panel = _window_with(building, tree)
    try:
        t = panel.tree
        QTest.mouseClick(t.viewport(), Qt.LeftButton, Qt.NoModifier,
                         _mark_point(panel, tree))      # Qt's last press
        _app.processEvents()
        t.clearSelection()
        _row(panel, building).setSelected(True)
        start = _mark_point(panel, building)
        end = _mark_point(panel, tree)
        QTest.mousePress(t.viewport(), Qt.LeftButton, Qt.NoModifier, start)
        move = QMouseEvent(QEvent.MouseMove, QPointF(end),
                           QPointF(t.viewport().mapToGlobal(end)),
                           Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(t.viewport(), move)
        QTest.mouseRelease(t.viewport(), Qt.LeftButton, Qt.NoModifier, end)
        _app.processEvents()
        assert [it.text(COL_NAME) for it in t.selectedItems()] == ["Building"]
        assert building.hidden
    finally:
        _close(win)


def test_a_double_click_on_a_mark_never_opens_the_row():
    building, _ = _building()
    win, _scene, panel = _window_with(building)
    try:
        opened = []
        panel.open_item = opened.append
        t = panel.tree
        p = _mark_point(panel, building)
        QTest.mouseClick(t.viewport(), Qt.LeftButton, Qt.NoModifier, p)
        double = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(p),
                             QPointF(t.viewport().mapToGlobal(p)),
                             Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(t.viewport(), double)
        QTest.mouseRelease(t.viewport(), Qt.LeftButton, Qt.NoModifier, p)
        _app.processEvents()
        assert opened == []
        assert t.state() != t.State.EditingState

        rect = t.visualItemRect(_row(panel, building))
        p = QPoint(t.columnViewportPosition(COL_NAME) + 80, rect.center().y())
        QTest.mouseClick(t.viewport(), Qt.LeftButton, Qt.NoModifier, p)
        double = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(p),
                             QPointF(t.viewport().mapToGlobal(p)),
                             Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(t.viewport(), double)
        QTest.mouseRelease(t.viewport(), Qt.LeftButton, Qt.NoModifier, p)
        _app.processEvents()
        assert [panel._group_of(it) for it in opened] == [building]
    finally:
        _close(win)


# ---- The target column -----------------------------------------------------

def test_the_target_shows_a_group_alone_and_back():
    building, tree = _building()
    level1, level2 = building.children
    win, scene, panel = _window_with(building, tree)
    try:
        steps = len(win.viewport.history.undo_stack)
        p = _mark_point(panel, level1, COL_ISOLATE)
        QTest.mouseClick(panel.tree.viewport(), Qt.LeftButton,
                         Qt.NoModifier, p)
        _app.processEvents()
        assert level2.hidden and tree.hidden
        assert not level1.hidden and not building.hidden
        assert len(win.viewport.history.undo_stack) == steps + 1
        assert panel._isolated_now()
        assert _row(panel, level1).toolTip(COL_ISOLATE) == (
            "Shown alone — click to show back what Isolate hid")

        panel._on_item_clicked(_row(panel, level1), COL_ISOLATE)
        assert not (level2.hidden or tree.hidden)
        assert len(win.viewport.history.undo_stack) == steps + 2
        assert not panel._isolated_now()
        assert _row(panel, level1).toolTip(COL_ISOLATE) == (
            "Isolate: show only this group")
        assert not any(g.hidden for g, _p, _d in outliner.walk(scene.groups))
    finally:
        _close(win)


def test_the_target_of_several_selected_rows_acts_on_all_of_them():
    building, tree = _building()
    level1, level2 = building.children
    win, _scene, panel = _window_with(building, tree)
    try:
        for g in (level1, tree):
            _row(panel, g).setSelected(True)
        panel._on_item_clicked(_row(panel, level1), COL_ISOLATE)
        assert level2.hidden and not level1.hidden and not tree.hidden
        assert panel._isolated_now()
    finally:
        _close(win)


def test_the_target_header_ends_the_isolation():
    building, tree = _building()
    level1, level2 = building.children
    win, _scene, panel = _window_with(building, tree)
    try:
        panel._on_item_clicked(_row(panel, level1), COL_ISOLATE)
        assert level2.hidden and tree.hidden
        panel._on_header_clicked(COL_ISOLATE)
        assert not (level2.hidden or tree.hidden)
        assert not panel._isolated_now()
    finally:
        _close(win)


# ---- The marks -------------------------------------------------------------

def test_an_inherited_mark_is_as_big_as_the_others_only_fainter():
    ink = node_icon("eye_off")
    faded = mark_icon("eye_off", inherited=True)
    assert faded.availableSizes() == [QSize(MARK_SIZE, MARK_SIZE)]
    assert ink.availableSizes() == [QSize(MARK_SIZE, MARK_SIZE)]

    def top_alpha(icon):
        img = icon.pixmap(MARK_SIZE, MARK_SIZE).toImage()
        return max(img.pixelColor(x, y).alpha()
                   for x in range(img.width()) for y in range(img.height()))

    assert 0 < top_alpha(faded) < top_alpha(ink)


# ---- The Layers tab keeps its keyboard -------------------------------------

def test_delete_in_the_layers_list_still_removes_the_row():
    from core.layers import Layer
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    try:
        panel = win.layers_dock.panel
        scene = win.viewport.scene
        scene.layers.append(Layer("Gone"))
        panel.refresh()
        tree = panel.tree
        tree.setCurrentItem(panel.item_for("Gone"))
        tree.setFocus()
        QTest.keyClick(tree, Qt.Key_Delete)
        _app.processEvents()
        assert scene.layer("Gone") is None
    finally:
        _close(win)


# ---- Nesting: a drop anywhere on a group goes into it -----------------------

def test_a_drop_anywhere_on_a_group_row_nests_into_it():
    """Dropping ON a group is what nesting means: only the thin band at the
    row's top edge stands the row beside it. Before, half the row read as
    «beside», so nesting seemed to work only with rows already inside
    another group — beside one of those lands inside its parent."""
    host, guest = _group("Host"), _group("Guest", (3, 0, 0))
    win, _scene, panel = _window_with(host, guest)
    try:
        t = panel.tree
        rect = t.visualItemRect(_row(panel, host))
        low = QPoint(rect.center().x(),
                     rect.top() + int(rect.height() * 0.85))
        _drag_move(t, low)
        assert t.drop_hint == (("into", _row(panel, host)),)
        assert t.drop_text(t.drop_hint[0]) == "Into «Host»"
        steps = len(win.viewport.history.undo_stack)
        _row(panel, guest).setSelected(True)
        _drop(t, low)
        assert guest in host.children
        assert len(win.viewport.history.undo_stack) == steps + 1

        # The top edge still stands a row beside the one under the pointer.
        top = QPoint(rect.center().x(), t.visualItemRect(
            _row(panel, host)).top() + 1)
        _drag_move(t, top)
        assert t.drop_hint == (("beside", _row(panel, host)),)
    finally:
        _close(win)


# ---- Deleting the picked rows ----------------------------------------------

def test_delete_key_removes_the_picked_rows_as_one_step():
    building, tree = _building()
    level1, _level2 = building.children
    win, scene, panel = _window_with(building, tree)
    try:
        rows = [_row(panel, g) for g in (tree, level1)]
        for row in rows:
            row.setSelected(True)
        t = panel.tree
        t.setFocus()
        steps = len(win.viewport.history.undo_stack)
        QTest.keyClick(t, Qt.Key_Delete)
        _app.processEvents()
        assert tree not in scene.groups
        assert level1 not in building.children
        assert all(_is_gone(panel, g) for g in (tree, level1))
        assert len(win.viewport.history.undo_stack) == steps + 1
        win.viewport.history.undo()
        panel.refresh()
        assert tree in scene.groups and level1 in building.children
        assert _row(panel, tree) is not None
    finally:
        _close(win)


def test_a_group_picked_with_one_of_its_parts_is_deleted_once():
    building, tree = _building()
    level1 = building.children[0]
    wall = level1.children[0]
    win, scene, panel = _window_with(building, tree)
    try:
        steps = len(win.viewport.history.undo_stack)
        panel.delete_rows([_row(panel, level1), _row(panel, wall)])
        _app.processEvents()
        assert level1 not in building.children
        assert len(win.viewport.history.undo_stack) == steps + 1
        assert len(scene.groups) == 2
        win.viewport.history.undo()
        panel.refresh()
        assert building.children[0] is level1
        assert wall in level1.children
    finally:
        _close(win)


def test_the_context_menu_deletes_the_picked_rows():
    from PySide6.QtCore import QTimer
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    try:
        t = panel.tree
        _row(panel, tree).setSelected(True)
        found = []

        def read():
            menu = QApplication.activePopupWidget()
            if menu is None:
                QTimer.singleShot(10, read)
                return
            found.extend(a for a in menu.actions() if a.text() == "Delete")
            menu.close()
        QTimer.singleShot(0, read)
        panel._on_context_menu(t.visualItemRect(_row(panel, tree)).center())
        assert found, "the right-click menu offers Delete"
        found[0].trigger()
        _app.processEvents()
        assert tree not in scene.groups
        assert _is_gone(panel, tree)
    finally:
        _close(win)


def test_the_bar_has_no_isolate_button():
    """Isolate is the row's target, the header's and the menu's: the bar
    keeps Rename and Expand all only, drawn with the shared Layers set."""
    from views.icons import tool_icon
    from views.outliner import node_icon
    building, _tree = _building()
    win, _scene, panel = _window_with(building)
    try:
        assert not hasattr(panel, "_isolate_btn")
        assert panel._rename_btn is not None and panel._expand_btn is not None
        assert panel._rename_btn.parent() is panel
        assert panel._expand_btn.parent() is panel
        assert not tool_icon("layers_rename").isNull()
        assert (panel._rename_btn.icon().cacheKey()
                == node_icon("layers_rename").cacheKey())
        key = ("layers_collapse" if panel._all_expanded()
               else "layers_expand")
        assert (panel._expand_btn.icon().cacheKey()
                == node_icon(key).cacheKey())
    finally:
        _close(win)


def test_a_section_plane_row_is_deleted_too():
    """Individual elements as well as groups: a plane's row goes with
    Delete, and Ctrl+Z brings it back."""
    from PySide6.QtGui import QVector3D
    from core.section import SectionPlane
    building, _tree = _building()
    win, scene, panel = _window_with(building)
    try:
        plane = SectionPlane(QVector3D(0, 0, 1), QVector3D(0, 0, 1),
                             name="Cut A")
        scene.section_planes.append(plane)
        scene.version += 1
        panel.refresh()
        row = panel._sec_items[id(plane)]
        assert row is not None
        panel.delete_rows([row])
        _app.processEvents()
        assert plane not in scene.section_planes
        assert panel._sec_items.get(id(plane)) is None
        win.viewport.history.undo()
        panel.refresh()
        assert plane in scene.section_planes
    finally:
        _close(win)


def _is_gone(panel, group) -> bool:
    return id(group) not in panel._items
