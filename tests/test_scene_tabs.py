# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The active project's scenes as tabs under the viewport
(views/scene_tabs.py): on by default, each project with its own choice
from its tab's right-click menu, and only while the project has scenes; a
click shows a scene, «+» keeps the current view as one, a drag changes the
order, a double-click renames, and the row follows the Scenes panel."""
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
    assert win._doc.scene_tabs
    _scene(win, "Exterior")
    assert not row.isHidden()
    lay = win._doc_area.layout()
    assert lay.indexOf(row) > lay.indexOf(win._doc_stack)   # under the view
    from PySide6.QtWidgets import QTabBar
    assert row.tabs.shape() == QTabBar.RoundedSouth


def test_plus_adds_a_scene_and_marks_it(win):
    win.tray.scenes.add_scene()
    row = _row(win)
    row.plus.click()                        # the current view → a scene
    assert len(win.viewport.scene.saved_views) == 2
    assert _names(win) == [v.name for v in win.viewport.scene.saved_views]
    assert row.tabs.currentIndex() == 1     # the new one, marked


# ---- the row only with scenes (Marco's decision, 0.6.1) ----------------------

def test_no_scenes_no_row_and_the_panel_makes_the_first(win):
    row = _row(win)
    assert not win.viewport.scene.saved_views and row.isHidden()
    assert win._act_scene_tabs.isChecked()     # the choice is still «on»
    win.tray.scenes.add_scene()                # the panel's «+ Scene»
    assert not row.isHidden()
    assert _names(win) == [win.viewport.scene.saved_views[0].name]
    assert row.tabs.currentIndex() == 0


def test_the_panels_button_itself_brings_the_row(win):
    from core.i18n import tr
    from PySide6.QtWidgets import QPushButton
    plus = next(b for b in win.tray.scenes.findChildren(QPushButton)
                if b.text() == tr("+ Scene"))
    assert _row(win).isHidden()
    plus.click()
    assert not _row(win).isHidden()


def test_the_last_scene_deleted_takes_the_row_away_and_undo_follows(win):
    win.tray.scenes.add_scene()
    row = _row(win)
    view = win.viewport.scene.saved_views[0]
    win.tray.scenes.delete_views([view])
    assert row.isHidden()
    win._on_undo()
    assert not row.isHidden() and _names(win) == [view.name]
    win._on_redo()
    assert row.isHidden()


def test_undoing_the_first_scene_made_by_a_command_follows(win):
    """Undo of a scene made through the history (Create plan does)."""
    from core.history import DeleteScenesCommand
    win.tray.scenes.add_scene()
    win.tray.scenes.add_scene()
    views = list(win.viewport.scene.saved_views)
    win.viewport.history.execute(DeleteScenesCommand(views))
    win.viewport.notify_scene_changed()
    assert _row(win).isHidden()
    win._on_undo()
    assert not _row(win).isHidden() and len(_names(win)) == 2


def test_the_row_follows_the_project_in_front(win):
    win.tray.scenes.add_scene()
    first = win._doc
    second = win._new_document()
    assert win._doc is second and _row(win).isHidden()
    win.activate_document(first)
    assert not _row(win).isHidden() and len(_names(win)) == 1
    win.activate_document(second)
    assert _row(win).isHidden()


def test_hidden_by_choice_stays_hidden_with_its_first_scene(win):
    win.set_scene_tabs(False)
    win.tray.scenes.add_scene()
    assert _row(win).isHidden() and not win._act_scene_tabs.isChecked()
    win.set_scene_tabs(True)
    assert not _row(win).isHidden()


def test_turning_it_on_without_scenes_says_why_no_row_came_up(win):
    from core.i18n import tr
    win.set_scene_tabs(False)
    win._act_scene_tabs.trigger()              # Alt+E
    assert _row(win).isHidden() and win._doc.scene_tabs
    assert win.statusBar().currentMessage() == tr(
        "This project has no scenes yet: its tabs appear with the first one "
        "(Scenes panel, «+ Scene»).")


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
    assert second.scene_tabs                # B has none of A's scenes
    assert _row(win).isHidden()
    _scene(win, "Otra")
    assert _names(win) == ["Otra"] and not _row(win).isHidden()
    win.activate_document(first)
    assert _row(win).isHidden()             # A: still off
    win.set_scene_tabs(True)
    assert _names(win) == ["Exterior"]


def test_the_tab_menu_turns_them_off_and_on(win):
    _scene(win, "Exterior")
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
    _scene(win, "Exterior")
    act = win._act_scene_tabs
    assert act.shortcut() == QKeySequence("Alt+E")
    assert act.isChecked()
    act.trigger()                                  # Alt+E
    assert _row(win).isHidden() and not win._doc.scene_tabs
    first = win._doc
    win.viewport.scene.version += 1
    second = win._new_document()                   # its own choice: on
    assert second.scene_tabs and act.isChecked()
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
    _scene(win, "Exterior")
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


# ---- rename and reorder (Marco, 0.6.1) ---------------------------------------

def _settle(ms=40):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _saved(win):
    return [v.name for v in win.viewport.scene.saved_views]


def _panel(win):
    lst = win.tray.scenes.list
    return [lst.item(i).text() for i in range(lst.count())]


def _in_step(win):
    """Row, panel and the document's list say the same."""
    assert _names(win) == _panel(win) == _saved(win)
    return _saved(win)


def _shown_row(win, *names):
    for n in names:
        _scene(win, n)
    win.show()
    _settle()
    return _row(win).tabs


def _mouse(tabs, kind, pos, buttons):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    p = QPointF(pos)
    button = Qt.NoButton if kind.name == "MouseMove" else Qt.LeftButton
    QApplication.sendEvent(tabs, QMouseEvent(
        kind, p, QPointF(tabs.mapToGlobal(pos)), button, buttons,
        Qt.NoModifier))


def _press_and_drag(tabs, index, to):
    """Press tab ``index`` and carry it past tab ``to``; the button is still
    down."""
    from PySide6.QtCore import QEvent, QPoint, Qt
    start = tabs.tabRect(index).center()
    _mouse(tabs, QEvent.MouseButtonPress, start, Qt.LeftButton)
    target = tabs.tabRect(to)
    x = target.right() - 2 if to > index else target.left() + 2
    for step in range(1, 9):
        at = QPoint(start.x() + (x - start.x()) * step // 8, start.y())
        _mouse(tabs, QEvent.MouseMove, at, Qt.LeftButton)
    return QPoint(x, start.y())


def _drag(tabs, index, to):
    from PySide6.QtCore import QEvent, Qt
    end = _press_and_drag(tabs, index, to)
    _mouse(tabs, QEvent.MouseButtonRelease, end, Qt.NoButton)
    _settle(300)                               # Qt's sliding animation


def test_dragging_a_tab_changes_the_order_in_one_undo_step(win):
    tabs = _shown_row(win, "A", "B", "C")
    steps = len(win.viewport.history.undo_stack)
    _drag(tabs, 0, 2)
    assert _in_step(win) == ["B", "C", "A"]
    assert len(win.viewport.history.undo_stack) == steps + 1
    win._on_undo()
    assert _in_step(win) == ["A", "B", "C"]
    win._on_redo()
    assert _in_step(win) == ["B", "C", "A"]


def test_dragging_a_tab_leaves_the_view_and_the_mark_alone(win):
    tabs = _shown_row(win, "A", "B", "C")
    tabs.setCurrentIndex(1)                    # «B» is the scene shown
    cam = win.viewport.camera
    cam.set_view("right")
    pose = (cam.yaw, cam.pitch, cam.distance)
    shown = []
    _row(win).sceneClicked.connect(shown.append)
    _drag(tabs, 0, 2)
    assert shown == []
    assert (cam.yaw, cam.pitch, cam.distance) == pose
    assert tabs.tabText(tabs.currentIndex()) == "B"


def test_a_click_shows_the_scene_when_it_lets_go(win):
    from PySide6.QtCore import QEvent, Qt
    tabs = _shown_row(win, "A", "B")
    shown = []
    _row(win).sceneClicked.connect(shown.append)
    at = tabs.tabRect(1).center()
    _mouse(tabs, QEvent.MouseButtonPress, at, Qt.LeftButton)
    assert shown == []
    _mouse(tabs, QEvent.MouseButtonRelease, at, Qt.NoButton)
    assert shown == [1]
    assert _saved(win) == ["A", "B"]


def test_the_list_changing_during_a_drag_does_not_rebuild_under_it(win):
    tabs = _shown_row(win, "A", "B", "C")
    from PySide6.QtCore import QEvent, Qt
    end = _press_and_drag(tabs, 0, 2)
    win.tray.scenes.refresh()                  # an edit passing by
    assert [tabs.tabText(i) for i in range(3)] == ["B", "C", "A"]  # untouched
    _mouse(tabs, QEvent.MouseButtonRelease, end, Qt.NoButton)
    _settle(300)
    assert _in_step(win) == ["B", "C", "A"]


def test_a_scene_added_during_a_press_reaches_the_row_after_it(win):
    from PySide6.QtCore import QEvent, Qt
    tabs = _shown_row(win, "A", "B")
    at = tabs.tabRect(0).center()
    _mouse(tabs, QEvent.MouseButtonPress, at, Qt.LeftButton)
    _scene(win, "C")
    assert tabs.count() == 2
    _mouse(tabs, QEvent.MouseButtonRelease, at, Qt.NoButton)
    assert _in_step(win) == ["A", "B", "C"]


def test_a_dragged_order_is_saved_in_the_document(win, tmp_path):
    from formats import igz
    tabs = _shown_row(win, "A", "B", "C")
    _drag(tabs, 2, 0)
    assert _saved(win) == ["C", "A", "B"]
    win.tray.scenes.rename_view(win.viewport.scene.saved_views[1], "Planta")
    path = tmp_path / "orden.igz"
    igz.save_scene(win.viewport.scene, path)
    from core.scene import Scene
    back = Scene()
    igz.load_into(back, path)
    assert [v.name for v in back.saved_views] == ["C", "Planta", "B"]


def _answer(monkeypatch, text, ok=True):
    from PySide6.QtWidgets import QInputDialog
    asked = []

    def get_text(parent, title, label, *a, **kw):
        asked.append(kw.get("text"))
        return text, ok
    monkeypatch.setattr(QInputDialog, "getText", get_text)
    return asked


def test_a_scene_tab_renames_from_its_menu_in_one_undo_step(win, monkeypatch):
    from core.i18n import tr
    _scene(win, "Exterior")
    _scene(win, "Planta")
    asked = _answer(monkeypatch, "  Planta baja ")
    steps = len(win.viewport.history.undo_stack)
    menu = win._build_scene_tab_menu(1)
    next(a for a in menu.actions() if a.text() == tr("Rename…")).trigger()
    _settle()
    assert asked == ["Planta"]
    assert _in_step(win) == ["Exterior", "Planta baja"]
    assert len(win.viewport.history.undo_stack) == steps + 1
    win._on_undo()
    assert _in_step(win) == ["Exterior", "Planta"]
    win._on_redo()
    assert _in_step(win) == ["Exterior", "Planta baja"]


def test_a_double_click_on_a_tab_renames_it(win, monkeypatch):
    from PySide6.QtCore import QEvent, Qt
    tabs = _shown_row(win, "A", "B")
    _answer(monkeypatch, "Nuevo")
    at = tabs.tabRect(1).center()
    _mouse(tabs, QEvent.MouseButtonDblClick, at, Qt.LeftButton)
    _mouse(tabs, QEvent.MouseButtonRelease, at, Qt.NoButton)
    _settle()
    assert _in_step(win) == ["A", "Nuevo"]


def test_a_rename_cancelled_or_refused_is_no_undo_step(win, monkeypatch):
    _scene(win, "A")
    _scene(win, "B")
    steps = len(win.viewport.history.undo_stack)
    panel = win.tray.scenes
    view = win.viewport.scene.saved_views[0]
    _answer(monkeypatch, "Otro", ok=False)
    panel.ask_rename(view)
    assert not panel.rename_view(view, "B")       # another scene's
    assert not panel.rename_view(view, "   ")     # empty
    assert not panel.rename_view(view, "A")       # the same
    assert _in_step(win) == ["A", "B"]
    assert len(win.viewport.history.undo_stack) == steps


def test_the_mark_stays_on_a_renamed_scene(win):
    tabs = _shown_row(win, "A", "B", "C")
    tabs.setCurrentIndex(2)
    win.tray.scenes.rename_view(win.viewport.scene.saved_views[2], "Z")
    assert tabs.tabText(tabs.currentIndex()) == "Z"


def test_the_sheet_views_follow_a_rename_and_its_undo(win):
    from core.composition import Composicion, MarcoVista
    _scene(win, "Planta")
    scene = win.viewport.scene
    sheet = Composicion(name="L1")
    frame = MarcoVista(view_key="scene:Planta")
    sheet.frames.append(frame)
    scene.compositions.append(sheet)
    win.tray.scenes.rename_view(scene.saved_views[0], "Baja")
    assert frame.view_key == "scene:Baja"
    win._on_undo()
    assert frame.view_key == "scene:Planta"
    win._on_redo()
    assert frame.view_key == "scene:Baja"


def test_the_composers_view_sources_follow_rename_order_and_undo(
        win, monkeypatch):
    from views.composer import ComposerWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    _scene(win, "A")
    _scene(win, "B")
    comp = win._ensure_composer()

    def sources():
        box = comp.view_combo
        return [box.itemData(i)[6:] for i in range(box.count())
                if str(box.itemData(i)).startswith("scene:")]
    win.tray.scenes.rename_view(win.viewport.scene.saved_views[0], "Z")
    assert sources() == ["Z", "B"]
    win._on_undo()
    assert sources() == ["A", "B"]
    win.tray.scenes.move_view(win.viewport.scene.saved_views[1], 0)
    assert sources() == ["B", "A"]
    comp.close()


def test_the_composers_panel_renames_in_one_undo_step(win):
    from views.outliner import SheetsPanel
    _scene(win, "A")
    panel = SheetsPanel.__new__(SheetsPanel)
    panel._window = win
    panel._shape = None
    panel._scene = lambda: win.viewport.scene
    panel.refresh = lambda: None
    SheetsPanel.rename_scene(panel, win.viewport.scene.saved_views[0], "B")
    assert _in_step(win) == ["B"]
    win._on_undo()
    assert _in_step(win) == ["A"]


# ---- the Scenes panel: its menu, ↑ ↓ ------------------------------------------

def test_the_panels_own_editor_renames_in_one_undo_step(win):
    _scene(win, "A")
    _scene(win, "B")
    steps = len(win.viewport.history.undo_stack)
    win.tray.scenes.list.item(0).setText("Z")
    assert _in_step(win) == ["Z", "B"]
    assert len(win.viewport.history.undo_stack) == steps + 1
    win._on_undo()
    assert _in_step(win) == ["A", "B"]


def test_the_panels_editor_refused_puts_the_real_name_back(win):
    _scene(win, "A")
    _scene(win, "B")
    win.tray.scenes.list.item(0).setText("B")
    assert _in_step(win) == ["A", "B"]


def test_the_panels_menu_renames_and_moves(win):
    from core.i18n import tr
    from PySide6.QtWidgets import QAbstractItemView
    _scene(win, "A")
    _scene(win, "B")
    _scene(win, "C")
    win.show()
    _settle()
    panel = win.tray.scenes

    def menu_of(row):
        m = panel._build_list_menu(panel.list.item(row))
        return m, {a.text(): a for a in m.actions()}
    assert panel._build_list_menu(None) is None     # off the rows
    menu, acts = menu_of(0)
    up, down = tr("Move up (Alt+↑)"), tr("Move down (Alt+↓)")
    assert not acts[up].isEnabled() and acts[down].isEnabled()
    acts[down].trigger()
    assert _in_step(win) == ["B", "A", "C"]
    menu, acts = menu_of(2)
    assert acts[up].isEnabled() and not acts[down].isEnabled()
    acts[up].trigger()
    assert _in_step(win) == ["B", "C", "A"]
    menu, acts = menu_of(0)
    acts[tr("Rename…")].trigger()
    assert panel.list.state() == QAbstractItemView.EditingState


def test_the_panels_arrows_keep_moving_the_same_scene(win):
    _scene(win, "A")
    _scene(win, "B")
    _scene(win, "C")
    panel = win.tray.scenes
    panel.list.setCurrentRow(2)
    panel.up_btn.click()
    panel.up_btn.click()                       # the same scene, not the row
    assert _in_step(win) == ["C", "A", "B"]
    assert panel.list.currentItem().text() == "C"
    assert [i.text() for i in panel.list.selectedItems()] == ["C"]
    steps = len(win.viewport.history.undo_stack)
    panel.up_btn.click()                       # already first: no step
    assert steps == len(win.viewport.history.undo_stack)
    panel.down_btn.click()
    assert _in_step(win) == ["A", "C", "B"]
    win._on_undo()
    assert _in_step(win) == ["C", "A", "B"]


def test_the_panels_arrows_leave_the_buttons_on_one_line(win):
    """At the style's default width «↓» fell onto a line of its own."""
    _scene(win, "A")
    panel = win.tray.scenes
    win.show()
    panel.resize(420, panel.height())
    _settle()
    assert panel.down_btn.width() <= 32 and panel.up_btn.width() <= 32
    assert panel.down_btn.y() == panel.up_btn.y()


def test_alt_arrows_move_it_where_the_list_has_the_keys(win):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence
    _scene(win, "A")
    _scene(win, "B")
    panel = win.tray.scenes
    panel.list.setCurrentRow(0)
    acts = {a.shortcut().toString(): a for a in panel.list.actions()}
    assert acts["Alt+Down"].shortcutContext() == Qt.WidgetShortcut
    acts[QKeySequence("Alt+Down").toString()].trigger()
    assert _in_step(win) == ["B", "A"]
    acts["Alt+Up"].trigger()
    assert _in_step(win) == ["A", "B"]


def test_a_refresh_keeps_what_the_panel_has_picked(win):
    _scene(win, "A")
    _scene(win, "B")
    _scene(win, "C")
    panel = win.tray.scenes
    panel.list.item(0).setSelected(True)
    panel.list.item(2).setSelected(True)
    panel.refresh()
    assert sorted(i.text() for i in panel.list.selectedItems()) == ["A", "C"]


def test_a_scene_shown_from_the_panel_marks_its_tab(win):
    tabs = _shown_row(win, "A", "B")
    panel = win.tray.scenes
    panel.show_view(win.viewport.scene.saved_views[1])
    assert tabs.currentIndex() == 1
    panel.show_view(win.viewport.scene.saved_views[0])
    assert tabs.currentIndex() == 0

