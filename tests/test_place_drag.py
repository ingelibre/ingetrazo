# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Dragging a component from a list into the view places it where it is
let go (``views/place_drag.py``): the bundled tree, «My Library» and «In
model» all offer it. ``QDrag.exec`` is modal, so the drag's events are
sent to the view by hand, as Qt would send them; every component is
generated here."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

from core import user_library as lib
from views import place_drag


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _box_component(name="Mesa", at=(5.0, 5.0, 0.0)):
    """A 2 × 1 × 3 m box as a component instance placed at ``at``."""
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    c = [V(dx * 2, dy, dz * 3) for dz in (0, 1) for dy in (0, 1)
         for dx in (0, 1)]
    for q in [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3),
              (0, 4, 6, 2), (1, 3, 7, 5)]:
        m.add_face([c[i] for i in q])
    g = Group(m, name=name)
    g.xform = QMatrix4x4()
    g.xform.translate(*at)
    g.component = True
    return g


def _igz(path: Path) -> Path:
    from core.scene import Scene
    comp = _box_component(path.stem)
    s = Scene()
    s.groups.append(comp)
    return lib.save_component(comp, s, path)


@pytest.fixture
def library(tmp_path, monkeypatch):
    root = tmp_path / "Mis componentes"
    root.mkdir()
    monkeypatch.setenv("INGETRAZO_USER_LIBRARY", str(root))
    return root


@pytest.fixture
def win(library):
    QApplication.instance() or QApplication([])
    from views.main_window import MainWindow
    w = MainWindow()
    w.viewport.resize(900, 600)
    yield w
    place_drag.finished(Qt.IgnoreAction)
    w._saved_version = w.viewport.scene.version
    w.close()


def _centre(vp) -> QPoint:
    return QPoint(vp.width() // 2, vp.height() // 2)


def _drag_over(vp, mime, at: QPoint):
    enter = QDragEnterEvent(at, place_drag.ACTIONS, mime, Qt.LeftButton,
                            Qt.NoModifier)
    vp.dragEnterEvent(enter)
    move = QDragMoveEvent(at + QPoint(3, 2), place_drag.ACTIONS, mime,
                          Qt.LeftButton, Qt.NoModifier)
    vp.dragMoveEvent(move)
    return enter, move


def _drop(vp, mime, at: QPoint):
    drop = QDropEvent(QPointF(at), place_drag.ACTIONS, mime, Qt.LeftButton,
                      Qt.NoModifier)
    vp.dropEvent(drop)
    action = drop.dropAction() if drop.isAccepted() else Qt.IgnoreAction
    place_drag.finished(action)
    return drop


def _library_row(win, name, refresh=True):
    w = win.tray.components.user_library
    if refresh:
        w.refresh()
    for it in w.items():
        if it.text(0) == name:
            return w, it
    raise AssertionError(name)


# ---- the token ------------------------------------------------------------
def test_a_drag_carries_its_starter_until_it_is_over():
    QApplication.instance() or QApplication([])
    calls = []
    mime = place_drag.offer(QMimeData(), lambda: calls.append(1))
    assert mime.hasFormat(place_drag.MIME)
    starter = place_drag.starter_of(mime)
    assert callable(starter)
    starter()
    assert calls == [1]
    place_drag.finished(Qt.IgnoreAction)
    assert place_drag.starter_of(mime) is None        # that drag is over
    assert place_drag.starter_of(QMimeData()) is None


def test_a_new_drag_replaces_the_old_token():
    QApplication.instance() or QApplication([])
    old = place_drag.offer(QMimeData(), lambda: None)
    new = place_drag.offer(QMimeData(), lambda: None)
    assert place_drag.starter_of(old) is None
    assert place_drag.starter_of(new) is not None
    place_drag.finished(Qt.IgnoreAction)


# ---- the view ---------------------------------------------------------------
def test_dragging_a_library_file_into_the_view_places_it(win, library):
    from tools.place_group import PlaceGroupTool
    _igz(library / "Mesa.igz")
    w, row = _library_row(win, "Mesa")
    starter = w.tree.drag_starter([row])
    assert starter is not None
    vp = win.viewport
    mime = place_drag.offer(QMimeData(), starter)
    before = len(vp.scene.groups)
    undo = len(vp.history.undo_stack)
    enter, move = _drag_over(vp, mime, _centre(vp))
    # The piece is on the pointer as soon as the drag enters the view.
    assert enter.isAccepted() and move.isAccepted()
    assert enter.dropAction() == Qt.CopyAction
    assert isinstance(vp.active_tool, PlaceGroupTool)
    drop = _drop(vp, mime, _centre(vp))
    assert drop.isAccepted()
    groups = vp.scene.groups
    assert len(groups) == before + 1
    assert groups[-1].name == "Mesa" and groups[-1].is_component()
    # One undo step, and Select is back, as after a click of the tool.
    assert len(vp.history.undo_stack) == undo + 1
    assert not isinstance(vp.active_tool, PlaceGroupTool)


def test_let_go_outside_the_view_places_nothing(win, library):
    from tools.place_group import PlaceGroupTool
    _igz(library / "Mesa.igz")
    w, row = _library_row(win, "Mesa")
    vp = win.viewport
    mime = place_drag.offer(QMimeData(), w.tree.drag_starter([row]))
    before = len(vp.scene.groups)
    _drag_over(vp, mime, _centre(vp))
    assert isinstance(vp.active_tool, PlaceGroupTool)
    place_drag.finished(Qt.IgnoreAction)       # back to the list, or Esc
    assert len(vp.scene.groups) == before
    assert not isinstance(vp.active_tool, PlaceGroupTool)


def test_the_starter_runs_once_per_drag(win):
    vp = win.viewport
    calls = []

    def starter():
        calls.append(1)
        win._start_place(_box_component("Caja"))
    mime = place_drag.offer(QMimeData(), starter)
    _drag_over(vp, mime, _centre(vp))
    _drag_over(vp, mime, _centre(vp) + QPoint(10, 10))
    assert calls == [1]
    _drop(vp, mime, _centre(vp))
    assert vp.scene.groups[-1].name == "Caja"


def test_a_starter_that_puts_nothing_on_the_pointer_is_refused(win):
    vp = win.viewport
    calls = []
    mime = place_drag.offer(QMimeData(), lambda: calls.append(1))
    enter, move = _drag_over(vp, mime, _centre(vp))
    assert calls == [1]                     # asked once, not on every move
    assert not enter.isAccepted() and not move.isAccepted()


def test_another_drag_is_left_to_the_view_as_before(win):
    vp = win.viewport
    mime = QMimeData()
    mime.setText("tray-section")
    enter, _move = _drag_over(vp, mime, _centre(vp))
    assert not enter.isAccepted()


# ---- the lists that offer it -------------------------------------------------
def test_a_folder_row_or_several_rows_only_move(win, library):
    lib.new_folder(library, "Cocina")
    _igz(library / "Mesa.igz")
    _igz(library / "Silla.igz")
    w, folder = _library_row(win, "Cocina")
    _w, mesa = _library_row(win, "Mesa", refresh=False)
    _w, silla = _library_row(win, "Silla", refresh=False)
    assert w.tree.drag_starter([folder]) is None
    assert w.tree.drag_starter([mesa, silla]) is None


def test_the_bundled_tree_offers_what_its_double_click_runs(win):
    tree = win.tray.components.tree
    assert tree.tree.starter_for is not None
    key = next(iter(tree._by_key))
    assert tree.tree.starter_for(key) is tree._by_key[key].insert
    assert tree.tree.starter_for("component:no-such") is None


def test_an_in_model_row_dragged_places_a_shared_copy(win):
    vp = win.viewport
    comp = _box_component("Armario")
    vp.scene.groups.append(comp)
    vp.notify_scene_changed()
    panel = win.tray.components
    panel.refresh_in_model()
    lst = panel._in_model
    row = next(lst.item(i) for i in range(lst.count())
               if "Armario" in lst.item(i).text())
    starter = lst.starter_for(row)
    assert starter is not None
    mime = place_drag.offer(QMimeData(), starter)
    _drag_over(vp, mime, _centre(vp))
    _drop(vp, mime, _centre(vp))
    copies = [g for g in vp.scene.groups if g.mesh is comp.mesh]
    assert len(copies) == 2                 # the same definition, shared


def test_the_in_model_list_drags_only(win):
    from PySide6.QtWidgets import QAbstractItemView
    lst = win.tray.components._in_model
    assert lst.dragEnabled()
    assert lst.dragDropMode() == QAbstractItemView.DragOnly
