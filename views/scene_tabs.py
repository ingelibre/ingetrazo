# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The active project's scenes as tabs, under the viewport.

A presentation goes from scene to scene; reading them as tabs along the
foot of the view — their names, in their order — is quicker than the list
in the Scenes panel, and they stay apart from the project tabs above.

- A (left) click on a tab shows that scene, as a double-click in the
  Scenes panel does; the scene shown wears a line in the accent colour
  under its name. A right-click only opens its menu: it shows nothing and
  changes nothing.
- **+** right after the last tab keeps the current view as a new scene
  (the panel's «+ Scene»).
- A right-click on a tab offers to update that scene from the current
  view, or to delete it (one undo step); on the bar itself, to hide the
  row. Both menus open upwards: the row sits at the foot of the window.
- A project without scenes says how to make one.
- On by default; each project keeps its own choice, from the right-click
  menu of its tab (``Document.scene_tabs``).

The row only shows and asks: the window gives it the views to list and
does the showing and the adding (``MainWindow._refresh_scene_tabs``).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QStyle, QStyleOptionTab,
                               QTabBar, QToolButton, QWidget)

from core.i18n import tr

#: A project shows its scenes as tabs unless its tab's menu turned them off.
SCENE_TABS_DEFAULT = True


class SceneTabBar(QTabBar):
    """The scenes' tabs, hanging from the view's lower edge, with an accent
    line under the name of the scene shown."""

    #: Thickness of the accent line and its gap above the tab's foot (px).
    LINE_PX = 2
    LINE_GAP = 3

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("scene_tab_bar")
        self.setShape(QTabBar.RoundedSouth)
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.ElideRight)
        self.views: list = []
        #: The button of the press that ``tabBarClicked`` follows: Qt sends
        #: that signal for any button, and a right-click showed the scene.
        self.pressed_button = Qt.LeftButton

    def mousePressEvent(self, ev) -> None:  # noqa: N802 — Qt override
        self.pressed_button = ev.button()
        try:
            super().mousePressEvent(ev)
        finally:
            self.pressed_button = Qt.LeftButton

    def show_views(self, views) -> None:
        """List ``views`` (the scene's saved views); the one marked stays
        marked while its name is still there."""
        names = [v.name for v in views]
        self.views = list(views)
        if names == [self.tabText(i) for i in range(self.count())]:
            return
        current = (self.tabText(self.currentIndex())
                   if self.currentIndex() >= 0 else None)
        self.blockSignals(True)
        while self.count():
            self.removeTab(0)
        for name in names:
            self.addTab(name)
        self.setCurrentIndex(names.index(current) if current in names else -1)
        self.blockSignals(False)
        self.updateGeometry()

    def sizeHint(self):  # noqa: N802 — Qt override
        """Exactly as wide as its tabs: Qt's hint keeps room for the
        scroll arrows, which left «+» far from a lone scene."""
        hint = super().sizeHint()
        if self.count():
            hint.setWidth(sum(self.tabSizeHint(i).width()
                              for i in range(self.count())))
        return hint

    def minimumSizeHint(self):  # noqa: N802 — Qt override
        """Never more than its tabs (Qt's minimum is the arrows' room)."""
        hint = super().minimumSizeHint()
        hint.setWidth(min(hint.width(), self.sizeHint().width()))
        return hint

    def underline_rect(self):
        """Where the accent line goes (None with no scene marked)."""
        i = self.currentIndex()
        if i < 0 or not self.tabText(i):
            return None
        opt = QStyleOptionTab()
        self.initStyleOption(opt, i)
        text = self.style().subElementRect(QStyle.SE_TabBarTabText, opt, self)
        width = min(self.fontMetrics().horizontalAdvance(opt.text),
                    text.width())
        tab = self.tabRect(i)
        y = tab.bottom() - self.LINE_GAP - self.LINE_PX + 1
        return QRect(text.center().x() - width // 2, y, width, self.LINE_PX)

    def paintEvent(self, ev) -> None:  # noqa: N802 — Qt override
        super().paintEvent(ev)
        rect = self.underline_rect()
        if rect is None:
            return
        from PySide6.QtGui import QPainter
        from views.theme import accent_color
        p = QPainter(self)
        p.fillRect(rect, accent_color())
        p.end()


class SceneTabRow(QWidget):
    """The tabs, **+**, and the hint of a project without scenes."""

    sceneClicked = Signal(int)     # the index of the scene clicked
    addRequested = Signal()        # «+»: the current view as a new scene
    #: A right-click on a tab: its index and where (global position).
    menuRequested = Signal(int, QPoint)
    #: A right-click on the bar, off the tabs: where (global position).
    barMenuRequested = Signal(QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("scene_tabs")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 6, 0)
        row.setSpacing(0)
        self.tabs = SceneTabBar(self)
        self.tabs.tabBarClicked.connect(self._on_clicked)
        self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._on_menu)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.barMenuRequested.emit(self.mapToGlobal(pos)))
        row.addWidget(self.tabs, 0, Qt.AlignTop)
        plus = self.plus = QToolButton(self)
        plus.setObjectName("scene_tab_new")
        from views.icons import tool_icon
        plus.setProperty("icon_key", "plus")     # repainted with the theme
        plus.setIcon(tool_icon("plus"))
        # The same «+» as after the project tabs: icon, size, hover.
        from views.documents import PLUS_ICON
        plus.setIconSize(QSize(PLUS_ICON, PLUS_ICON))
        plus.setToolButtonStyle(Qt.ToolButtonIconOnly)
        plus.setAutoRaise(True)
        plus.setCursor(Qt.PointingHandCursor)
        plus.setToolTip(tr("Save the current view and layer visibility"))
        plus.setAccessibleName(tr("+ Scene"))
        plus.clicked.connect(self.addRequested.emit)
        row.addWidget(plus, 0, Qt.AlignTop)
        self.hint = QLabel(tr(
            "No scenes yet: «+» keeps the current view as one."), self)
        self.hint.setObjectName("scene_tab_hint")
        self.hint.setContentsMargins(6, 3, 0, 0)
        row.addWidget(self.hint, 0, Qt.AlignTop)
        row.addStretch(1)
        from views.theme import style as theme_style
        theme_style(self,
            "#scene_tabs {{ background: palette(window); }}"
            "QLabel#scene_tab_hint {{ color: {muted}; }}"
            "QToolButton#scene_tab_new {{ border: none; border-radius: 6px;"
            " background: transparent; padding: 0px; }}"
            "QToolButton#scene_tab_new:hover {{"
            " background: rgba({accent_rgb}, 36); }}")
        self._match_plus()

    def _match_plus(self) -> None:
        """«+» as tall as a scene tab, level with the tabs."""
        from views.documents import size_plus_button
        size_plus_button(self.plus, self.tabs)

    def showEvent(self, ev) -> None:  # noqa: N802 — Qt override
        super().showEvent(ev)
        self._match_plus()

    def show_views(self, views) -> None:
        """The project's scenes; with none, the hint instead of the tabs."""
        self.tabs.show_views(views)
        self.tabs.setVisible(bool(views))
        self.hint.setVisible(not views)
        self._match_plus()

    def mark(self, index: int) -> None:
        """Mark the scene at ``index`` as the one shown."""
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)

    def _on_menu(self, pos) -> None:
        i = self.tabs.tabAt(pos)
        if i >= 0:
            self.menuRequested.emit(i, self.tabs.mapToGlobal(pos))
        else:                              # the bar's own room, off the tabs
            self.barMenuRequested.emit(self.tabs.mapToGlobal(pos))

    def _on_clicked(self, index: int) -> None:
        # Only the left button shows a scene: a right-click is the menu's.
        if index >= 0 and self.tabs.pressed_button == Qt.LeftButton:
            self.tabs.setCurrentIndex(index)
            self.sceneClicked.emit(index)


def menu_upwards(menu, global_pos) -> QPoint:
    """Where to open ``menu`` so it grows UP from ``global_pos`` (the scene
    row sits at the window's foot: downwards it ran off the screen)."""
    return QPoint(global_pos.x(), global_pos.y() - menu.sizeHint().height())
