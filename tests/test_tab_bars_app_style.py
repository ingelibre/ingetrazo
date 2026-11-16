# SPDX-License-Identifier: GPL-3.0-or-later
"""The project and scene tab bars measure with the application's style
(#1225).

With a style sheet on the application, a widget's ``style()`` is a style
sheet style PySide only knows as a QCommonStyle: each tab bar's calls
left one more of those Python wrappers behind, and on Windows their
clean-up at exit could crash. Measured with the application's style the
wrappers no longer pile up, and the tabs come out the same size."""
from __future__ import annotations

import gc
import sys

import pytest
from PySide6.QtWidgets import QApplication, QStyle

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture
def themed():
    """The application with a theme's style sheet on, as it runs."""
    app = QApplication.instance()
    before = app.styleSheet()
    from views.theme import apply_theme
    apply_theme(app, "light")
    yield app
    app.setStyleSheet(before)


def _sheet_style_wrappers() -> int:
    """Python wrappers of a style sheet style: PySide knows that class
    only as a QCommonStyle (IngeTrazo's own styles are subclasses)."""
    from PySide6.QtWidgets import QCommonStyle
    gc.collect()
    return sum(1 for o in gc.get_objects()
               if type(o) is QCommonStyle)


def _project_bar(names):
    from views.documents import _ProjectTabs
    bar = _ProjectTabs()
    for n in names:
        bar.addTab(n)
    bar.resize(600, 40)
    bar.show()
    QApplication.processEvents()
    return bar


def _scene_bar(names):
    from views.scene_tabs import SceneTabBar
    bar = SceneTabBar()
    for n in names:
        bar.addTab(n)
    bar.setCurrentIndex(0)
    bar.resize(600, 40)
    bar.show()
    QApplication.processEvents()
    return bar


def _measure(bar) -> None:
    from views.documents import panel_tab_height
    for i in range(bar.count()):
        bar.tabSizeHint(i)
    bar.underline_rect()
    panel_tab_height(bar)


def test_windows_leave_no_style_sheet_style_wrappers_behind(themed):
    # One wrapper more per window was the leak: 1 to 25 with 24 windows
    # in the issue. Three windows, their tabs measured and drawn.
    from views.main_window import MainWindow
    start = _sheet_style_wrappers()
    wins = []
    try:
        for _ in range(3):
            w = MainWindow()
            w.show()
            QApplication.processEvents()
            _measure(w._project_tabs.tabs)
            wins.append(w)
        assert _sheet_style_wrappers() - start == 0
    finally:
        for w in wins:
            w._saved_version = w.viewport.scene.version
            w.close()


def test_the_tabs_measure_the_same_as_with_the_bars_own_style(themed):
    from PySide6.QtWidgets import QStyleOptionTab
    from views.documents import tab_style
    for make in (_project_bar, _scene_bar):
        bar = make(["Casa", "Plaza mayor", "Detalle de escalera"])
        try:
            own = bar.style()
            assert tab_style(bar) is QApplication.style()
            for i in range(bar.count()):
                opt = QStyleOptionTab()
                bar.initStyleOption(opt, i)
                assert (tab_style(bar).subElementRect(
                            QStyle.SE_TabBarTabText, opt, bar)
                        == own.subElementRect(
                            QStyle.SE_TabBarTabText, opt, bar)), \
                    (type(bar).__name__, bar.tabText(i))
        finally:
            bar.close()
            bar.deleteLater()
    QApplication.processEvents()
