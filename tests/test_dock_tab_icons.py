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
    # Every tab alike: the bar is about as wide as its icons.
    widths = {bar.tabSizeHint(j).width() for j in range(bar.count())}
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


def _tip_over(bar, i):
    """What pops up with the pointer resting on tab ``i``."""
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QToolTip
    QToolTip.hideText()
    _app.processEvents()
    centre = bar.tabRect(i).center()
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
