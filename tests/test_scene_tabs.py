# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The active project's scenes as tabs under the viewport
(views/scene_tabs.py): on by default, each project with its own choice
from its tab's right-click menu; a click shows a scene, «+» keeps the
current view as one, a project without scenes says how to make one, and
the row follows the Scenes panel."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    for doc in list(w._documents):
        doc.saved_content = doc.viewport.scene.content_version
    w._saved_version = w.viewport.scene.version
    w.close()


def _row(win):
    return win._scene_tabs


def _names(win):
    tabs = _row(win).tabs
    return [tabs.tabText(i) for i in range(tabs.count())]


def _scene(win, name, view="top"):
    from core.saved_views import SavedView
    cam = win.viewport.camera
    cam.set_view(view)
    win.viewport.scene.saved_views.append(
        SavedView.capture(name, win.viewport.scene, cam))
    win.tray.scenes.refresh()


def test_on_by_default_under_the_viewport(win):
    row = _row(win)
    assert not row.isHidden()
    lay = win._doc_area.layout()
    assert lay.indexOf(row) > lay.indexOf(win._doc_stack)   # under the view
    from PySide6.QtWidgets import QTabBar
    assert row.tabs.shape() == QTabBar.RoundedSouth


def test_without_scenes_it_says_how_and_plus_adds_one(win):
    row = _row(win)
    assert row.tabs.isHidden() and not row.hint.isHidden()
    row.plus.click()                        # the current view → a scene
    assert len(win.viewport.scene.saved_views) == 1
    assert _names(win) == [win.viewport.scene.saved_views[0].name]
    assert not row.tabs.isHidden() and row.hint.isHidden()
    assert row.tabs.currentIndex() == 0     # the new one, marked


def test_scenes_from_the_panel_reach_the_tabs(win):
    _scene(win, "Exterior", "iso")
    _scene(win, "Planta", "top")
    assert _names(win) == ["Exterior", "Planta"]
    win.tray.scenes.add_scene()
    assert len(_names(win)) == 3


def test_a_click_shows_that_scene_and_marks_it(win):
    _scene(win, "Planta", "top")
    _scene(win, "Alzado", "front")
    cam = win.viewport.camera
    cam.set_view("iso")
    _row(win).tabs.tabBarClicked.emit(0)
    top = type(cam)()
    top.set_view("top")
    assert (round(cam.yaw, 6), round(cam.pitch, 6)) == \
        (round(top.yaw, 6), round(top.pitch, 6))
    assert _row(win).tabs.currentIndex() == 0


def test_each_project_lists_its_own_scenes_and_keeps_its_choice(win):
    _scene(win, "Exterior")
    first = win._doc
    win.set_scene_tabs(False)               # A: off
    assert _row(win).isHidden()
    second = win._new_document()            # B: the default, on
    assert win._doc is second
    assert not _row(win).isHidden()
    assert _names(win) == []                # B has none of A's scenes
    win.activate_document(first)
    assert _row(win).isHidden()             # A: still off
    win.set_scene_tabs(True)
    assert _names(win) == ["Exterior"]


def test_the_tab_menu_turns_them_off_and_on(win):
    menu = win._build_project_tab_menu(win._doc)
    act = next(a for a in menu.actions() if a.isCheckable())
    from core.i18n import tr
    assert act.text() == tr("Show scenes as tabs") and act.isChecked()
    act.setChecked(False)
    assert _row(win).isHidden() and not win._doc.scene_tabs
    act.setChecked(True)
    assert not _row(win).isHidden()
    menu.close()


def test_alt_e_shows_and_hides_them_for_the_project_in_front(win):
    from PySide6.QtGui import QKeySequence
    act = win._act_scene_tabs
    assert act.shortcut() == QKeySequence("Alt+E")
    assert act.isChecked()
    act.trigger()                                  # Alt+E
    assert _row(win).isHidden() and not win._doc.scene_tabs
    first = win._doc
    win.viewport.scene.version += 1
    second = win._new_document()                   # its own choice: on
    assert act.isChecked() and not _row(win).isHidden()
    win.activate_document(first)
    assert not act.isChecked()                     # follows the project
    act.trigger()
    assert not _row(win).isHidden()


def test_alt_e_is_no_other_commands_shortcut(win):
    from PySide6.QtGui import QAction, QKeySequence
    alt_e = QKeySequence("Alt+E")
    owners = {a.text() for a in win.findChildren(QAction)
              if alt_e in a.shortcuts()}
    from core.i18n import tr
    assert owners == {tr("Show scenes as tabs")}


def test_a_right_click_on_a_tab_asks_for_its_menu(win):
    bar = win._project_tabs
    # Only the signal: the window's handler opens a real (modal) menu.
    bar.menuRequested.disconnect(win._project_tab_menu)
    seen = []
    bar.menuRequested.connect(lambda doc, pos: seen.append(doc))
    bar._on_menu(bar.tabs.tabRect(0).center())
    assert seen == [win._doc]


def test_an_opened_project_lists_the_scenes_it_was_saved_with(win, tmp_path):
    from core.camera import OrbitCamera
    from core.saved_views import SavedView
    from core.scene import Scene
    from formats import igz
    from PySide6.QtGui import QVector3D as V
    scene = Scene()
    scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    for name in ("Exterior", "Planta"):
        scene.saved_views.append(SavedView.capture(name, scene, OrbitCamera()))
    path = tmp_path / "con-escenas.igz"
    igz.save_scene(scene, path)
    win.open_path(path)
    assert _names(win) == ["Exterior", "Planta"]


def test_the_accent_line_marks_the_scene_shown(win):
    _scene(win, "Exterior")
    win.show()
    QApplication.processEvents()
    tabs = _row(win).tabs
    tabs.setCurrentIndex(0)
    line = tabs.underline_rect()
    assert line is not None and tabs.tabRect(0).contains(line)
    from views.theme import accent_color
    c = tabs.grab().toImage().pixelColor(line.center())
    a = accent_color()
    assert abs(c.red() - a.red()) + abs(c.green() - a.green()) \
        + abs(c.blue() - a.blue()) < 40


def test_a_scene_tab_deletes_its_scene_from_its_menu(win):
    from core.i18n import tr
    _scene(win, "Exterior", "iso")
    _scene(win, "Planta", "top")
    _scene(win, "Alzado", "front")
    menu = win._build_scene_tab_menu(1)
    delete = next(a for a in menu.actions() if a.text() == tr("Delete"))
    delete.trigger()
    assert _names(win) == ["Exterior", "Alzado"]
    assert [v.name for v in win.viewport.scene.saved_views] == \
        ["Exterior", "Alzado"]
    win.viewport.history.undo()                  # one undo step brings it back
    win.tray.scenes.refresh()
    assert _names(win) == ["Exterior", "Planta", "Alzado"]


def test_a_right_click_on_a_scene_tab_asks_for_its_menu(win):
    _scene(win, "Exterior")
    row = _row(win)
    row.menuRequested.disconnect(win._scene_tab_menu)   # not a real menu
    seen = []
    row.menuRequested.connect(lambda i, pos: seen.append(i))
    row._on_menu(row.tabs.tabRect(0).center())
    assert seen == [0]


@pytest.mark.parametrize("count", [1, 2, 4])
def test_plus_sits_right_after_the_last_scene(win, count):
    """With one scene «+» stood far away: the bar kept the scroll arrows'
    room."""
    win.show()
    for _ in range(count):
        win.tray.scenes.add_scene()
    QApplication.processEvents()
    QApplication.processEvents()
    row = _row(win)
    tabs = row.tabs
    last = tabs.tabRect(tabs.count() - 1)
    end = tabs.mapTo(row, last.topRight()).x()
    start = row.plus.mapTo(row, row.plus.rect().topLeft()).x()
    assert 0 <= start - end <= 2


def test_the_scene_plus_is_the_same_as_the_projects_plus(win):
    """The scene «+» was smaller and out of line with its tabs."""
    win.show()
    win.tray.scenes.add_scene()
    QApplication.processEvents()
    row = _row(win)
    mine, theirs = row.plus, win._project_tabs.plus
    assert mine.iconSize() == theirs.iconSize()
    assert mine.size() == theirs.size()
    tabs = row.tabs
    top = tabs.mapTo(row, tabs.tabRect(0).topLeft()).y()
    assert abs(mine.y() - top) <= 1                    # level with the tabs
    assert mine.height() == tabs.tabRect(0).height()


def test_a_scene_tab_takes_the_current_view_from_its_menu(win):
    from core.i18n import tr
    _scene(win, "Planta", "top")
    cam = win.viewport.camera
    cam.set_view("front")
    menu = win._build_scene_tab_menu(0)
    update = next(a for a in menu.actions() if a.text() == tr("Update"))
    update.trigger()                               # Planta now looks front
    cam.set_view("iso")
    _row(win).tabs.tabBarClicked.emit(0)           # show it again
    front = type(cam)()
    front.set_view("front")
    assert (round(cam.yaw, 6), round(cam.pitch, 6)) == \
        (round(front.yaw, 6), round(front.pitch, 6))


# ---- right-click: only a menu (ronda 7) -------------------------------------

def test_a_right_click_on_a_scene_shows_nothing_and_changes_nothing(win):
    """A right-click went to the saved scene: the view jumped back and the
    work in hand seemed lost. It only opens the menu now."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    cam = win.viewport.camera
    cam.set_view("top")
    win.tray.scenes.add_scene()
    cam.set_view("front")
    pose = (cam.yaw, cam.pitch, cam.distance)
    shown = []
    win._scene_tabs.sceneClicked.connect(shown.append)
    win._scene_tabs.menuRequested.disconnect(win._scene_tab_menu)
    tabs = _row(win).tabs
    QTest.mouseClick(tabs, Qt.RightButton, Qt.NoModifier,
                     tabs.tabRect(0).center())
    QApplication.processEvents()
    assert shown == []
    assert (cam.yaw, cam.pitch, cam.distance) == pose
    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier,
                     tabs.tabRect(0).center())
    QApplication.processEvents()
    assert shown == [0]                       # a left click still shows it


def test_the_scene_menus_open_upwards(win):
    from PySide6.QtCore import QPoint
    from views.scene_tabs import menu_upwards
    win.tray.scenes.add_scene()
    menu = win._build_scene_tab_menu(0)
    at = QPoint(300, 700)
    where = menu_upwards(menu, at)
    assert where.x() == at.x()
    assert where.y() + menu.sizeHint().height() == at.y()   # it ends there
    menu.close()


def test_the_bar_hides_the_scenes_from_its_own_menu(win):
    from core.i18n import tr
    row = _row(win)
    assert not row.isHidden()
    menu = win._build_scene_bar_menu()
    hide = next(a for a in menu.actions() if a.text() == tr("Hide scenes"))
    hide.trigger()
    assert row.isHidden() and not win._doc.scene_tabs
    assert not win._act_scene_tabs.isChecked()
    win._act_scene_tabs.trigger()             # Alt+E brings it back
    assert not row.isHidden()


def test_a_right_click_off_the_tabs_asks_for_the_bars_menu(win):
    win.tray.scenes.add_scene()
    row = _row(win)
    row.barMenuRequested.disconnect(win._scene_bar_menu)
    seen = []
    row.barMenuRequested.connect(seen.append)
    tabs = row.tabs
    off = tabs.tabRect(tabs.count() - 1).topRight()
    off.setX(off.x() + 5)
    row._on_menu(off)                         # past the last tab
    row.customContextMenuRequested.emit(row.rect().center())  # the room
    assert len(seen) == 2
