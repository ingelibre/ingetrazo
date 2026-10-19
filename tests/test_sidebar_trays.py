"""The right-side trays (Properties, BIM, Terrain) always have a way back:
their Window-menu entries work, and folding the sidebar brings back every
tray that was open — not just the tab in front (Marco, 0.5.1 Flatpak: «no
veo las pestañas de terreno y BIM», the menu entries greyed out)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
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




def test_the_window_menu_can_bring_back_every_tray(settings_file):
    from views.main_window import MainWindow
    win = MainWindow()
    for dock in win._sidebar_docks():
        assert dock.toggleViewAction().isEnabled(), dock.objectName()
    win.bim_tray.hide()
    assert not win.bim_tray.toggleViewAction().isChecked()
    win.bim_tray.toggleViewAction().trigger()
    assert not win.bim_tray.isHidden()


def test_unfolding_the_sidebar_brings_back_the_tabs_behind(settings_file,
                                                         monkeypatch):
    from PySide6.QtWidgets import QDockWidget
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    for _ in range(5):
        _app.processEvents()
    # On a real screen a tray tabbed behind another is not visible; the
    # offscreen platform shows them all, so play the real screen here.
    front = win.tray
    real = QDockWidget.isVisible
    monkeypatch.setattr(QDockWidget, "isVisible",
                        lambda d: real(d) and d is front)
    for dock in (win.bim_tray, win.georef_tray):    # open them all
        dock.toggleViewAction().trigger()
    right = [d for d in win._sidebar_docks() if not d.isHidden()
             and win.dockWidgetArea(d) != Qt.LeftDockWidgetArea]
    win._set_sidebar_visible(False)
    win._set_sidebar_visible(True)
    for dock in right:
        assert not dock.isHidden(), dock.objectName()


def _shown(win):
    """The Window-menu checks follow the trays once the window is up."""
    win.show()
    for _ in range(5):
        _app.processEvents()
    return win


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_a_first_run_opens_the_everyday_trays_and_keeps_the_rest_ready(
        settings_file):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    assert not win.tray.isHidden()                    # Properties
    assert not win.project_browser.isHidden()          # the model's tree
    assert win.project_browser in win.tabifiedDockWidgets(win.tray)
    assert _tab_order(win)[:2] == ["Properties", "Browser"]
    assert win.bim_tray.isHidden() and win.georef_tray.isHidden()
    assert win.bim_tray.toggleViewAction().isEnabled()  # one click away
    _close(win)


def _tab_order(win):
    """The tabs of the group holding Properties, left to right."""
    from PySide6.QtCore import QPoint
    for tb in win._dock_tab_bars():
        texts = [tb.tabText(i) for i in range(tb.count())]
        if ("Properties" in texts and tb.isVisible()
                and win.rect().contains(tb.mapTo(win, QPoint(0, 0)))):
            return texts
    return []


def test_restore_default_panels_puts_everything_back(settings_file):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    win.georef_tray.toggleViewAction().trigger()     # opened
    win.move_dock(win.bim_tray, Qt.LeftDockWidgetArea)
    win.move_dock(win.project_browser, Qt.LeftDockWidgetArea)
    _app.processEvents()
    win.restore_default_trays()
    for _ in range(5):
        _app.processEvents()
    assert all(win.dockWidgetArea(d) == Qt.RightDockWidgetArea
               for d in win._sidebar_docks())
    assert win.georef_tray.isHidden() and win.bim_tray.isHidden()
    assert not win.tray.isHidden() and not win.project_browser.isHidden()
    assert _tab_order(win)[:2] == ["Properties", "Browser"]
    # The test's own INI: the QSettings name imported above is not the
    # patched one, and the shared store keeps what earlier tests wrote.
    assert not QSettings(str(settings_file), QSettings.IniFormat).contains(
        "ui/hidden_trays")
    _close(win)


def test_every_tray_opens_at_start_up_unless_the_menu_closed_it(settings_file):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    for dock in (win.bim_tray, win.georef_tray):    # opened from the menu
        dock.toggleViewAction().trigger()
    _close(win)
    win = _shown(MainWindow())
    win.bim_tray.hide()                 # lost by a fold, not by the menu
    win.georef_tray.toggleViewAction().trigger()    # closed from the menu
    assert win.georef_tray.isHidden()
    _close(win)                         # the layout is saved on close

    win = _shown(MainWindow())
    assert not win.tray.isHidden()
    assert not win.bim_tray.isHidden()
    assert win.georef_tray.isHidden()
    win.georef_tray.toggleViewAction().trigger()    # back from the menu
    _close(win)

    win = _shown(MainWindow())
    assert not any(d.isHidden() for d in (win.tray, win.bim_tray,
                                          win.georef_tray,
                                          win.project_browser))
    _close(win)


def test_a_folded_sidebar_opens_unfolded(settings_file):
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    open_ = {d.objectName() for d in win._sidebar_docks()
             if not d.isHidden()}
    win._set_sidebar_visible(False)
    _close(win)
    win = _shown(MainWindow())
    assert open_ and all(not d.isHidden() for d in win._sidebar_docks()
                         if d.objectName() in open_)
    _close(win)


def test_ai_and_render_open_and_an_extension_may_ask_to_start_hidden(
        settings_file):
    from PySide6.QtWidgets import QLabel
    from views.extension_api import ExtensionApp
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    for name in ("extension_ai", "extension_render_blender"):
        dock = win.extension_panels().get(name)
        if dock is not None:                          # bundled, if loaded
            assert not dock.isHidden(), name
    app = ExtensionApp(win, "quiet")
    quiet = app.add_panel("Quiet", QLabel("q"), start_hidden=True)
    loud = ExtensionApp(win, "loud").add_panel("Loud", QLabel("l"))
    assert quiet.isHidden() and not loud.isHidden()
    win.set_tray_shown(quiet, True)                   # the user opens it…
    _close(win)
    win = _shown(MainWindow())                        # …and it stays open
    quiet = ExtensionApp(win, "quiet").add_panel("Quiet", QLabel("q"),
                                                 start_hidden=True)
    assert not quiet.isHidden()
    _close(win)


def test_a_new_extension_asking_to_start_hidden_does_so_on_a_used_profile(
        settings_file):
    from PySide6.QtWidgets import QLabel
    from views.extension_api import ExtensionApp
    from views.main_window import MainWindow
    win = _shown(MainWindow())
    win.georef_tray.toggleViewAction().trigger()      # a choice is saved
    _close(win)
    win = _shown(MainWindow())
    late = ExtensionApp(win, "late").add_panel("Late", QLabel("l"),
                                               start_hidden=True)
    assert late.isHidden()                            # installed later: hidden
    assert not win.georef_tray.isHidden()             # the choice still rules
    _close(win)


def test_restore_default_panels_gives_the_tray_its_first_run_width(
        settings_file):
    """The width a first run has — the factory layout's — is the one
    Restore default panels puts back after the tray was dragged wider."""
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 900)
    _shown(win)
    assert win.tray.width() == MainWindow.FACTORY_TRAY_WIDTH
    win.resizeDocks([win.tray], [700], Qt.Horizontal)
    for _ in range(5):
        _app.processEvents()
    assert win.tray.width() > 600
    win.restore_default_trays()
    for _ in range(5):
        _app.processEvents()
    assert win.tray.width() == MainWindow.FACTORY_TRAY_WIDTH
    _close(win)


def test_a_tray_left_wide_last_time_still_restores_to_the_factory_width(
        settings_file):
    """The report: the layout is saved on closing, so a tray left 600 px
    wide opens 600 px wide; restoring to «the width it opened with» then
    changed nothing. Restore default panels gives the factory width."""
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 900)
    _shown(win)
    win.resizeDocks([win.tray], [600], Qt.Horizontal)
    for _ in range(5):
        _app.processEvents()
    _close(win)                                      # saves the layout
    win = MainWindow()
    win.resize(1400, 900)
    _shown(win)
    assert abs(win.tray.width() - 600) <= 2          # opened wide
    win.restore_default_trays()
    for _ in range(5):
        _app.processEvents()
    assert win.tray.width() == MainWindow.FACTORY_TRAY_WIDTH
    _close(win)


def test_restore_default_panels_keeps_the_window_s_height(settings_file):
    """Every tray was docked one under the other before being tabbed: their
    heights added up past the window, which grew to hold them — maximized,
    its foot went off the screen and the sidebar's handle, centred on the
    view, slid down with it (2026-10-16: «el botón se desplaza hacia abajo
    al restablecer paneles»)."""
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 800)
    _shown(win)
    height, handle = win.height(), win._sidebar_handle.y()
    win.restore_default_trays()
    for _ in range(5):
        _app.processEvents()
    assert win.height() == height
    assert abs(win._sidebar_handle.y() - handle) <= 2
    _close(win)


def _over_the_view(win, handle):
    """``handle`` stacked above the viewport (later among the window's
    children): the viewport draws with OpenGL and hides what lies under."""
    kids = [c for c in win.children() if c.isWidgetType()]
    return kids.index(handle) > kids.index(win.viewport)


def test_reordering_the_panel_tabs_leaves_the_sidebar_handle_on_top(
        settings_file):
    """Dragging a tab along the bar restacks the window's children and the
    viewport came out above the handle: half of it hidden under the view
    (2026-10-16: «al mover los paneles de orden … queda medio oculto»)."""
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 800)
    _shown(win)
    assert _over_the_view(win, win._sidebar_handle)
    bar = next(tb for tb in win._dock_tab_bars()
               if tb.isVisible() and tb.count() > 1 and tb.y() >= 0)
    bar.moveTab(0, 1)
    for _ in range(5):
        _app.processEvents()
    assert _over_the_view(win, win._sidebar_handle)
    assert _over_the_view(win, win._left_handle)
    _close(win)


def test_folding_takes_along_a_panel_an_extension_docked_by_itself(
        settings_file):
    """igz_tb_scenes docks its «Escenas» with addDockWidget, not
    add_panel: folding the sidebar left it alone on the right (Marco,
    18-10: «había otra barra… trate de mostrar y ya no funciona»)."""
    from PySide6.QtWidgets import QDockWidget, QLabel
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    _app.processEvents()
    own = QDockWidget("Scenes", win)
    own.setObjectName("igz_tb_scenes_dock")
    own.setWidget(QLabel("scenes"))
    win.addDockWidget(Qt.RightDockWidgetArea, own)
    left = QDockWidget("Left one", win)
    left.setWidget(QLabel("left"))
    win.addDockWidget(Qt.LeftDockWidgetArea, left)
    _app.processEvents()
    win._act_sidebar.setChecked(False)
    assert own.isHidden()                 # nothing left standing alone
    win._act_sidebar.setChecked(True)
    assert not own.isHidden() and not win.tray.isHidden()
    win._set_left_sidebar_visible(False)
    assert left.isHidden()
    win._set_left_sidebar_visible(True)
    assert not left.isHidden()
    # one the user closed stays closed
    own.hide()
    win._act_sidebar.setChecked(False)
    win._act_sidebar.setChecked(True)
    assert own.isHidden()
    win._saved_version = win.viewport.scene.version
    win.close()
