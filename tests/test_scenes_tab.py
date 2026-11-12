# SPDX-License-Identifier: GPL-3.0-or-later
"""Scenes: a tab of its own in the side tray, in line with Layers and the
Browser (#1158).

It was a section of Properties with three buttons and a flat list. Now it
has the bar of Layers (flat icon buttons and a filter) and its kind of
tree: scenes filed in folders, dragged into them or to another place, a
right-click menu with the window's scene actions, a mark on the scene
shown, the list or the thumbnails, and every change goes through the undo
history.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)
else:
    _app = _inst

import core.extensions as extensions                              # noqa: E402
from core import scene_folders as SF                              # noqa: E402


@pytest.fixture
def win(tmp_path, monkeypatch):
    """A window with a throwaway INI, so no layout leaks in or out. The
    pictures are not drawn here (a render each): the tests that want them
    ask for them."""
    path = tmp_path / "prefs.ini"
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    import PySide6.QtCore as qc
    import views.main_window as mw
    from views.tray import ScenesPanel
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory)
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [tmp_path])
    monkeypatch.setattr(ScenesPanel, "_render_thumbnail",
                        lambda self, view: None)
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    for _ in range(3):
        _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _scenes(win, *names):
    """Saved scenes with these names, through the panel's own button."""
    panel = win.scenes_dock.panel
    for name in names:
        panel.tree.clearSelection()
        view = panel._on_add()
        view.name = name
    panel.tree.clearSelection()
    panel._shape = None
    panel.refresh()
    return panel


def _names(win):
    return [v.name for v in win.viewport.scene.saved_views]


def _rows(panel):
    return [it.text(0) for it in panel._rows()]


def _view(win, name):
    return next(v for v in win.viewport.scene.saved_views if v.name == name)


def _folder(panel, name, parent=None):
    """A folder made with the panel's button, renamed to ``name``."""
    panel.tree.clearSelection()
    if parent is not None:
        panel._select_row(panel.folder_row(parent))
    before = set(SF.folders_of(panel._scene()))
    panel._on_add_folder()
    made = (set(SF.folders_of(panel._scene())) - before).pop()
    assert panel.rename_folder(made, name)
    panel.tree.clearSelection()
    return name


# ---- 1. Its own tab ---------------------------------------------------------

def test_scenes_is_a_tab_of_its_own_right_after_layers(win):
    order = [d.objectName() for d in win._default_tray_order()]
    assert order[:4] == ["tray_properties", "tray_project_browser",
                         "tray_layers", "tray_scenes"]
    dock = win.scenes_dock
    assert dock in win._sidebar_docks()          # Window ▸ Panels lists it
    assert not dock.isHidden()
    assert win.layers_dock in win.tabifiedDockWidgets(dock)
    # No longer a section of Properties, and the old name still works.
    assert win.tray.scenes is dock.panel
    assert not win.tray.widget().isAncestorOf(dock.panel)


def test_on_a_first_run_the_tab_comes_right_after_layers(win):
    """Layers is seated again at start-up and goes to the end of the row;
    Scenes follows it there instead of staying in front of it."""
    rows = [row for row, _front in win._dock_tab_rows(win._sidebar_docks())
            if win.scenes_dock in row]
    assert rows, "the Scenes tab is in no row of tabs"
    names = [d.objectName() for d in rows[0]]
    assert names.index("tray_scenes") == names.index("tray_layers") + 1


def test_a_layout_saved_before_the_tab_seats_it_beside_layers(win):
    """A layout saved before the tab existed leaves it apart from the
    other tabs; at start-up it goes back among them."""
    dock = win.scenes_dock
    win.removeDockWidget(dock)
    win.addDockWidget(Qt.RightDockWidgetArea, dock)      # a block apart
    dock.show()
    _app.processEvents()
    assert win.layers_dock not in win.tabifiedDockWidgets(dock)
    win._seat_new_trays()
    _app.processEvents()
    assert win.layers_dock in win.tabifiedDockWidgets(dock)


def test_seated_behind_layers_even_with_extension_tabs_saved_after_it(win):
    """A layout that knows an extension's panels tabbed after Layers, but
    not Scenes: Qt adds a tab at the end of the row, behind them. Scenes
    goes right after Layers; the extensions' tabs follow it, in order."""
    from PySide6.QtWidgets import QDockWidget, QLabel
    exts = []
    for name in ("Extension one", "Extension two"):
        d = QDockWidget(name, win)
        d.setObjectName("extension_" + name.split()[1])
        d.setWidget(QLabel(name))
        win.addDockWidget(Qt.RightDockWidgetArea, d)
        win.tabifyDockWidget(win.layers_dock, d)
        d.show()                 # made after the window showed: hidden
        exts.append(d)
    dock = win.scenes_dock
    win.removeDockWidget(dock)                    # unknown to the layout
    win._seat_new_tray(dock, [win.layers_dock, win.project_browser])
    dock.show()
    _app.processEvents()
    # The row in tab order, Properties aside (tabifiedDockWidgets).
    row = [d.objectName() for d in win.tabifiedDockWidgets(win.tray)]
    at = row.index("tray_layers")
    assert row[at:at + 4] == ["tray_layers", "tray_scenes",
                              "extension_one", "extension_two"]


def test_moved_alone_to_the_other_side_it_stays(win, monkeypatch):
    dock = win.scenes_dock
    win.removeDockWidget(dock)
    win.addDockWidget(Qt.LeftDockWidgetArea, dock)
    dock.show()
    monkeypatch.setattr(win, "restoreDockWidget", lambda d: True)
    win._seat_new_trays()
    assert win.dockWidgetArea(dock) == Qt.LeftDockWidgetArea


def test_restore_default_panels_brings_it_back(win):
    win.set_tray_shown(win.scenes_dock, False)
    assert win.scenes_dock.isHidden()
    win.restore_default_trays()
    assert not win.scenes_dock.isHidden()
    assert win.layers_dock in win.tabifiedDockWidgets(win.scenes_dock)


# ---- 2. The bar of Layers and the Browser -----------------------------------

def test_the_bar_has_flat_icon_buttons_the_filter_and_the_view(win):
    from PySide6.QtWidgets import QPushButton, QToolButton
    panel = win.scenes_dock.panel
    bar = panel.layout().itemAt(0).layout()
    widgets = [bar.itemAt(i).widget() for i in range(bar.count())]
    assert widgets == [panel.add_btn, panel.add_folder_btn, panel.update_btn,
                       panel.search, panel.view_btn]
    for btn in (panel.add_btn, panel.add_folder_btn, panel.update_btn,
                panel.view_btn):
        assert isinstance(btn, QToolButton) and btn.autoRaise()
        assert btn.text() == "" and not btn.icon().isNull()
        assert btn.toolTip()
    assert not panel.findChildren(QPushButton)   # the old text buttons


def test_the_filter_hides_rows_and_stops_dragging(win):
    from PySide6.QtWidgets import QAbstractItemView
    panel = _scenes(win, "Plan Ground", "Plan First", "Elevation North")

    def shown():
        return [it.text(0) for it in panel._rows() if not it.isHidden()]
    panel.search.setText("plan")
    assert shown() == ["Plan Ground", "Plan First"]
    assert panel.tree.dragDropMode() == QAbstractItemView.NoDragDrop
    panel.search.setText("*north")                # a pattern, as in Layers
    assert shown() == ["Elevation North"]
    panel.search.clear()
    assert shown() == ["Plan Ground", "Plan First", "Elevation North"]
    assert panel.tree.dragDropMode() == QAbstractItemView.InternalMove


def test_the_filter_keeps_the_folders_on_the_way_and_a_folder_s_contents(win):
    panel = _scenes(win, "Ground", "North")
    _folder(panel, "Plans")
    panel.drop_rows(("folder", "Plans"), [panel.row_for(_view(win, "Ground"))])

    def shown():
        return [it.text(0) for it in panel._rows() if not it.isHidden()]
    panel.search.setText("ground")
    assert shown() == ["Plans", "Ground"]
    panel.search.setText("plans")                 # the folder: all it holds
    assert shown() == ["Plans", "Ground"]


# ---- 3. The right-click menu ------------------------------------------------

def test_the_menu_runs_the_window_s_scene_actions(win):
    panel = _scenes(win, "A", "B")
    acts = win._scene_actions
    row = panel.row_for(_view(win, "B"))
    menu = panel.context_menu(row)
    assert panel.current_view() is _view(win, "B")
    got = [a for a in menu.actions() if not a.isSeparator()]
    assert got[:5] == [acts[k] for k in ("scene_show", "scene_update",
                                         "scene_rename", "scene_duplicate",
                                         "scene_delete")]
    empty = panel.context_menu(None)
    texts = [a.text() for a in empty.actions() if not a.isSeparator()]
    assert empty.actions()[0] is acts["scene_add"]
    assert "Add folder" in texts


def test_duplicate_from_the_menu_goes_right_after_and_undoes(win):
    panel = _scenes(win, "A", "B")
    panel.select_view(_view(win, "A"))
    win._scene_actions["scene_duplicate"].trigger()
    assert _names(win) == ["A", "A (copy)", "B"]
    assert panel.current_view().name == "A (copy)"
    win.viewport.history.undo()
    panel.refresh()
    assert _names(win) == ["A", "B"]
    assert _rows(panel) == ["A", "B"]


# ---- Folders ----------------------------------------------------------------

def test_a_folder_holds_scenes_and_shows_them_inside(win):
    panel = _scenes(win, "Ground", "First", "North")
    _folder(panel, "Plans")
    rows = [panel.row_for(_view(win, n)) for n in ("Ground", "First")]
    panel.drop_rows(("folder", "Plans"), rows)
    assert _view(win, "Ground").folder == "Plans"
    folder = panel.folder_row("Plans")
    assert [folder.child(i).text(0) for i in range(folder.childCount())] \
        == ["Ground", "First"]
    # The folders first, then the loose scenes — and the one list every
    # place reads in that same order.
    assert _rows(panel) == ["Plans", "Ground", "First", "North"]
    assert _names(win) == ["Ground", "First", "North"]


def test_folders_nest_and_a_folder_never_goes_into_itself(win):
    panel = _scenes(win, "Ground")
    _folder(panel, "Plans")
    _folder(panel, "Floors", parent="Plans")
    assert SF.folder_parent(win.viewport.scene, "Floors") == "Plans"
    assert panel.folder_row("Floors").parent() is panel.folder_row("Plans")
    panel.drop_rows(("folder", "Floors"), [panel.folder_row("Plans")])
    assert SF.folder_parent(win.viewport.scene, "Plans") is None


def test_a_scene_added_with_a_folder_picked_goes_into_it(win):
    panel = _scenes(win)
    _folder(panel, "Plans")
    panel._select_row(panel.folder_row("Plans"))
    view = panel._on_add()
    assert view.folder == "Plans"
    assert panel.row_for(view).parent() is panel.folder_row("Plans")


def test_a_scene_dropped_on_another_goes_before_it_in_its_folder(win):
    panel = _scenes(win, "A", "B", "C")
    _folder(panel, "F")
    panel.drop_rows(("folder", "F"),
                    [panel.row_for(_view(win, n)) for n in ("A", "B")])
    panel.drop_rows(("before", _view(win, "A")),
                    [panel.row_for(_view(win, "C"))])
    assert _view(win, "C").folder == "F"
    assert _names(win) == ["C", "A", "B"]
    panel.drop_rows(("folder", None), [panel.row_for(_view(win, "B"))])
    assert _view(win, "B").folder is None
    assert _rows(panel) == ["F", "C", "A", "B"]


def test_every_folder_change_is_one_undo_step(win):
    panel = _scenes(win, "A", "B")
    history = win.viewport.history
    _folder(panel, "F")                       # add + rename: two steps
    panel.drop_rows(("folder", "F"), [panel.row_for(_view(win, "B"))])
    assert _rows(panel) == ["F", "B", "A"]
    history.undo()                            # the drop
    panel.refresh()
    assert _rows(panel) == ["F", "A", "B"] and _view(win, "B").folder is None
    history.undo()                            # the rename
    assert SF.folders_of(win.viewport.scene) == ["Folder"]
    history.undo()                            # the folder
    panel.refresh()
    assert SF.folders_of(win.viewport.scene) == []
    assert _rows(panel) == ["A", "B"]
    history.redo()
    history.redo()
    history.redo()
    panel.refresh()
    assert _rows(panel) == ["F", "B", "A"]


def test_a_folder_name_another_has_is_refused(win):
    panel = _scenes(win)
    _folder(panel, "Plans")
    _folder(panel, "Sections")
    assert not panel.rename_folder("Sections", "Plans")
    assert "already called" in win.statusBar().currentMessage()
    assert SF.folders_of(win.viewport.scene) == ["Plans", "Sections"]


def test_deleting_a_folder_keeps_its_scenes_one_level_up(win):
    panel = _scenes(win, "Ground")
    _folder(panel, "Plans")
    _folder(panel, "Floors", parent="Plans")
    panel.drop_rows(("folder", "Floors"),
                    [panel.row_for(_view(win, "Ground"))])
    panel._select_row(panel.folder_row("Floors"))
    panel.delete_row()
    assert SF.folders_of(win.viewport.scene) == ["Plans"]
    assert _view(win, "Ground").folder == "Plans"
    win.viewport.history.undo()
    assert _view(win, "Ground").folder == "Floors"


def test_folders_are_saved_with_the_document(win, tmp_path):
    from core.scene import Scene
    from formats import igz
    panel = _scenes(win, "Ground", "North")
    _folder(panel, "Plans")
    _folder(panel, "Floors", parent="Plans")
    panel.drop_rows(("folder", "Floors"),
                    [panel.row_for(_view(win, "Ground"))])
    path = tmp_path / "folders.igz"
    igz.save_scene(win.viewport.scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert SF.folders_of(back) == ["Plans", "Floors"]
    assert SF.folder_parent(back, "Floors") == "Plans"
    assert [(v.name, v.folder) for v in back.saved_views] == \
        [("Ground", "Floors"), ("North", None)]


def test_updating_a_scene_keeps_its_folder(win):
    panel = _scenes(win, "Ground")
    _folder(panel, "Plans")
    panel.drop_rows(("folder", "Plans"), [panel.row_for(_view(win, "Ground"))])
    panel.select_view(_view(win, "Ground"))
    panel._on_update()
    assert _view(win, "Ground").folder == "Plans"


# ---- 4. Reorder by dragging -------------------------------------------------

def test_a_row_dragged_reorders_the_scenes_in_one_undo_step(win):
    panel = _scenes(win, "A", "B", "C")
    panel.drop_rows(("before", _view(win, "A")),
                    [panel.row_for(_view(win, "C"))])
    assert _names(win) == ["C", "A", "B"]
    history = win.viewport.history
    history.undo()
    panel.refresh()
    assert _names(win) == ["A", "B", "C"]
    assert _rows(panel) == ["A", "B", "C"]
    history.redo()
    panel.refresh()
    assert _rows(panel) == ["C", "A", "B"]


def _sheet_list_scenes(panel):
    """The scene rows of a «Views and sheets» list, top to bottom."""
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    panel.refresh()
    out = []
    it = QTreeWidgetItemIterator(panel.tree)
    while it.value() is not None:
        data = it.value().data(0, Qt.UserRole)
        if data and data[0] == "scene":
            out.append(data[1].name)
        it += 1
    return out


def test_views_and_sheets_lists_the_scenes_in_the_new_order(win):
    from views.outliner import SheetsPanel
    panel = _scenes(win, "A", "B", "C")
    panel.drop_rows(("before", _view(win, "A")),
                    [panel.row_for(_view(win, "C"))])
    assert _sheet_list_scenes(SheetsPanel(win)) == ["C", "A", "B"]


# ---- 5. Undo for everything -------------------------------------------------

def test_add_is_undoable(win):
    panel = _scenes(win)
    view = panel._on_add()
    assert panel.current_view() is view
    win.viewport.history.undo()
    panel.refresh()
    assert _names(win) == [] and panel.scene_rows() == []
    win.viewport.history.redo()
    assert len(_names(win)) == 1


def test_update_is_undoable(win):
    panel = _scenes(win, "A")
    view = _view(win, "A")
    cam = win.viewport.camera
    before = view.distance
    cam.distance = before + 37.0
    panel.select_view(view)
    panel._on_update()
    assert view.distance == pytest.approx(before + 37.0)
    win.viewport.history.undo()
    assert view.distance == pytest.approx(before)
    assert view.name == "A"
    win.viewport.history.redo()
    assert view.distance == pytest.approx(before + 37.0)


def test_rename_in_the_row_is_undoable_and_carries_the_sheets(win):
    from core.composition import Composicion
    panel = _scenes(win, "A", "B")
    scene = win.viewport.scene
    page = Composicion(name="Sheet")
    frame = page.default_frame()
    frame.view_key = "scene:A"
    page.frames.append(frame)
    scene.compositions.append(page)
    panel.row_for(_view(win, "A")).setText(0, "Ground floor")  # inline edit
    assert _names(win) == ["Ground floor", "B"]
    assert frame.view_key == "scene:Ground floor"
    win.viewport.history.undo()
    assert _names(win) == ["A", "B"]
    assert frame.view_key == "scene:A"


def test_rename_edits_the_row_when_the_tab_is_in_sight(win, monkeypatch):
    """As Layers and the Browser: no window over the panel, the name is
    edited where it is. With the tab out of sight, the program's wide
    name prompt (views.prompts), not Qt's narrow one."""
    from PySide6.QtWidgets import QAbstractItemView, QInputDialog
    panel = _scenes(win, "A", "B")
    win.scenes_dock.show()
    win.scenes_dock.raise_()
    _app.processEvents()
    asked = []
    monkeypatch.setattr(QInputDialog, "getText",
                        lambda *a, **k: asked.append(a) or ("X", True))
    panel.select_view(_view(win, "B"))
    win._scene_actions["scene_rename"].trigger()
    assert not asked
    assert panel.tree.state() == QAbstractItemView.EditingState
    assert panel.tree.currentItem() is panel.row_for(_view(win, "B"))
    # One line high, centred on the row, however tall the picture makes it.
    from PySide6.QtWidgets import QLineEdit
    editor = panel.tree.viewport().findChild(QLineEdit)
    row_rect = panel.tree.visualItemRect(panel.tree.currentItem())
    assert editor is not None
    assert editor.height() <= editor.sizeHint().height()
    assert abs(editor.geometry().center().y() - row_rect.center().y()) <= 1
    panel.tree.setFocus()                       # leaves the edit as it was
    _app.processEvents()

    win.scenes_dock.hide()
    _app.processEvents()
    win._scene_actions["scene_rename"].trigger()
    assert asked and _names(win) == ["A", "X"]


def test_the_name_prompt_is_the_programs_wide_one(win, monkeypatch):
    import views.prompts as prompts
    _scenes(win, "A")
    win.scenes_dock.hide()
    _app.processEvents()
    used = []
    monkeypatch.setattr(prompts, "get_text",
                        lambda *a, **k: used.append(k) or ("", False))
    win.tray.scenes.select_view(_view(win, "A"))
    win._scene_actions["scene_rename"].trigger()
    assert used and used[0]["text"] == "A"


def test_a_name_another_scene_has_is_refused_and_nothing_to_undo(win):
    panel = _scenes(win, "A", "B")
    history = win.viewport.history
    steps = len(history.undo_stack)
    panel.row_for(_view(win, "B")).setText(0, "A")
    assert _names(win) == ["A", "B"]
    assert _rows(panel) == ["A", "B"]
    assert len(history.undo_stack) == steps
    assert "already called" in win.statusBar().currentMessage()


def test_rename_from_views_and_sheets_is_undoable_too(win):
    from views.outliner import SheetsPanel
    _scenes(win, "A")
    view = _view(win, "A")
    assert SheetsPanel(win).rename_scene(view, "Section")
    assert view.name == "Section"
    win.viewport.history.undo()
    assert view.name == "A"


def test_delete_is_still_undoable(win):
    panel = _scenes(win, "A", "B")
    panel.select_view(_view(win, "A"))
    panel._on_delete()
    assert _names(win) == ["B"]
    win.viewport.history.undo()
    assert _names(win) == ["A", "B"]


# ---- 6. A mark on the scene shown -------------------------------------------

def _bold(panel):
    return [it.font(0).bold() for it in panel.scene_rows()]


def test_the_scene_shown_carries_the_mark(win):
    panel = _scenes(win, "A", "B")
    panel.activate_view(_view(win, "B"))
    assert panel.shown is _view(win, "B")
    assert _bold(panel) == [False, True]
    panel.activate_view(_view(win, "A"))
    assert _bold(panel) == [True, False]


def test_the_mark_goes_with_its_scene_when_it_is_deleted(win):
    panel = _scenes(win, "A", "B")
    panel.activate_view(_view(win, "A"))
    panel.select_view(_view(win, "A"))
    panel._on_delete()
    assert panel.shown is None
    assert not any(_bold(panel))


def test_a_scene_shown_from_views_and_sheets_is_marked_here(win):
    from views.outliner import SheetsPanel
    panel = _scenes(win, "A", "B")
    view = _view(win, "B")
    SheetsPanel(win)._show_scene(view)
    assert panel.shown is view
    assert panel.row_for(view).font(0).bold()


# ---- The list or the thumbnails ---------------------------------------------

def _wait(timeout_ms=5000, until=None):
    """Until the pictures are drawn, one per tick of the loop: a while,
    then on until the Scenes tab has none left to draw nor an old-picture
    timer running (a slow machine needs more than a fixed pause), and
    ``until()`` holds when given (a loaded machine can leave the queue
    empty for a moment before the next picture is put in it)."""
    import time
    from PySide6.QtTest import QTest
    QTest.qWait(300)
    panel = _app_panel()
    deadline = time.monotonic() + timeout_ms / 1000
    while (panel is not None and panel.isVisible()
           and (panel._thumb_queue or panel._old_timer.isActive()
                or (until is not None and not until()))
           and time.monotonic() < deadline):
        QTest.qWait(20)


def _app_panel():
    """The Scenes tab on screen, if there is one (a hidden tab draws
    nothing, so there is nothing to wait for)."""
    from views.tray import ScenesPanel
    from shiboken6 import isValid
    panels = [w for w in _app.allWidgets()
              if isinstance(w, ScenesPanel) and isValid(w)
              and w.isVisible()]
    return panels[-1] if panels else None


def test_thumbnails_are_the_default_and_the_choice_is_kept(win):
    panel = win.scenes_dock.panel
    assert panel.thumbnails
    assert panel.thumbs_action.isChecked()
    assert panel.tree.iconSize().height() >= 48
    panel.list_action.trigger()
    assert not panel.thumbnails and panel.list_action.isChecked()
    assert panel.tree.iconSize().height() <= 16
    from views.tray import ScenesPanel
    again = ScenesPanel(win)              # the next window remembers it
    assert not again.thumbnails
    again.deleteLater()


def test_each_scene_gets_its_picture_and_a_changed_one_is_drawn_again(
        win, monkeypatch):
    from PySide6.QtGui import QColor, QIcon, QPixmap
    from views.tray import ScenesPanel
    drawn = []

    def fake(self, view):
        drawn.append(view.name)
        pm = QPixmap(96, 64)
        pm.fill(QColor("red"))
        return QIcon(pm)
    monkeypatch.setattr(ScenesPanel, "_render_thumbnail", fake)
    panel = _scenes(win, "A", "B")
    _wait(until=lambda: len(drawn) >= 2)
    assert sorted(drawn) == ["A", "B"]
    row = panel.row_for(_view(win, "A"))
    assert row.icon(0).pixmap(96, 64).toImage().pixelColor(48, 32) == \
        QColor("red")
    drawn.clear()
    panel._shape = None
    panel.refresh()
    _wait()
    assert drawn == []                    # nothing changed: none drawn again
    win.viewport.camera.distance += 10.0
    panel.select_view(_view(win, "B"))
    panel._on_update()
    _wait(until=lambda: bool(drawn))
    assert drawn == ["B"]


def _painter(monkeypatch, drawn, colour):
    """Pictures of one colour (``colour[0]``), each one noted in ``drawn``."""
    from PySide6.QtGui import QColor, QIcon, QPixmap
    from views.tray import ScenesPanel

    def fake(self, view):
        drawn.append(view.name)
        pm = QPixmap(96, 64)
        pm.fill(QColor(colour[0]))
        return QIcon(pm)
    monkeypatch.setattr(ScenesPanel, "_render_thumbnail", fake)


def _colour(panel, view):
    return panel.row_for(view).icon(0).pixmap(96, 64).toImage().pixelColor(
        48, 32).name()


def _edit_model(win):
    """An edit of the model (not of the scenes), as a tool's would be."""
    win.viewport.scene.version += 1
    win.scenes_dock.panel.refresh()


def test_a_model_edited_redraws_the_pictures_once_it_is_still(
        win, monkeypatch):
    """Pictures went old when the model changed: now each is drawn again
    a moment after the last edit, the old one shown until then."""
    drawn, colour = [], ["#ff0000"]
    _painter(monkeypatch, drawn, colour)
    panel = _scenes(win, "A", "B")
    panel._old_timer.setInterval(150)
    _wait()
    assert sorted(drawn) == ["A", "B"]
    drawn.clear()
    colour[0] = "#0000ff"
    _edit_model(win)
    _app.processEvents()
    assert drawn == []                         # not at each stroke
    assert _colour(panel, _view(win, "A")) == "#ff0000"
    _edit_model(win)                           # another: it waits again
    _wait()
    _wait()
    assert sorted(drawn) == ["A", "B"]         # once each, not twice
    assert _colour(panel, _view(win, "A")) == "#0000ff"


def test_a_hidden_tab_redraws_its_pictures_when_it_shows(win, monkeypatch):
    drawn, colour = [], ["#ff0000"]
    _painter(monkeypatch, drawn, colour)
    panel = _scenes(win, "A")
    panel._old_timer.setInterval(50)
    _wait()
    drawn.clear()
    win.scenes_dock.hide()                     # Scenes out of sight
    _app.processEvents()
    assert not panel.isVisible()
    _edit_model(win)
    _wait()
    assert drawn == []
    win.scenes_dock.show()
    _app.processEvents()
    _wait()
    assert drawn == ["A"]


def test_edits_of_the_scenes_redraw_only_the_scene_they_change(
        win, monkeypatch):
    """Adding, renaming, filing in folders: the model is the same, the
    other pictures stay."""
    drawn, colour = [], ["#ff0000"]
    _painter(monkeypatch, drawn, colour)
    panel = _scenes(win, "A", "B")
    panel._old_timer.setInterval(50)
    _wait()
    drawn.clear()
    panel.rename(_view(win, "A"), "C")
    _folder(panel, "F")
    panel.drop_rows(("folder", "F"), [panel.row_for(_view(win, "B"))])
    panel.tree.clearSelection()
    panel._on_add()
    _wait()
    _wait()
    assert "B" not in drawn
    assert drawn.count("C") == 1 and len(drawn) == 2   # renamed + new


def test_in_the_list_view_no_picture_is_drawn(win, monkeypatch):
    from views.tray import ScenesPanel
    drawn = []
    monkeypatch.setattr(ScenesPanel, "_render_thumbnail",
                        lambda self, view: drawn.append(view.name))
    panel = win.scenes_dock.panel
    panel.set_thumbnails(False)
    _scenes(win, "A", "B")
    _wait()
    assert drawn == []


def test_a_refresh_while_a_picture_is_drawn_does_not_draw_it_twice(
        win, monkeypatch):
    """Rendering runs the event loop: a refresh in the middle queued the
    picture in hand again (seen on the test house: the first one twice)."""
    from PySide6.QtGui import QColor, QIcon, QPixmap
    from views.tray import ScenesPanel
    drawn = []

    def fake(self, view):
        drawn.append(view.name)
        self._shape = None
        self.refresh()                       # as an event in mid-render
        pm = QPixmap(96, 64)
        pm.fill(QColor("red"))
        return QIcon(pm)
    monkeypatch.setattr(ScenesPanel, "_render_thumbnail", fake)
    _scenes(win, "A", "B")
    _wait()
    assert sorted(drawn) == ["A", "B"]


# ---- With the scene tabs under the viewport (main 0.6.1) -------------------

def test_one_command_of_each_kind_for_scenes():
    """Main's AddSceneCommand (with a place and the folder now) and its
    RenameSceneCommand: no second class of the same name beside them."""
    import core.history as H
    import core.saved_views as S
    src = open(H.__file__, encoding="utf8").read()
    assert src.count("class AddSceneCommand(") == 1
    assert "class RenameSceneCommand(" not in src
    assert hasattr(S, "RenameSceneCommand") and hasattr(S, "MoveSceneCommand")


def test_a_tab_dragged_among_folders_lands_with_the_scene_after_it(win):
    """A scene tab dragged to another place: it goes right before the
    scene that follows it there, into that scene's folder — what dropping
    it on that row in the panel does — in one undo step."""
    panel = _scenes(win, "A", "B", "C", "D")
    _folder(panel, "F")
    panel.drop_rows(("folder", "F"), [panel.row_for(_view(win, "C")),
                                      panel.row_for(_view(win, "D"))])
    assert _names(win) == ["C", "D", "A", "B"]   # a folder before scenes
    steps = len(win.viewport.history.undo_stack)
    panel.move_view(_view(win, "A"), 1)        # between C and D
    assert _names(win) == ["C", "A", "D", "B"]
    assert SF.folder_of(win.viewport.scene, _view(win, "A")) == "F"
    assert len(win.viewport.history.undo_stack) == steps + 1
    panel.move_view(_view(win, "B"), 3)        # to the end: after D, in F
    assert _names(win) == ["C", "A", "D", "B"]
    assert SF.folder_of(win.viewport.scene, _view(win, "B")) == "F"
    win.viewport.history.undo()
    win.viewport.history.undo()
    assert _names(win) == ["C", "D", "A", "B"]
    assert SF.folder_of(win.viewport.scene, _view(win, "A")) is None


def test_alt_arrows_move_a_scene_within_its_folder(win):
    panel = _scenes(win, "A", "B", "C")
    _folder(panel, "F")
    panel.drop_rows(("folder", "F"), [panel.row_for(_view(win, "B")),
                                      panel.row_for(_view(win, "C"))])
    panel.select_view(_view(win, "C"))
    moves = {a.shortcut().toString(): a for a in panel.tree.actions()}
    assert _names(win) == ["B", "C", "A"]      # the folder first
    moves["Alt+Up"].trigger()
    assert _names(win) == ["C", "B", "A"]
    steps = len(win.viewport.history.undo_stack)
    moves["Alt+Up"].trigger()                  # first of its folder: stays
    assert _names(win) == ["C", "B", "A"]
    assert len(win.viewport.history.undo_stack) == steps
    assert SF.folder_of(win.viewport.scene, _view(win, "C")) == "F"


def test_plus_of_the_tabs_files_the_scene_with_the_one_shown(win):
    """In a folder the new scene is not the last of the list: its own tab
    is the one marked."""
    panel = _scenes(win, "A", "B")
    _folder(panel, "F")
    panel.drop_rows(("folder", "F"), [panel.row_for(_view(win, "A"))])
    panel.activate_view(_view(win, "A"))
    panel.tree.clearSelection()
    win._add_scene_from_tabs()
    new = win.viewport.scene.saved_views[1]
    assert SF.folder_of(win.viewport.scene, new) == "F"
    tabs = win._scene_tabs.tabs
    assert tabs.tabText(tabs.currentIndex()) == new.name


def test_update_from_a_scene_tab_is_one_undo_step(win):
    from core.i18n import tr
    panel = _scenes(win, "A")
    view = _view(win, "A")
    before = view.distance
    win.viewport.camera.distance = before + 25.0
    menu = win._build_scene_tab_menu(0)
    next(a for a in menu.actions() if a.text() == tr("Update")).trigger()
    assert view.distance == pytest.approx(before + 25.0)
    win.viewport.history.undo()
    assert view.distance == pytest.approx(before)


def test_a_scene_shown_from_a_tab_is_marked_in_the_panel(win):
    panel = _scenes(win, "A", "B")
    win._on_scene_tab(1)
    assert panel.shown is _view(win, "B")
    font = panel.row_for(_view(win, "B")).font(0)
    assert font.bold()


# ---- The panel's icons follow the theme; a picture is asked for again -------

def test_the_bar_icons_are_named_so_a_theme_change_draws_them_again(win):
    """Drawn in the theme's ink when made, and left in it: black on the
    dark theme after a switch."""
    from PySide6.QtGui import QColor, QIcon, QPixmap
    from views import theme
    panel = win.scenes_dock.panel
    named = {panel.add_btn: "scene_add", panel.add_folder_btn: "folder_add",
             panel.update_btn: "refresh",
             panel.list_action: "scenes_list",
             panel.thumbs_action: "scenes_thumbs"}
    for obj, key in named.items():
        assert obj.property("icon_key") == key
    panel.set_thumbnails(True)
    assert panel.view_btn.property("icon_key") == "scenes_thumbs"
    panel.set_thumbnails(False)
    assert panel.view_btn.property("icon_key") == "scenes_list"
    # The redraw reaches them: a blank put in their place is replaced.
    blank = QPixmap(16, 16)
    blank.fill(QColor(0, 0, 0, 0))
    for obj in list(named) + [panel.view_btn]:
        obj.setIcon(QIcon(blank))
    theme._redraw_icons(_app)
    for obj in list(named) + [panel.view_btn]:
        img = obj.icon().pixmap(16, 16).toImage()
        assert any(img.pixelColor(x, y).alpha() > 0
                   for x in range(img.width()) for y in range(img.height()))


def test_a_picture_that_could_not_be_drawn_is_asked_for_again(
        win, monkeypatch):
    """At start-up the view may not be ready: the first try gave nothing
    and the scene kept the camera until it changed."""
    from PySide6.QtGui import QColor, QIcon, QPixmap
    from PySide6.QtTest import QTest
    from views.tray import ScenesPanel
    tries = []

    def fake(self, view):
        tries.append(view.name)
        if len(tries) < 2:
            return None                      # not ready the first time
        pm = QPixmap(96, 64)
        pm.fill(QColor("red"))
        return QIcon(pm)
    monkeypatch.setattr(ScenesPanel, "_render_thumbnail", fake)
    monkeypatch.setattr(ScenesPanel, "RETRY_AFTER_MS", 30)
    panel = win.scenes_dock.panel
    panel._retry_timer.setInterval(30)
    panel = _scenes(win, "A")
    _wait()
    QTest.qWait(200)
    _wait()
    assert tries == ["A", "A"]
    row = panel.row_for(_view(win, "A"))
    assert row.icon(0).pixmap(96, 64).toImage().pixelColor(48, 32) == \
        QColor("red")


def test_a_scene_with_no_picture_to_be_had_is_not_asked_for_ever(
        win, monkeypatch):
    from PySide6.QtTest import QTest
    from views.tray import ScenesPanel
    tries = []
    monkeypatch.setattr(ScenesPanel, "_render_thumbnail",
                        lambda self, view: tries.append(view.name))
    win.scenes_dock.panel._retry_timer.setInterval(20)
    _scenes(win, "A")
    _wait()
    QTest.qWait(400)
    assert len(tries) == ScenesPanel.RETRIES + 1
