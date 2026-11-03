# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The side trays' tabs show only an icon, so many more fit on the bar
before it scrolls: the name is the tab's tooltip and heads the panel.

- every tray — built-in or an extension's — has an icon of its own, drawn
  in the tools' ink and redrawn with the theme;
- a tab takes the icon's room, not the name's, yet keeps the name as its
  text (Qt writes it there, and the tabs are found by it);
- the panel's header shows the name and follows a rename;
- ``add_panel(icon=…)`` takes a drawn icon's key or a QIcon; without one
  the tab shows the title's initial.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QLabel

_app = QApplication.instance() or QApplication([])

PANEL_KEYS = ("panel_properties", "panel_bim", "panel_terrain",
              "panel_browser", "panel_ai", "panel_render",
              "panel_solid_inspector", "panel_levels", "layers_panel")


@pytest.fixture
def win(tmp_path, monkeypatch):
    # A settings store and a plugin folder of this test's own (as in
    # test_extension_api_v2.py), every tray opened so they share a bar.
    import sys
    store = tmp_path / "settings"
    store.mkdir()
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(store))
    shared = next(m._settings_dir for n, m in list(sys.modules.items())
                  if n.endswith("conftest") and hasattr(m, "_settings_dir"))
    import core.extensions as extensions
    monkeypatch.setattr(extensions, "user_plugins_dir",
                        lambda: tmp_path / "plugins")
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    for dock in w._sidebar_docks():
        dock.show()
    _app.processEvents()
    w._style_dock_tabs()
    _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, shared)


def _bar_of(win, dock):
    """The tab bar on screen that holds ``dock``'s tab, and its index."""
    # Qt keeps spare tab bars around: the one on screen, inside the window.
    for bar in win._dock_tab_bars():
        if not bar.isVisible() or not win.rect().contains(
                bar.mapTo(win, QPoint(0, 0))):
            continue
        for i in range(bar.count()):
            if bar.tabText(i) == dock.windowTitle():
                return bar, i
    raise AssertionError(f"no tab for {dock.windowTitle()}")


def _image(icon: QIcon):
    return icon.pixmap(48, 48).toImage()


def test_every_panel_icon_is_drawn_and_its_own():
    from views.icons import tool_icon
    images = []
    for key in PANEL_KEYS:
        icon = tool_icon(key)
        assert not icon.isNull(), key
        img = _image(icon)
        assert any(img.pixelColor(x, y).alpha() > 0
                   for x in range(0, 48, 2) for y in range(0, 48, 2)), key
        images.append(img)
    for i, a in enumerate(images):
        for b in images[i + 1:]:
            assert a != b


def test_every_built_in_tray_has_its_icon(win):
    keys = {d.property("icon_key") for d in
            (win.tray, win.bim_tray, win.georef_tray, win.project_browser,
             win.layers_dock)}
    assert keys == {"panel_properties", "panel_bim", "panel_terrain",
                    "panel_browser", "layers_panel"}
    for dock in win._sidebar_docks():
        assert dock.testAttribute(Qt.WA_SetWindowIcon), dock.windowTitle()
        assert not dock.windowIcon().isNull()


def test_a_tab_takes_the_icons_room_not_the_names(win):
    bar, i = _bar_of(win, win.tray)
    hint = bar.tabSizeHint(i).width()
    name = bar.fontMetrics().horizontalAdvance(win.tray.windowTitle())
    assert hint < bar.iconSize().width() + 32
    assert hint < name + bar.iconSize().width()     # what it took before
    # Every tab alike as drawn: the bar is about as wide as its icons.
    widths = {win._real_tab_rect(bar, j).width() for j in range(bar.count())}
    assert max(widths) - min(widths) <= 2


def test_the_tab_keeps_the_name_as_text_and_tooltip(win):
    bar, i = _bar_of(win, win.bim_tray)
    assert bar.tabText(i) == "BIM"
    assert bar.tabToolTip(i) == "BIM"
    assert not bar.tabIcon(i).isNull()
    # The tab under the pointer still names its tray (found by the text).
    pos = bar.mapTo(win, bar.tabRect(i).center())
    assert win._dock_tab_at(pos) is win.bim_tray


def test_the_tab_draws_no_text():
    # A label with a name and no icon: the application's style paints the
    # name, the tabs' style paints nothing.
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QStyle, QStyleOptionTab, QTabBar
    from views.main_window import _IconTabStyle
    bar = QTabBar()

    def painted(style) -> bool:
        opt = QStyleOptionTab()
        opt.initFrom(bar)
        opt.text = "Properties"
        opt.rect = QRect(0, 0, 200, 40)
        pm = QPixmap(200, 40)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        style.drawControl(QStyle.CE_TabBarTabLabel, opt, p, bar)
        p.end()
        img = pm.toImage()
        return any(img.pixelColor(x, y).alpha() > 0
                   for x in range(200) for y in range(40))

    assert painted(QApplication.style())
    assert not painted(_IconTabStyle(QApplication.style().name()))


def test_the_panel_header_shows_the_name_and_follows_a_rename(win):
    header = win.tray.titleBarWidget()
    label = header.findChild(QLabel, "dock_header_name")
    assert label is not None and label.text() == "Properties"
    assert label.isVisible()
    win.tray.setWindowTitle("Props")
    _app.processEvents()
    assert label.text() == "Props"
    bar, i = _bar_of(win, win.tray)
    assert bar.tabToolTip(i) == "Props"
    win.tray.setWindowTitle("Properties")


def test_a_tray_alone_has_its_icon_tab_beside_the_name(win):
    from views.main_window import _DockTitleTab
    win.move_dock(win.project_browser, Qt.LeftDockWidgetArea)
    _app.processEvents()
    _app.processEvents()
    header = win.project_browser.titleBarWidget()
    tab = header.tab
    assert isinstance(tab, _DockTitleTab)
    assert tab.tabToolTip(0) == "Browser" and not tab.tabIcon(0).isNull()
    assert tab.tabSizeHint(0).width() < tab.iconSize().width() + 32
    label = header.findChild(QLabel, "dock_header_name")
    assert label.text() == "Browser"
    assert label.mapTo(header, QPoint(0, 0)).x() >= tab.width()
    win.move_dock(win.project_browser, Qt.RightDockWidgetArea)


def test_a_new_icon_reaches_no_tab_already_gone(win, monkeypatch):
    # A tray alone on its side, then tabbed: its own tab is deleted, and a
    # later icon (the theme redrawn) must not go looking for it.
    import sys
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: errors.append(a[1]))
    win.move_dock(win.project_browser, Qt.LeftDockWidgetArea)
    _app.processEvents()
    _app.processEvents()
    win.move_dock(win.bim_tray, Qt.LeftDockWidgetArea)
    for _ in range(3):
        _app.processEvents()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    _app.processEvents()
    win._refresh_toolbar_icons()
    _app.processEvents()
    assert not errors
    win.move_dock(win.project_browser, Qt.RightDockWidgetArea)
    win.move_dock(win.bim_tray, Qt.RightDockWidgetArea)


def test_add_panel_takes_a_drawn_icon_or_a_qicon(win):
    from views.extension_api import ExtensionApp
    app = ExtensionApp(win, "iconext")
    drawn = app.add_panel("Drawn", QLabel("a"), name="drawn",
                          icon="panel_render")
    assert drawn.property("icon_key") == "panel_render"
    assert not drawn.windowIcon().isNull()
    pm = QPixmap(16, 16)
    pm.fill(Qt.red)
    given = app.add_panel("Given", QLabel("b"), name="given", icon=QIcon(pm))
    assert given.windowIcon().cacheKey() == QIcon(pm).cacheKey() \
        or given.windowIcon().pixmap(16, 16).toImage().pixelColor(8, 8) \
        == Qt.red
    # A shared tab: the first that brings an icon sets it.
    shared = app.add_panel("Shared", QLabel("c"), panel="sharedext")
    app.add_panel("Shared", QLabel("d"), panel="sharedext", icon="panel_ai")
    assert shared.property("icon_key") == "panel_ai"


def test_a_panel_without_an_icon_shows_its_initial(win):
    from views.extension_api import ExtensionApp
    from views.icons import letter_icon
    dock = ExtensionApp(win, "plain").add_panel("Zeta", QLabel("z"))
    win._style_dock_tabs()
    _app.processEvents()
    assert not dock.windowIcon().isNull()
    assert _image(dock.windowIcon()) == _image(letter_icon("Zeta"))


def test_the_icons_follow_the_theme(win):
    before = _image(win.tray.windowIcon())
    from views import icons
    real = icons._ink
    from PySide6.QtGui import QColor
    icons._ink = lambda: QColor(250, 0, 250)
    try:
        win._refresh_toolbar_icons()
    finally:
        icons._ink = real
    assert _image(win.tray.windowIcon()) != before
    bar, i = _bar_of(win, win.tray)                 # the tab redrawn too
    assert _image(bar.tabIcon(i)) == _image(win.tray.windowIcon())
    win._refresh_toolbar_icons()
    assert _image(win.tray.windowIcon()) == before
    assert _image(bar.tabIcon(i)) == before


def test_a_panel_an_extension_builds_itself_gets_an_icon_too(win):
    # «Escenas» and the like make their own QDockWidget: tabbed with the
    # trays, its tab would be blank without the initial.
    from PySide6.QtWidgets import QDockWidget
    dock = QDockWidget("Scenes", win)
    dock.setObjectName("own_scenes")
    dock.setWidget(QLabel("s"))
    win.addDockWidget(win.dockWidgetArea(win.tray), dock)
    win.tabifyDockWidget(win.tray, dock)
    _app.processEvents()
    win._style_dock_tabs()
    _app.processEvents()
    assert not dock.windowIcon().isNull()
    bar, i = _bar_of(win, dock)
    assert not bar.tabIcon(i).isNull()
    assert bar.tabToolTip(i) == "Scenes"
    dock.deleteLater()


def _gear(bar):
    from PySide6.QtWidgets import QToolButton
    return bar.findChild(QToolButton, "panel_options_button")


def test_the_gear_is_fixed_at_the_end_of_the_tabs_row(win):
    bar, _i = _bar_of(win, win.tray)
    gear = _gear(bar)
    assert gear.isVisible() and not gear.icon().isNull()
    assert gear.toolTip() == "Panel options" and gear.autoRaise()
    assert gear.geometry().right() == bar.width() - 1   # the same row, its end
    assert gear.y() == 0 and gear.height() == bar.height()
    # No tab, no matter how many come: it stays where it is, after them all.
    win.set_tray_shown(win.georef_tray, False)
    _app.processEvents()
    win._style_dock_tabs()
    _app.processEvents()
    bar, _i = _bar_of(win, win.tray)
    assert _gear(bar).geometry().right() == bar.width() - 1
    last = win._real_tab_rect(bar, bar.count() - 1)
    assert last.right() < _gear(bar).x()
    # Its header gets none: the name alone.
    assert win.tray.titleBarWidget().options is None
    win.set_tray_shown(win.georef_tray, True)


def test_the_room_after_the_last_tab_is_no_tab(win):
    bar, _i = _bar_of(win, win.tray)
    i = bar.count() - 1
    drawn = win._real_tab_rect(bar, i)
    assert drawn.width() < bar.tabRect(i).width()
    room = QPoint(drawn.right() + 3, drawn.center().y())
    assert bar.tabAt(room) == i and win._tab_on_bar_at(bar, room) == -1
    assert win._tab_on_bar_at(bar, drawn.center()) == i
    assert _tip_over(bar, i) == win._dock_of_tab(bar, i).windowTitle()


def test_the_tabs_bring_out_the_arrows_before_reaching_the_gear(win):
    # The «+» and the gear count: the arrows come before tabs go under them.
    from PySide6.QtWidgets import QToolButton
    from views.extension_api import ExtensionApp
    app = ExtensionApp(win, "fill_up")
    for n in range(30):
        app.add_panel(f"Fill {n}", QLabel(str(n)), name=str(n))
        _app.processEvents()
        win._style_dock_tabs()
        _app.processEvents()
        bar, _i = _bar_of(win, win.tray)
        plus = bar.findChild(QToolButton, "add_panels_button")
        arrows = [b for b in bar.findChildren(QToolButton)
                  if b not in (plus, _gear(bar)) and b.isVisible()]
        if not arrows:
            last = win._real_tab_rect(bar, bar.count() - 1)
            assert last.right() < plus.x()
            assert plus.geometry().right() < _gear(bar).x()
    assert arrows


def test_the_gear_opens_the_panel_options(win, monkeypatch):
    shown = []
    monkeypatch.setattr(win, "_popup_menu",
                        lambda menu, pos: shown.append(menu))
    win.tray.raise_()
    _app.processEvents()
    _gear(_bar_of(win, win.tray)[0]).click()
    texts = [a.text() for a in shown[0].actions()]
    assert texts[:2] == ["Tabs on top", "Tabs on the right, vertical"]
    assert "Move to the left side" in texts
    assert win.bim_tray.windowTitle() in texts      # and the panels list
    assert "Show all panels" in texts
    # The panel's own side: from one on the left, back to the right.
    win.move_dock(win.project_browser, Qt.LeftDockWidgetArea)
    _app.processEvents()
    _app.processEvents()
    win.project_browser.titleBarWidget().options.click()    # alone: its header
    assert "Move to the right side" in [a.text() for a in shown[1].actions()]
    win.move_dock(win.project_browser, Qt.RightDockWidgetArea)


def _open_on(win, monkeypatch, opener, dock):
    """Tick ``dock`` in the list that ``opener`` pops up."""
    def pick(menu, pos):
        next(a for a in menu.actions()
             if a.text() == dock.windowTitle()).trigger()
    monkeypatch.setattr(win, "_popup_menu", pick)
    opener()
    _app.processEvents()
    win._style_dock_tabs()
    _app.processEvents()
    _app.processEvents()


def test_a_closed_panel_opens_on_the_side_of_the_plus(win, monkeypatch):
    from PySide6.QtWidgets import QToolButton
    win.set_tray_shown(win.georef_tray, False)
    win.move_dock(win.project_browser, Qt.LeftDockWidgetArea)
    _app.processEvents()
    win._style_dock_tabs()
    _app.processEvents()
    assert win.dockWidgetArea(win.georef_tray) == Qt.RightDockWidgetArea
    # The left side holds one tray alone: the «+» of its own tab.
    tab = win.project_browser.titleBarWidget().tab
    plus = tab.findChild(QToolButton, "add_panels_button")
    _open_on(win, monkeypatch, plus.click, win.georef_tray)
    assert win.dockWidgetArea(win.georef_tray) == Qt.LeftDockWidgetArea
    assert not win.georef_tray.isHidden()
    assert win.georef_tray in win.tabifiedDockWidgets(win.project_browser)
    # Now tabbed there, another one comes by the bar's «+», or by its gear.
    win.set_tray_shown(win.bim_tray, False)
    bar, _i = _bar_of(win, win.project_browser)
    plus = bar.findChild(QToolButton, "add_panels_button")
    _open_on(win, monkeypatch, plus.click, win.bim_tray)
    assert win.dockWidgetArea(win.bim_tray) == Qt.LeftDockWidgetArea
    win.set_tray_shown(win.bim_tray, False)
    win.move_dock(win.bim_tray, Qt.RightDockWidgetArea)
    win.set_tray_shown(win.bim_tray, False)
    bar, _i = _bar_of(win, win.project_browser)
    _open_on(win, monkeypatch, _gear(bar).click, win.bim_tray)
    assert win.dockWidgetArea(win.bim_tray) == Qt.LeftDockWidgetArea


def test_an_open_panel_stays_on_its_side_and_the_window_menu_moves_none(win):
    # Unticked from the other side's list it closes where it is; from
    # Window ▸ Panels, which belongs to no side, it comes back where it was.
    win.set_tray_shown(win.bim_tray, False, Qt.LeftDockWidgetArea)
    assert win.dockWidgetArea(win.bim_tray) == Qt.RightDockWidgetArea
    win.set_tray_shown(win.bim_tray, True)
    assert win.dockWidgetArea(win.bim_tray) == Qt.RightDockWidgetArea
    assert not win.bim_tray.isHidden()


def _set_vertical(win, on):
    win.set_dock_tabs_vertical(on)
    _app.processEvents()
    win._style_dock_tabs()
    _app.processEvents()


def test_the_tabs_can_run_down_the_panels_right_edge(win):
    from PySide6.QtWidgets import QTabBar
    from views.main_window import DOCK_TAB_ICON_PX, _VERTICAL_TABS
    assert not win.dock_tabs_vertical()
    assert _bar_of(win, win.tray)[0].shape() not in _VERTICAL_TABS
    _set_vertical(win, True)
    assert win.dock_tabs_vertical()
    bar, _i = _bar_of(win, win.tray)
    assert bar.shape() == QTabBar.RoundedEast
    tops = [bar.tabRect(j).top() for j in range(bar.count())]
    assert tops == sorted(tops) and len(set(tops)) == bar.count()
    assert bar.width() < bar.height()
    # On the panel's right, in a tab as tall as the icon's room.
    shown = next(d for d in win._sidebar_docks() if d.isVisible()
                 and not d.visibleRegion().isEmpty())
    assert bar.mapTo(win, QPoint(0, 0)).x() >= \
        shown.mapTo(win, QPoint(shown.width() - 1, 0)).x()
    assert bar.tabSizeHint(0).height() < DOCK_TAB_ICON_PX + 32
    # Still found, named and told as ever.
    bar, i = _bar_of(win, win.bim_tray)
    pos = bar.mapTo(win, bar.tabRect(i).center())
    assert win._dock_tab_at(pos) is win.bim_tray
    assert _tip_over(bar, i) == "BIM"
    # And back on top.
    _set_vertical(win, False)
    assert _bar_of(win, win.tray)[0].shape() not in _VERTICAL_TABS


def test_a_vertical_tab_paints_its_icon_upright():
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QStyle, QStyleOptionTab, QTabBar
    from views.main_window import _IconTabStyle
    pm = QPixmap(20, 20)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.fillRect(0, 0, 20, 10, Qt.red)                # the icon's top half
    p.end()
    opt = QStyleOptionTab()
    opt.shape = QTabBar.RoundedEast
    opt.state = QStyle.State_Enabled | QStyle.State_Selected
    opt.icon = QIcon(pm)
    opt.iconSize = pm.size()
    opt.rect = QRect(0, 0, 40, 40)
    out = QPixmap(40, 40)
    out.fill(Qt.transparent)
    p = QPainter(out)
    _IconTabStyle(QApplication.style().name()).drawControl(
        QStyle.CE_TabBarTabLabel, opt, p, None)
    p.end()
    img = out.toImage()
    assert img.pixelColor(20, 13).alpha() > 0       # the top half on top
    assert img.pixelColor(20, 26).alpha() == 0


def test_the_plus_follows_the_vertical_tabs(win):
    _set_vertical(win, True)
    from PySide6.QtWidgets import QToolButton
    bar, _i = _bar_of(win, win.tray)
    btn = bar.findChild(QToolButton, "add_panels_button")
    last = win._real_tab_rect(bar, bar.count() - 1)
    assert btn.isVisible()
    assert last.bottom() < btn.y() <= last.bottom() + 6
    assert 0 <= btn.x() and btn.geometry().right() < bar.width()
    # The gear, at the column's end.
    assert _gear(bar).geometry().bottom() == bar.height() - 1
    assert btn.geometry().bottom() < _gear(bar).y()
    _set_vertical(win, False)


def test_the_plus_stays_inside_a_vertical_bar_that_overflows(win):
    from PySide6.QtWidgets import QToolButton
    from views.extension_api import ExtensionApp
    app = ExtensionApp(win, "many_down")
    for i in range(60):
        app.add_panel(f"Down {i}", QLabel(str(i)), name=str(i))
    win._show_all_trays()
    _set_vertical(win, True)
    bar, _i = _bar_of(win, win.tray)
    btn = bar.findChild(QToolButton, "add_panels_button")
    gear = _gear(bar)
    arrows = [b for b in bar.findChildren(QToolButton)
              if b not in (btn, gear) and b.isVisible()]
    assert arrows                                   # they really do not fit
    for arrow in arrows:
        assert not btn.geometry().intersects(arrow.geometry())
        assert arrow.y() > btn.y()                  # «+», then the arrows,
    # and the gear at the end.
    assert max(a.geometry().bottom() for a in arrows) == gear.y() - 1
    assert gear.geometry().bottom() == bar.height() - 1
    _set_vertical(win, False)


def test_the_choice_is_kept_and_a_saved_layout_does_not_undo_it(win):
    from views.main_window import _VERTICAL_TABS
    state = win.saveState()                         # saved with tabs on top
    _set_vertical(win, True)
    win.restoreState(state)
    _app.processEvents()
    assert _bar_of(win, win.tray)[0].shape() in _VERTICAL_TABS
    # A new window reads it.
    from views.main_window import MainWindow
    other = MainWindow()
    other.resize(1400, 900)
    other.show()
    _app.processEvents()
    other._style_dock_tabs()
    _app.processEvents()
    assert other.dock_tabs_vertical()
    assert _bar_of(other, other.tray)[0].shape() in _VERTICAL_TABS
    other._saved_version = other.viewport.scene.version
    other.close()
    _set_vertical(win, False)


def test_restore_default_panels_puts_the_tabs_back_on_top(win):
    from views.main_window import _VERTICAL_TABS
    _set_vertical(win, True)
    win.restore_default_trays()
    _app.processEvents()
    win._style_dock_tabs()
    _app.processEvents()
    assert not win.dock_tabs_vertical()
    assert _bar_of(win, win.tray)[0].shape() not in _VERTICAL_TABS


def _tip_over(bar, i):
    """What pops up with the pointer resting on tab ``i``."""
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QToolTip
    QToolTip.hideText()
    _app.processEvents()
    # Near its start: the last tab's rect holds the room it keeps too.
    centre = bar.tabRect(i).topLeft() + QPoint(8, 8)
    QApplication.sendEvent(bar, QHelpEvent(QEvent.ToolTip, centre,
                                           bar.mapToGlobal(centre)))
    _app.processEvents()
    return QToolTip.text() if QToolTip.isVisible() else ""


def test_resting_the_pointer_on_an_icon_tells_its_name(win):
    # Qt's own tray bars show a tab's tooltip only when its name is cut
    # short; the icon alone never is, so the name never came.
    bar, i = _bar_of(win, win.bim_tray)
    assert _tip_over(bar, i) == "BIM"
    bar, i = _bar_of(win, win.tray)
    assert _tip_over(bar, i) == "Properties"
    # A tray alone on its side: its own tab tells it too.
    win.move_dock(win.project_browser, Qt.LeftDockWidgetArea)
    _app.processEvents()
    _app.processEvents()
    tab = win.project_browser.titleBarWidget().tab
    assert _tip_over(tab, 0) == "Browser"
    win.move_dock(win.project_browser, Qt.RightDockWidgetArea)
