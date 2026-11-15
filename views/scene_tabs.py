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
- Dragging a tab changes the order of the scenes (one undo step): the view
  stays where it is, so the scene shows on the release of a click, not on
  its press. A double-click renames the scene.
- **+** right after the last tab keeps the current view as a new scene
  (the panel's «+ Scene»).
- A right-click on a tab offers to update that scene from the current
  view, to rename it, or to delete it (one undo step); on the bar itself,
  to hide the row. Both menus open upwards: the row sits at the foot of the
  window.
- A project without scenes has no row: its first scene brings it, from the
  Scenes panel, and deleting the last takes it away.
- On by default; each project keeps its own choice, from the right-click
  menu of its tab (``Document.scene_tabs``).

The row only shows and asks: the window gives it the views to list and
does the showing and the adding (``MainWindow._refresh_scene_tabs``).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QStyle,
                               QStyleOptionTab, QTabBar, QToolButton, QWidget)

from core.i18n import tr

#: A project shows its scenes as tabs unless its tab's menu turned them off.
SCENE_TABS_DEFAULT = True


class SceneTabBar(QTabBar):
    """The scenes' tabs, hanging from the view's lower edge, with an accent
    line under the name of the scene shown."""

    #: A left click on a tab, on its release: that it was no drag.
    tabClicked = Signal(int)
    #: A tab dropped elsewhere: the scene's old and new place in the list.
    moveRequested = Signal(int, int)

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
        self.setMovable(True)
        self.tabMoved.connect(self._on_tab_moved)
        #: While the left button holds a tab: the tab pressed and the scene
        #: marked before the press; where a drag has taken it so far; a list
        #: that came in meanwhile.
        self._held = None
        self._moved = None
        self._waiting = None

    def mousePressEvent(self, ev) -> None:  # noqa: N802 — Qt override
        self.pressed_button = ev.button()
        at = self.tabAt(ev.position().toPoint())
        if ev.button() == Qt.LeftButton and at >= 0:
            self._held = (at, self.marked_view())
            self._moved = None
        try:
            super().mousePressEvent(ev)
        finally:
            self.pressed_button = Qt.LeftButton

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802 — Qt override
        super().mouseReleaseEvent(ev)
        if ev.button() != Qt.LeftButton or self._held is None:
            return
        (at, marked), to = self._held, self._moved
        waiting, self._waiting = self._waiting, None
        self._held = self._moved = None
        if to is None:                         # a click, not a drag
            self.tabClicked.emit(at)
        else:
            # Qt marks the tab it presses: the scene shown is still the one.
            self.views.insert(to, self.views.pop(at))
            self._mark(marked)
            if to != at:
                self.moveRequested.emit(at, to)
                self._mark(marked)
                return
        if waiting is not None:
            self.show_views(waiting)

    def hideEvent(self, ev) -> None:  # noqa: N802 — Qt override
        self._held = self._moved = None
        super().hideEvent(ev)
        if self._waiting is not None:
            waiting, self._waiting = self._waiting, None
            self.show_views(waiting)

    def _on_tab_moved(self, index: int, to: int) -> None:
        # In the middle of the drag, and about the NEIGHBOUR the tab passes
        # (Qt slides that one into its place): follow the tab held. The list
        # itself only changes when the tab is dropped.
        if self._held is None:
            return
        at = self._held[0] if self._moved is None else self._moved
        if at == index:
            at = to
        elif index < at <= to:
            at -= 1
        elif to <= at < index:
            at += 1
        self._moved = at

    def marked_view(self):
        """The saved view of the tab marked, or None."""
        i = self.currentIndex()
        return self.views[i] if 0 <= i < len(self.views) else None

    def _mark(self, view) -> None:
        for i, v in enumerate(self.views):
            if v is view:
                self.setCurrentIndex(i)
                return

    def show_views(self, views) -> None:
        """List ``views`` (the scene's saved views); the one marked stays
        marked while it is still there, whatever it is called now."""
        if self._held is not None:             # never under a press or a drag
            self._waiting = list(views)
            return
        names = [v.name for v in views]
        marked = self.marked_view()
        self.views = list(views)
        if names != [self.tabText(i) for i in range(self.count())]:
            self.blockSignals(True)
            while self.count():
                self.removeTab(0)
            for name in names:
                self.addTab(name)
            self.blockSignals(False)
            self.updateGeometry()
        self.blockSignals(True)
        self._mark(marked)
        self.blockSignals(False)

    def sizeHint(self):  # noqa: N802 — Qt override
        """Exactly as wide as its tabs: Qt's hint keeps room for the
        scroll arrows, which left «+» far from a lone scene."""
        hint = super().sizeHint()
        if self.count():
            hint.setWidth(sum(self.tabSizeHint(i).width()
                              for i in range(self.count())))
        else:
            from views.documents import panel_tab_height
            hint.setHeight(panel_tab_height(self))
        return hint

    def tabSizeHint(self, index: int):  # noqa: N802 — Qt override
        """As tall as the project tabs and the side panels' tabs."""
        from views.documents import panel_tab_height
        hint = super().tabSizeHint(index)
        hint.setHeight(panel_tab_height(self))
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
    """The tabs and **+**."""

    sceneClicked = Signal(int)     # the index of the scene clicked
    addRequested = Signal()        # «+»: the current view as a new scene
    #: A right-click on a tab: its index and where (global position).
    menuRequested = Signal(int, QPoint)
    #: A right-click on the bar, off the tabs: where (global position).
    barMenuRequested = Signal(QPoint)
    #: A double-click on a tab: rename that scene.
    renameRequested = Signal(int)
    #: A tab dragged elsewhere: the scene's old and new place in the list.
    moveRequested = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("scene_tabs")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 6, 0)
        row.setSpacing(0)
        self.tabs = SceneTabBar(self)
        self.tabs.tabBarClicked.connect(self._on_clicked)
        self.tabs.tabClicked.connect(self._on_tab_clicked)
        self.tabs.tabBarDoubleClicked.connect(self.renameRequested.emit)
        self.tabs.moveRequested.connect(self.moveRequested.emit)
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
        row.addStretch(1)
        from views.theme import style as theme_style
        theme_style(self,
            "#scene_tabs {{ background: palette(window); }}"
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
        """The project's scenes."""
        self.tabs.show_views(views)
        self._match_plus()

    def mark(self, index: int) -> None:
        """Mark the scene at ``index`` as the one shown."""
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)

    def mark_view(self, view) -> None:
        """Mark the scene ``view`` as the one shown, if it has a tab."""
        self.tabs._mark(view)

    def _on_menu(self, pos) -> None:
        i = self.tabs.tabAt(pos)
        if i >= 0:
            self.menuRequested.emit(i, self.tabs.mapToGlobal(pos))
        else:                              # the bar's own room, off the tabs
            self.barMenuRequested.emit(self.tabs.mapToGlobal(pos))

    def _on_clicked(self, index: int) -> None:
        # Only the left button shows a scene: a right-click is the menu's;
        # and only when it lets go: the press may be the start of a drag.
        if (index >= 0 and self.tabs.pressed_button == Qt.LeftButton
                and self.tabs._held is None):
            self._on_tab_clicked(index)

    def _on_tab_clicked(self, index: int) -> None:
        self.tabs.setCurrentIndex(index)
        self.sceneClicked.emit(index)


def menu_upwards(menu, global_pos) -> QPoint:
    """Where to open ``menu`` so it grows UP from ``global_pos`` (the scene
    row sits at the window's foot: downwards it ran off the screen), kept
    inside the program's window."""
    size = menu.sizeHint()
    at = QPoint(global_pos.x(), global_pos.y() - size.height())
    return keep_inside(at, size, window_bounds(menu))


def window_bounds(menu):
    """The program's window a menu belongs to, in screen coordinates (and
    within its screen), or None while that window is not shown."""
    parent = menu.parentWidget() if menu is not None else None
    win = parent.window() if parent is not None else None
    if win is None or not win.isVisible():
        return None
    rect = win.frameGeometry()
    screen = win.screen()
    if screen is not None:
        rect = rect.intersected(screen.availableGeometry())
    return rect if not rect.isEmpty() else None


def keep_inside(at: QPoint, size, bounds) -> QPoint:
    """``at`` moved just enough for a popup of ``size`` to stay in
    ``bounds`` (a menu opened near the window's edge stays in the program);
    a popup bigger than the window keeps to its top-left corner."""
    if bounds is None:
        return QPoint(at)
    x = min(at.x(), bounds.right() + 1 - size.width())
    y = min(at.y(), bounds.bottom() + 1 - size.height())
    return QPoint(max(x, bounds.left()), max(y, bounds.top()))


class CompositionGuidesRow(QWidget):
    """A menu row: a tick box, as the menu's other on/off entries have,
    that shows or hides the composition guides in ``viewport`` — the active
    view — and «Composition Guides», which opens the list of guides beside
    it."""

    #: How long the pointer rests on the name before the list opens (ms),
    #: as a menu's own submenus wait.
    HOVER_MS = 250
    #: Where the tick box and the name start (px from the row's left edge).
    BOX_LEFT = 6
    TEXT_LEFT = 28

    def __init__(self, viewport, menu, parent=None, views=None) -> None:
        super().__init__(parent)
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QActionGroup
        from PySide6.QtWidgets import QLabel, QMenu
        from views.composition_guides import GUIDES, guide_names
        self.viewport = viewport
        self.menu = menu
        #: Every view shown (a callable): «in all views» acts on them.
        self.views = views or (lambda: [viewport])
        self.setObjectName("composition_guides_row")
        self.setMouseTracking(True)
        row = QHBoxLayout(self)
        # The box sits in the column where the menu ticks its other
        # entries, so the name starts where theirs do.
        row.setContentsMargins(self.BOX_LEFT, 2, 10, 2)
        row.setSpacing(0)
        switch = self.switch = QCheckBox(self)
        switch.setObjectName("composition_guides_switch")
        switch.setFixedWidth(self.TEXT_LEFT - self.BOX_LEFT)
        switch.setToolTip(tr(
            "Show or hide the composition guides in the active view"))
        switch.setAccessibleName(tr("Composition Guides"))
        switch.toggled.connect(self._on_switch)
        row.addWidget(switch)
        self.label = QLabel(tr("Composition Guides"), self)
        row.addWidget(self.label, 1)
        self.arrow = QLabel("▸", self)
        row.addWidget(self.arrow)
        names = guide_names()
        sub = self.list_menu = QMenu(tr("Composition Guides"), self)
        group = QActionGroup(sub)
        group.setExclusive(True)
        self.guide_actions = {}
        for key in GUIDES[1:]:
            act = sub.addAction(names[key])
            act.setCheckable(True)
            act.setData(key)
            group.addAction(act)
            act.triggered.connect(lambda _c=False, k=key: self.choose(k))
            self.guide_actions[key] = act
        # With several views, each keeps its own guides; these two put
        # them on or off in all of them at once.
        sub.addSeparator()
        several = len(self.views()) > 1        # updated by sync()
        show_all = self.show_all_action = sub.addAction(
            tr("Show in all views"))
        show_all.setStatusTip(tr(
            "The composition guide chosen, in every view shown."))
        show_all.setEnabled(several)
        show_all.triggered.connect(lambda _c=False: self.set_all(True))
        hide_all = self.hide_all_action = sub.addAction(
            tr("Hide in all views"))
        hide_all.setStatusTip(tr(
            "No composition guides in any view shown."))
        hide_all.setEnabled(several)
        hide_all.triggered.connect(lambda _c=False: self.set_all(False))
        self._hover = QTimer(self)
        self._hover.setSingleShot(True)
        self._hover.setInterval(self.HOVER_MS)
        self._hover.timeout.connect(self.open_list)
        self.sync()

    def chosen(self) -> str:
        """The guide shown, or the one the switch would turn on."""
        from views.composition_guides import DEFAULT_GUIDES
        vp = self.viewport
        return (getattr(vp.camera, "composition_guide", None)
                or getattr(vp, "last_composition_guide", None)
                or DEFAULT_GUIDES)

    def sync(self) -> None:
        """The switch and the list show the active view's guide."""
        on = bool(getattr(self.viewport.camera, "composition_guide", None))
        self.switch.blockSignals(True)
        self.switch.setChecked(on)
        self.switch.blockSignals(False)
        act = self.guide_actions.get(self.chosen())
        if act is not None:
            act.setChecked(True)
        several = len(self.views()) > 1
        self.show_all_action.setEnabled(several)
        self.hide_all_action.setEnabled(several)

    def _on_switch(self, on: bool) -> None:
        self.viewport.toggle_composition_guide(bool(on))
        self.sync()

    def choose(self, key: str) -> None:
        """Show the guide ``key`` in the active view, and close the menu."""
        self.viewport.set_composition_guide(key)
        self.sync()
        self.menu.close()

    def set_all(self, on: bool) -> None:
        """The guide chosen in every view shown (on), or none in any (off);
        then close the menu."""
        key = self.chosen() if on else None
        for vp in self.views():
            vp.set_composition_guide(key)
        self.sync()
        self.menu.close()

    def open_list(self) -> None:
        """The list of guides, beside the row: on its right, or on its left
        when the window has no room there — never out of the window."""
        if self.list_menu.isVisible():
            return
        size = self.list_menu.sizeHint()
        right = self.mapToGlobal(QPoint(self.width(), 0))
        left = self.mapToGlobal(QPoint(-size.width(), 0))
        bounds = window_bounds(self.menu)
        at = right
        if bounds is not None and right.x() + size.width() > bounds.right() + 1:
            at = left
        self.list_menu.popup(keep_inside(at, size, bounds))

    def _over_switch(self, pos) -> bool:
        return self.switch.geometry().contains(pos)

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802 — Qt override
        if self._over_switch(ev.position().toPoint()):
            self._hover.stop()
        elif not self._hover.isActive() and not self.list_menu.isVisible():
            self._hover.start()
        super().mouseMoveEvent(ev)

    def leaveEvent(self, ev) -> None:  # noqa: N802 — Qt override
        self._hover.stop()
        super().leaveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802 — Qt override
        if ev.button() == Qt.LeftButton \
                and not self._over_switch(ev.position().toPoint()):
            self._hover.stop()
            self.open_list()
            return
        super().mouseReleaseEvent(ev)


def CompositionGuidesAction(viewport, menu, views=None):  # noqa: N802
    """The «Composition Guides» row as an entry of ``menu``; ``views``
    gives every view shown, for «Show/Hide in all views»."""
    from PySide6.QtWidgets import QWidgetAction
    act = QWidgetAction(menu)
    act.setText(tr("Composition Guides"))
    row = CompositionGuidesRow(viewport, menu, menu, views)
    act.setDefaultWidget(row)
    act.row = row
    return act
