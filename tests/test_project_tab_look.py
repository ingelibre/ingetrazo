# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""How the project tabs look (views/documents.py): drawn as the side
panels' tabs with an accent line under the active name; as wide as a name
and its cross need and as tall as a line of text, never cutting the name;
the cross bigger and against the tab's right edge; «+» drawn, centred and
right after the last tab, as tall as a tab."""
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
    w.show()
    QApplication.processEvents()
    yield w
    for doc in list(w._documents):
        doc.saved_content = doc.viewport.scene.content_version
    w._saved_version = w.viewport.scene.version
    w.close()


def _tabs(win):
    return win._project_tabs.tabs


def test_drawn_as_the_panels_tabs(win):
    tabs = _tabs(win)
    assert not tabs.documentMode()
    assert "::tab" not in win._project_tabs.styleSheet()


def test_an_accent_line_under_the_active_name(win):
    tabs = _tabs(win)
    line = tabs.underline_rect()
    assert line is not None and tabs.tabRect(0).contains(line)
    from views.theme import accent_color
    c = tabs.grab().toImage().pixelColor(line.center())
    a = accent_color()
    assert abs(c.red() - a.red()) + abs(c.green() - a.green()) \
        + abs(c.blue() - a.blue()) < 40


def test_narrow_without_cutting_the_name(win, tmp_path):
    from core.scene import Scene
    from formats import igz
    from PySide6.QtWidgets import QStyleOptionTab
    path = tmp_path / "casa-pestanas.igz"
    igz.save_scene(Scene(), path)
    win._new_document()
    win.open_path(path)
    QApplication.processEvents()
    tabs = _tabs(win)
    for i in range(tabs.count()):
        opt = QStyleOptionTab()
        tabs.initStyleOption(opt, i)
        assert "…" not in opt.text and "..." not in opt.text


def test_the_cross_is_bigger_and_against_the_right_edge(win):
    tabs = _tabs(win)
    btn = tabs.tabButton(0, tabs.ButtonPosition.RightSide)
    assert btn.iconSize().width() == tabs.CLOSE_ICON >= 12
    tab = tabs.tabRect(0)
    assert tab.right() - btn.geometry().right() == tabs.CLOSE_EDGE
    assert abs(btn.geometry().center().y() - tab.center().y()) <= 1


def test_the_cross_closes_its_project(win):
    first = win._doc
    second = win._new_document()
    tabs = _tabs(win)
    i = win._project_tabs.index_of(second)
    seen = []
    win._project_tabs.closeRequested.connect(seen.append)
    tabs.tabButton(i, tabs.ButtonPosition.RightSide).click()
    QApplication.processEvents()
    assert seen and seen[0] is second
    assert first in win._documents


def test_plus_right_after_the_last_tab_as_tall_as_it(win):
    bar = win._project_tabs
    tabs, plus = bar.tabs, bar.plus
    QApplication.processEvents()
    last = tabs.tabRect(tabs.count() - 1)
    end = tabs.mapTo(bar, last.topRight()).x()
    start = plus.mapTo(bar, plus.rect().topLeft()).x()
    assert 0 <= start - end <= 2
    assert plus.height() == tabs.sizeHint().height()


def test_plus_is_a_drawn_icon_centred(win):
    plus = win._project_tabs.plus
    assert not plus.text() and not plus.icon().isNull()
    img = plus.icon().pixmap(48, 48).toImage()
    xs = [x for y in range(img.height()) for x in range(img.width())
          if img.pixelColor(x, y).alpha() > 60]
    ys = [y for y in range(img.height()) for x in range(img.width())
          if img.pixelColor(x, y).alpha() > 60]
    assert abs((min(xs) + max(xs)) / 2 - img.width() / 2) <= 1.5
    assert abs((min(ys) + max(ys)) / 2 - img.height() / 2) <= 1.5


def test_the_views_button_comes_first(win):
    bar = win._project_tabs
    assert bar.views_button.x() < bar.tabs.x()


def test_as_tall_as_the_side_panels_tabs(win):
    """The same height as the tabs of the panels on the side."""
    from PySide6.QtWidgets import QTabBar
    panel_bars = [b for b in win.findChildren(QTabBar)
                  if b.isVisible() and b is not _tabs(win)
                  and b.objectName() != "scene_tab_bar" and b.count()]
    assert panel_bars, "no panel tabs to compare with"
    want = panel_bars[0].tabRect(0).height()
    assert _tabs(win).tabRect(0).height() == want


def test_plus_always_adds_a_tab(win):
    """«+» on an untouched Untitled made nothing appear: every click is a
    new project of its own."""
    bar = win._project_tabs
    assert bar.count() == 1
    bar.plus.click()
    bar.plus.click()
    bar.plus.click()
    assert bar.count() == 4 and len(win._documents) == 4
    assert win._doc is win._documents[-1]          # the newest, in front
    assert not win._is_dirty()


def test_the_tab_menus_new_adds_a_tab_too(win):
    from core.i18n import tr
    menu = win._build_project_tab_menu(win._doc)
    next(a for a in menu.actions() if a.text() == tr("New")).trigger()
    assert len(win._documents) == 2


def test_little_room_after_the_cross(win):
    """The ink of the cross ends a little way from the tab's right edge:
    a small gap, not the wide empty strip there was."""
    tabs = _tabs(win)
    btn = tabs.tabButton(0, tabs.ButtonPosition.RightSide)
    img = btn.icon().pixmap(tabs.CLOSE_ICON, tabs.CLOSE_ICON).toImage()
    ink_right = max(x for y in range(img.height()) for x in range(img.width())
                    if img.pixelColor(x, y).alpha() > 60)
    icon_left = btn.geometry().x() + (btn.width() - img.width()) // 2
    gap = tabs.tabRect(0).right() - (icon_left + ink_right)
    assert 3 <= gap <= tabs.CLOSE_EDGE + 5


def test_the_cross_stays_put_when_a_tab_is_clicked(win):
    """A click on a tab put the cross back where the style wanted it, a
    dozen pixels from the edge."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    win._project_tabs.plus.click()
    QApplication.processEvents()
    tabs = _tabs(win)

    def gaps():
        return [tabs.tabRect(i).right()
                - tabs.tabButton(i, tabs.ButtonPosition.RightSide)
                .geometry().right() for i in range(tabs.count())]
    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier,
                     tabs.tabRect(0).center())
    QApplication.processEvents()
    tabs.repaint()
    assert gaps() == [tabs.CLOSE_EDGE] * tabs.count()
