# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""One toolbar icon size for the model window AND the sheet composer
(Marco, 2026-09-14: «no sé si habrás considerado también los iconos de
composiciones»)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QToolBar

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """A throwaway INI for every QSettings() the windows open — the name
    imported into views.main_window included, or the MainWindow reads
    (and, on close, WRITES) the layout of whatever test ran before."""
    path = tmp_path / "prefs.ini"
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    import PySide6.QtCore as qc
    import views.main_window as mw
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory)
    return path


def test_the_size_reaches_the_composer_toolbars_live_and_on_build(settings_file, monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    try:
        win.set_toolbar_icon_size(40)
        comp = ComposerWindow(win)
        win._composer = comp
        try:
            bars = win.findChildren(QToolBar) + comp.findChildren(QToolBar)
            assert bars and all(tb.iconSize().width() == 40 for tb in bars)
            win.set_toolbar_icon_size(20)                  # live, both windows
            assert all(tb.iconSize().width() == 20 for tb in bars)
        finally:
            comp.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_main_toolbar_starts_with_save(settings_file, monkeypatch):
    """Marco, 2026-09-14: the Save icon on the model's Main bar too, before
    the Select arrow; it triggers the same save as the menu."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        acts = [a for a in win.toolbars["main"].actions() if not a.isSeparator()]
        assert acts[0] is win._act_save_tb and acts[0].text() == "Save"
        assert acts[1] is win._tool_actions["select"]
        called = []
        monkeypatch.setattr(win, "_on_save", lambda: called.append(True))
        win._act_save_tb.trigger()
        assert called == [True]
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_simplify_mesh_is_only_in_the_edit_menu(settings_file):
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        action = win._act_simplify_mesh
        assert action not in win.toolbars["main"].actions()
        edit_menu = next(
            item.menu() for item in win.menuBar().actions()
            if item.text() == "Edit")
        assert action in edit_menu.actions()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_stl_simplification_defaults_to_principal_planes(
        settings_file, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QDialog, QComboBox
    from views.main_window import MainWindow
    import views.main_window as mw

    old_settings = mw.QSettings()
    old_settings.setValue("import/stl_simplify", "true")
    old_settings.sync()
    monkeypatch.setattr(
        mw.file_dialogs, "getOpenFileName",
        lambda *args: (str(tmp_path / "sample.stl"), ""))
    selected = {}

    def reject_dialog(dialog):
        combo = dialog.findChildren(QComboBox)[1]
        selected["mode"] = combo.currentData()
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", reject_dialog)
    win = MainWindow()
    try:
        win._on_import_stl()
        assert selected["mode"] == "principal"
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_stl_parse_runs_on_worker_and_reports_progress_on_ui_thread(
        settings_file, monkeypatch, tmp_path):
    import struct
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication
    from formats import stl as stl_format
    from views.main_window import MainWindow

    path = tmp_path / "triangle.stl"
    with path.open("wb") as target:
        target.write(b"binary STL".ljust(80, b"\0"))
        target.write(struct.pack("<I", 1))
        target.write(struct.pack(
            "<12fH", 0, 0, 1,
            0, 0, 0, 1, 0, 0, 0, 1, 0, 0))

    parsing_threads = []
    progress_threads = []
    parse = stl_format.parse_stl

    def track_parse(*args, **kwargs):
        parsing_threads.append(
            QThread.currentThread() != QApplication.instance().thread())
        return parse(*args, **kwargs)

    monkeypatch.setattr(stl_format, "parse_stl", track_parse)
    win = MainWindow()
    try:
        mesh, error = win._parse_stl_threaded(
            path, 1.0, "none",
            lambda *_: progress_threads.append(
                QThread.currentThread() == QApplication.instance().thread()))
        assert error is None
        assert len(mesh.faces) == 1
        assert parsing_threads == [True]
        assert progress_threads and all(progress_threads)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_fresh_install_gets_marcos_layout_and_large_icons(settings_file, monkeypatch):
    """No saved state → the factory blob (resources/ui/default_layout.state)
    and 32 px icons: Draw and Annotate stand at the left, the rest along
    the top, as Marco arranged them (2026-09-14: «así como está… por
    defecto para cualquier persona que instale el programa»)."""
    from PySide6.QtCore import Qt
    from views import icons
    from views.main_window import MainWindow
    assert icons.toolbar_icon_px() == 24                                # normal, since 14-09
    win = MainWindow()
    try:
        assert win.toolBarArea(win.toolbars["draw"]) == Qt.LeftToolBarArea
        assert win.toolBarArea(win.toolbars["annotate"]) == Qt.LeftToolBarArea
        for name in ("main", "modify", "view", "sections", "views"):
            assert win.toolBarArea(win.toolbars[name]) == Qt.TopToolBarArea, name
        assert all(tb.iconSize().width() == 24 for tb in win.toolbars.values())
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_clean_screen_shows_an_exit_button_at_the_top_right(settings_file):
    """Ctrl+0 hides everything; a floating «Exit clean screen» button at
    the viewport's top-right brings the workspace back for whoever does
    not know the key (Marco, 2026-09-14)."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.show()
        win._act_clean_screen.setChecked(True)
        btn = win._clean_exit_btn
        assert btn.isVisible() and not win.menuBar().isVisible()
        assert btn.x() + btn.width() <= win.viewport.width() and btn.y() == 12
        btn.click()
        assert not win._act_clean_screen.isChecked()
        assert not btn.isVisible() and win.menuBar().isVisible()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_sidebar_handle_sits_on_the_resize_line_and_folds_the_trays(settings_file):
    """LibreOffice's handle (Marco, 2026-09-14): a slim button on the line
    between the viewport and the trays, half-way down; click (or Window ▸
    Sidebar, Ctrl+F5) folds the three trays away, the handle rests at the
    window's edge, click brings back the trays that were open."""
    from PySide6.QtWidgets import QApplication
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.resize(1200, 800)
        win.show()
        QApplication.processEvents()
        btn = win._sidebar_handle
        from PySide6.QtCore import Qt
        docks = [d for d in win._sidebar_docks()        # the right side's
                 if win.dockWidgetArea(d) != Qt.LeftDockWidgetArea]
        assert btn.isVisible() and win.tray.isVisible()
        edge = win.viewport.mapTo(win, win.viewport.rect().topRight()).x()
        assert abs((btn.x() + btn.width() // 2) - edge) <= 2       # on the line
        assert abs(btn.y() + btn.height() // 2
                   - (win.viewport.mapTo(win, win.viewport.rect().topLeft()).y()
                      + win.viewport.height() // 2)) <= 2           # half-way down
        assert edge < win.width() - 50                              # trays take room
        btn.click()                                                 # fold
        QApplication.processEvents()
        assert not win._act_sidebar.isChecked()
        assert not any(d.isVisible() for d in docks)
        QApplication.processEvents()
        assert btn.isVisible() and btn.x() + btn.width() >= win.width() - 2   # at the edge
        win._act_sidebar.setChecked(True)                           # unfold (Ctrl+F5)
        QApplication.processEvents()
        assert win.tray.isVisible()
        # Switching the tabbed trays (Terrain ↔ BIM) must not bury the handle.
        for dock in (win.bim_tray, win.georef_tray, win.tray):
            dock.show()
            dock.raise_()
            QApplication.processEvents()
            QApplication.processEvents()
            top = win.childAt(btn.geometry().center())
            assert top is btn or btn.isAncestorOf(top), dock.objectName()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def _composer(monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    win._composer = comp
    return win, comp


def test_the_composer_has_the_same_handle_and_clean_screen(settings_file, monkeypatch):
    """Marco, 2026-09-14: «en composiciones implementa ese mismo botón…
    también Ctrl+0». The handle sits on the splitter line, folds the
    right panel away; Ctrl+0 leaves only the page plus the exit button."""
    win, comp = _composer(monkeypatch)
    try:
        comp.resize(1200, 800)
        comp.show()
        QApplication.processEvents()
        btn = comp._sidebar_handle
        panel = comp._side_panel              # the right side panel
        area = comp._canvas_area               # the page, left of it
        assert btn.isVisible() and panel.isVisible()
        edge = area.mapTo(comp, area.rect().topRight()).x()
        assert btn.x() >= edge                 # never over the canvas' scroll bar
        assert btn.x() <= edge + comp._splitter.handleWidth()
        btn.click()
        QApplication.processEvents()
        assert not panel.isVisible() and not comp._act_sidebar.isChecked()
        QApplication.processEvents()
        assert btn.x() + btn.width() >= comp.width() - 2
        comp._act_sidebar.setChecked(True)
        QApplication.processEvents()
        assert panel.isVisible()
        # Ctrl+0
        comp._act_clean_screen.setChecked(True)
        QApplication.processEvents()
        assert not any(tb.isVisible() for tb in comp.findChildren(QToolBar))
        assert not panel.isVisible() and not btn.isVisible()
        exit_btn = comp._clean_exit_btn
        assert exit_btn.isVisible()
        assert exit_btn.x() + exit_btn.width() <= comp._view.width()
        exit_btn.click()
        QApplication.processEvents()
        assert comp._sheet_tb.isVisible() and panel.isVisible() and btn.isVisible()
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_composer_toolbars_are_movable_and_their_arrangement_is_remembered(settings_file, monkeypatch):
    """The factory look is the code's (tools left, sheet top); what the
    user drags is saved on close and restored next time."""
    from PySide6.QtCore import Qt
    win, comp = _composer(monkeypatch)
    try:
        comp.show()
        QApplication.processEvents()
        tools = comp.findChild(QToolBar, "composer_tools")
        assert tools.isMovable() and comp._sheet_tb.isMovable()
        assert comp.toolBarArea(tools) == Qt.LeftToolBarArea
        assert comp.toolBarArea(comp._sheet_tb) == Qt.TopToolBarArea
        # The drawing tools on their own TOP bar: 23 in one column did not
        # fit a 768 px laptop screen (Marco, 2026-09-14).
        draw = comp.findChild(QToolBar, "composer_draw")
        assert comp.toolBarArea(draw) == Qt.TopToolBarArea
        # Factory order along the top: Sheet, Draw, Arrange (Marco, 14-09).
        top = sorted((tb for tb in comp.findChildren(QToolBar)
                      if comp.toolBarArea(tb) == Qt.TopToolBarArea and tb.isVisible()),
                     key=lambda tb: tb.x())
        assert [tb.objectName() for tb in top] == [
            "sheet_toolbar", "composer_draw", "arrange_toolbar"]
        # 11 on the draw bar: the radius and the baseline dimensions;
        # 16 on the tools bar: Zoom and Zoom Window joined it (20-09)
        assert len(tools.actions()) == 16 and len(draw.actions()) == 11
        assert comp._tool_actions["cota"] in draw.actions()
        assert comp._tool_actions["vista"] in tools.actions()
        comp._tool_actions["cota"].trigger()          # one exclusive group
        assert comp.tool_mode == "cota" and not comp._tool_actions["select"].isChecked()
        comp.addToolBar(Qt.RightToolBarArea, tools)     # the user drags it
        comp.close()
        QApplication.processEvents()
        comp2 = type(comp)(win)
        try:
            comp2.show()
            QApplication.processEvents()
            t2 = comp2.findChild(QToolBar, "composer_tools")
            assert comp2.toolBarArea(t2) == Qt.RightToolBarArea
        finally:
            comp2.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_default_is_normal_on_any_screen_and_a_choice_wins(settings_file):
    """Large (32 px) was the default for the 0.3.20 (fine on a 27" monitor,
    clumsy on the laptop — Marco, 2026-09-14); normal since, on every
    screen. A saved choice is never second-guessed."""
    from views import icons
    assert icons.toolbar_icon_px() == 24
    icons.save_toolbar_icon_px(40)
    assert icons.toolbar_icon_px() == 40



def test_the_overflow_button_wears_the_program_chevron(settings_file, monkeypatch):
    """A toolbar that does not fit grows Qt's extension button; ours shows
    a double chevron with a tooltip rather than the style's grey stub
    (Marco, 2026-09-14, on a small window)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QToolButton
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.resize(700, 420)
        win.show()
        QApplication.processEvents()
        draw = win.toolbars["draw"]
        ext = draw.findChild(QToolButton, "qt_toolbar_ext_button")
        assert not ext.icon().isNull()
        assert ext.toolTip()
        vertical = draw.orientation() == Qt.Vertical
        icon_v = ext.icon().cacheKey()
        win.addToolBar(Qt.TopToolBarArea if vertical else Qt.LeftToolBarArea, draw)
        QApplication.processEvents()
        assert ext.icon().cacheKey() != icon_v            # re-drawn for the new orientation
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_walkthrough_toolbar_stands_left_under_annotate(settings_file, monkeypatch):
    """Fresh install: the factory blob puts Walkthrough at the left, right
    under Annotate (below 3D Text — Marco, 2026-09-19). A profile whose
    saved layout predates the toolbar gets the same placement once."""
    from PySide6.QtCore import Qt
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.show()
        tb, above = win.toolbars["walkthrough"], win.toolbars["annotate"]
        assert win.toolBarArea(tb) == Qt.LeftToolBarArea
        assert win.toolBarArea(above) == Qt.LeftToolBarArea
        assert tb.geometry().top() >= above.geometry().bottom() - 1
        # A layout saved before the toolbar existed leaves it where Qt
        # created it — the top. Stand in for that with a state that has
        # it at the top.
        win.removeToolBar(tb)
        win.addToolBar(Qt.TopToolBarArea, tb)
        tb.show()
        top_state = bytes(win.saveState())
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
    from PySide6.QtCore import QSettings
    st = QSettings()
    st.remove("ui/placed/walkthrough")
    st.setValue("ui/window_state", top_state)
    win = MainWindow()
    try:
        assert win.toolBarArea(win.toolbars["walkthrough"]) == Qt.LeftToolBarArea
        assert QSettings().value("ui/placed/walkthrough") is not None
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
    # …and once placed, the user's own arrangement is respected.
    st.setValue("ui/window_state", top_state)
    win = MainWindow()
    try:
        assert win.toolBarArea(win.toolbars["walkthrough"]) == Qt.TopToolBarArea
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
