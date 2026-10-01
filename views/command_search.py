# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Command search: type a few letters, press Enter, the command runs.

Blender's F3 menu search, Rhino's command line: a
single box that filters every action the window already has — menus,
tools, trays, plugins — so nobody has to remember in which menu «Orient
Faces» lives. Nothing is registered twice: the list is the window's own
``QAction`` objects (the same :func:`views.shortcuts.collect_actions` the
shortcut editor lists), read each time the box opens, so a plugin loaded a
minute ago is already in it.

The matching is Blender's (:mod:`core.string_search`): word beginnings,
initials («rf» → Reverse Faces), a typing error or two, in the language
of the menus AND in English (a tutorial says «Push/Pull», the menu says
«Empujar/Tirar»), by menu path too, accents and case aside. As in Blender,
the path is drawn faded, a right click offers to change the command's
shortcut, and typing a letter in an open menu searches that menu.
"""
from __future__ import annotations

import html
import re

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QObject,
                            QPoint, QRect, QSettings, QSize, Qt, QTimer)
from PySide6.QtGui import (QAction, QColor, QCursor, QGuiApplication, QIcon,
                           QKeySequence, QPalette)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListView, QMainWindow, QMenu,
                               QMenuBar, QStyle, QToolBar,
                               QStyledItemDelegate, QStyleOptionViewItem,
                               QVBoxLayout)

from core import string_search
from core.i18n import source_of, tr
from views.shortcuts import _plain, action_key, collect_actions

#: The command that opens this box — kept out of its own list.
OBJECT_NAME = "command_search"
_RECENT_KEY = "command_search/recent"
_RECENT_MAX = 100
_SEP = " ▸ "


def _label(action: QAction) -> str:
    """The menu text without its mnemonic «&» — the «…» stays: it says
    the command asks something before doing it."""
    return action.text().replace("&&", "\0").replace("&", "") \
        .replace("\0", "&").strip()


_TRAILING = re.compile(r"\s*\(([^()]+)\)\s*$")


def _keys_in(text: str):
    """The shortcut a label carries at its end — «Ungroup (Ctrl+Shift+G)»
    — as a QKeySequence, or ``None`` when the brackets say something else
    («Português (Brasil)», «AI Bridge (MCP)»)."""
    m = _TRAILING.search(text)
    if m is None:
        return None
    inner = m.group(1).strip()
    seq = QKeySequence.fromString(inner, QKeySequence.PortableText)
    if seq.isEmpty() or seq[0].key() == Qt.Key_unknown:
        return None
    same = seq.toString(QKeySequence.PortableText).replace(" ", "").lower()
    return seq if same == inner.replace(" ", "").lower() else None


def _without_keys(text: str) -> str:
    return _TRAILING.sub("", text).strip()


def _menubar(window):
    """The window's menu bar, or ``None`` — never made by asking (the
    composer has none, and ``menuBar()`` would give it an empty one)."""
    bar = window.menuWidget()
    return bar if isinstance(bar, QMenuBar) else None


def _submenus(window) -> dict:
    """``{action: menu}`` for every menu of the window, found from the
    menus (``menuAction``) rather than asked of each action: with PySide
    6.11.1, ``QAction.menu()`` on a menu whose wrapper did not exist yet
    handed back a dead wrapper for the Help menu (seen on one machine;
    every window then failed to build)."""
    return {m.menuAction(): m for m in window.findChildren(QMenu)}


def _top_menus(window, subs: dict | None = None) -> list:
    bar = _menubar(window)
    if bar is None:
        return []
    if subs is None:
        subs = _submenus(window)
    return [subs[a] for a in bar.actions() if a in subs]


def menu_paths(window) -> dict:
    """``{action_key: "Edit ▸ Unhide"}`` for the actions in the menu bar;
    an action found only on a toolbar gets the toolbar's name («Draw»)."""
    paths: dict = {}
    subs = _submenus(window)

    def walk(menu: QMenu, trail: list) -> None:
        for act in menu.actions():
            sub = subs.get(act)
            if sub is not None:
                walk(sub, trail + [_plain(sub.title())])
            elif not act.isSeparator() and _plain(act.text()):
                paths.setdefault(action_key(act), _SEP.join(trail))

    for menu in _top_menus(window, subs):
        walk(menu, [_plain(menu.title())])
    for bar in window.findChildren(QToolBar):
        if bar.window() is not window:
            continue
        paths.setdefault(action_key(bar.toggleViewAction()), tr("Toolbars"))
        for act in bar.actions():
            if not act.isSeparator() and _plain(act.text()):
                paths.setdefault(action_key(act), _plain(bar.windowTitle()))
    return paths


def menu_trail(window, menu: QMenu):
    """``"Edit ▸ Unhide"`` for a menu of the menu bar, ``None`` for any
    other (a right-click menu)."""
    subs = _submenus(window)

    def walk(parent: QMenu, trail: list):
        if parent is menu:
            return _SEP.join(trail)
        for act in parent.actions():
            sub = subs.get(act)
            if sub is not None:
                found = walk(sub, trail + [_plain(sub.title())])
                if found is not None:
                    return found
        return None

    for top in _top_menus(window):
        found = walk(top, [_plain(top.title())])
        if found is not None:
            return found
    return None


def _belongs(action: QAction, window) -> bool:
    """Is ``action`` the window's own? The sheet composer is a child of
    the main window: its commands must not show in the main window's F3
    (nor the main window's in the composer's)."""
    obj = action.parent()
    while obj is not None:
        if obj is window:
            return True
        if isinstance(obj, QMainWindow):
            return False                       # another window's
        obj = obj.parent()
    return False


def recent_keys() -> list:
    value = QSettings().value(_RECENT_KEY) or []
    return [str(v) for v in ([value] if isinstance(value, str) else value)]


def remember(act: QAction) -> None:
    key = action_key(act)
    keys = [key] + [k for k in recent_keys() if k != key]
    QSettings().setValue(_RECENT_KEY, keys[:_RECENT_MAX])


class Command:
    """One row: the action, its words in both languages, its menu path,
    its explanation. Worked out once, when the box opens — not per key."""

    __slots__ = ("action", "key", "name", "path", "keys", "tip", "items")

    def __init__(self, action: QAction, path: str) -> None:
        self.action = action
        self.key = action_key(action)
        english = _plain(source_of(action.text()))
        name = _label(action)
        keys = action.shortcut()
        in_text = _keys_in(english)
        if in_text is not None:
            # «Ungroup (Ctrl+Shift+G)»: the keys go to their column.
            name, english = _without_keys(name), _without_keys(english)
            keys = keys if not keys.isEmpty() else in_text
        self.name = name
        self.path = path
        self.keys = keys.toString(QKeySequence.NativeText)
        trail = path.split(_SEP) if path else []
        self.items = (
            string_search.Item(trail + [name]),
            string_search.Item([source_of(p) for p in trail] + [english]))
        self.tip = _description(action, name)


def _description(action: QAction, name: str) -> str:
    """What the command does, from its tooltip or status tip — without
    the name and the keys a tooltip often repeats («Line  (L)», «3D Text
    — build extruded text as a solid»). Empty when that is all it says."""
    tip = (action.statusTip() or action.toolTip() or "").strip()
    if _keys_in(source_of(tip)) is not None or _keys_in(tip) is not None:
        tip = _without_keys(tip)
    fold = string_search.fold
    bare = _plain(name)
    if fold(tip).startswith(fold(bare)):
        # Only a name that stands apart — «Orbit (O) — left-drag…» — is
        # taken off; «Pan the sheet…» is a sentence and stays whole.
        m = _LEAD.match(tip[len(bare):])
        if m is not None:
            rest = tip[len(bare) + m.end():]
            tip = rest[:1].upper() + rest[1:]
    return "" if fold(_plain(tip)) == fold(bare) else tip


#: What may follow a name a tooltip repeats: its keys, then a dash or a
#: colon — or nothing at all.
_LEAD = re.compile(r"\s*(\([^()]*\))?\s*([—–:\-]\s*|$)")


def tooltip_html(cmd: Command) -> str:
    """Blender's tooltip: the name in bold, what it does, the keys —
    wrapped to a readable width, never cut."""
    parts = [f"<b>{html.escape(cmd.name)}</b>"]
    if cmd.tip:
        parts.append(html.escape(cmd.tip))
    if cmd.keys:
        parts.append("<span style='color:gray'>" + html.escape(
            tr("Shortcut: {keys}", keys=cmd.keys)) + "</span>")
    body = "<br>".join(parts)
    if len(cmd.tip) > 60:
        body = f"<table width='{_TIP_WIDTH}'><tr><td>{body}</td></tr></table>"
    return "<qt>" + body + "</qt>"


_TIP_WIDTH = 380


def _signature(action: QAction, path: str) -> tuple:
    """What a Command is worked out from: when none of it changed, the
    one made at the last opening still holds."""
    return (action.objectName(), action.text(), action.toolTip(),
            action.statusTip(),
            action.shortcut().toString(QKeySequence.PortableText), path)


def commands(window, scope: str = "") -> list:
    """Every command the box can offer, in the window as it is now; only
    those under the menu ``scope`` («Edit ▸ Unhide») when given.

    The list is read afresh each time — a plugin loaded a minute ago is
    in it — but a command whose text, tips, keys and path are unchanged
    reuses what the last opening worked out: splitting ~200 labels in
    two languages took most of the ~100 ms F3 needed to appear."""
    paths = menu_paths(window)
    cache = getattr(window, "_command_cache", None) or {}
    fresh: dict = {}
    pool = []
    for a in collect_actions(window):
        if a.objectName() == OBJECT_NAME or not a.isVisible() \
                or not _belongs(a, window):
            continue
        path = paths.get(action_key(a), "")
        sig = _signature(a, path)
        hit = cache.get(a)
        cmd = hit[1] if hit is not None and hit[0] == sig else Command(a, path)
        fresh[a] = (sig, cmd)
        pool.append(cmd)
    window._command_cache = fresh            # only the actions alive now
    if scope:
        pool = [c for c in pool
                if c.path == scope or c.path.startswith(scope + _SEP)]
    return pool


def search(window, query: str, pool=None, recent=None) -> list:
    """The commands matching ``query``, best first. With one letter typed
    or none, the recent ones lead; an empty query lists them all."""
    pool = commands(window) if pool is None else pool
    if recent is None:
        keys = recent_keys()
        recent = {k: len(keys) - i for i, k in enumerate(keys)}
    return string_search.rank(query, [(c, c.items) for c in pool],
                              recent=lambda c: recent.get(c.key, -1))


_PATH_ROLE = Qt.UserRole + 1
_KEYS_ROLE = Qt.UserRole + 2
#: Rows shown at once, as Blender's box (SEARCH_ITEMS); the rest scroll.
VISIBLE_ROWS = 10
_ICON = 16


BOX_WIDTH = 560


def _clamp_axis(pos: int, size: int, lo: int, hi: int,
                far_lo: int, far_hi: int) -> int:
    """Where a box of ``size`` starting near ``pos`` goes on one axis:
    inside ``lo..hi`` when it fits there, else inside ``far_lo..far_hi``."""
    if size > hi - lo:
        lo, hi = far_lo, far_hi
    return max(lo, min(pos, hi - size))


def fit_box(cursor: QPoint, size: QSize, edit_h: int, work: QRect,
            screen: QRect) -> QRect:
    """The box's place: its text field under ``cursor``, as Blender's, but
    never over the side trays or the toolbars (Marco: «siempre se vea en
    el espacio de modelado»). Each axis on its own:

    1. inside the modelling area ``work`` when the box fits in it;
    2. otherwise over its edge — the trays — keeping its size, inside the
       ``screen``;
    3. smaller only when not even the screen holds it (the rows scroll)."""
    width = min(size.width(), screen.width())
    height = min(size.height(), screen.height())
    x = _clamp_axis(cursor.x() - width // 2, width,
                    work.left(), work.left() + work.width(),
                    screen.left(), screen.left() + screen.width())
    y = _clamp_axis(cursor.y() - edit_h // 2, height,
                    work.top(), work.top() + work.height(),
                    screen.top(), screen.top() + screen.height())
    return QRect(x, y, width, height)


class _Results(QAbstractListModel):
    """The matches, drawn on demand: a keystroke resets a list, and only
    the rows on screen are ever asked for their text and icon."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: list = []

    def set_rows(self, rows: list) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def flags(self, index):
        if self.rows[index.row()].action.isEnabled():
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return Qt.NoItemFlags                  # shown, greyed, never run

    def data(self, index, role=Qt.DisplayRole):
        cmd = self.rows[index.row()]
        act = cmd.action
        if role == Qt.DisplayRole:
            checked = act.isCheckable() and act.isChecked()
            return ("✓ " if checked else "") + cmd.name
        if role == Qt.DecorationRole:
            return act.icon()
        if role == _PATH_ROLE:
            return cmd.path
        if role == _KEYS_ROLE:
            return cmd.keys
        if role == Qt.ToolTipRole:
            return tooltip_html(cmd)
        return None


class _RowDelegate(QStyledItemDelegate):
    """One line per command, as Blender draws its search: the menu path
    faded, «▸», the icon, the name in full colour, the keys at the right.
    The path gives way (cut from the left) before the name does."""

    def paint(self, painter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        # A copy: PySide hands out the option's own icon, which the reset
        # below would blank.
        name, icon = opt.text, QIcon(opt.icon)
        opt.text, opt.icon = "", QIcon()
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)

        pal = opt.palette
        selected = bool(opt.state & QStyle.State_Selected)
        enabled = bool(opt.state & QStyle.State_Enabled)
        if not enabled:
            main = pal.color(QPalette.Disabled, QPalette.Text)
        else:
            main = pal.color(QPalette.HighlightedText if selected
                             else QPalette.Text)
        faded = QColor(main)
        faded.setAlphaF(0.55 if enabled else 0.35)
        fm = opt.fontMetrics
        rect = opt.rect.adjusted(6, 0, -6, 0)
        mid = rect.center().y()

        painter.save()
        painter.setPen(faded)
        keys = index.data(_KEYS_ROLE) or ""
        if keys:
            painter.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, keys)
            rect.setRight(rect.right() - fm.horizontalAdvance(keys) - 12)
        path = index.data(_PATH_ROLE) or ""
        icon_w = _ICON + 4 if not icon.isNull() else 0
        x = rect.left()
        if path:
            room = rect.width() - fm.horizontalAdvance(name) - icon_w
            text = fm.elidedText(path + " ▸ ", Qt.ElideLeft, max(room, 0))
            painter.drawText(x, rect.top(), rect.width(), rect.height(),
                             Qt.AlignLeft | Qt.AlignVCenter, text)
            x += fm.horizontalAdvance(text)
        if icon_w:
            mode = QIcon.Normal if enabled else QIcon.Disabled
            icon.paint(painter, x, mid - _ICON // 2, _ICON, _ICON,
                       Qt.AlignCenter, mode)
            x += icon_w
        painter.setPen(main)
        width = max(rect.right() - x, 0)
        painter.drawText(x, rect.top(), width, rect.height(),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         fm.elidedText(name, Qt.ElideRight, width))
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(),
                     max(option.fontMetrics.height(), _ICON) + 6)


class CommandSearch(QFrame):
    """The box itself: a compact popup at the mouse, as Blender's. Type to
    filter, arrows to move, Enter to run, Esc (or a click outside) to
    leave; a right click on a row offers to change its shortcut."""

    def __init__(self, window) -> None:
        super().__init__(window, Qt.Popup)
        self._window = window
        self.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self._scope_label = QLabel()
        self._scope_label.hide()
        top.addWidget(self._scope_label)
        self._edit = QLineEdit()
        self._edit.setPlaceholderText(tr("Search a command…"))
        self._edit.setClearButtonEnabled(True)
        from views.icons import tool_icon
        self._edit.addAction(tool_icon("zoom"), QLineEdit.LeadingPosition)
        self._edit.textChanged.connect(self._refill)
        self._edit.installEventFilter(self)
        top.addWidget(self._edit, 1)
        lay.addLayout(top)
        self._model = _Results(self)
        self._list = QListView()
        self._list.setModel(self._model)
        self._list.setItemDelegate(_RowDelegate(self._list))
        self._list.setUniformItemSizes(True)
        self._list.setFrameShape(QFrame.NoFrame)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setFocusPolicy(Qt.NoFocus)   # the typing stays in the box
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        self._list.activated.connect(self._run)
        self._list.clicked.connect(self._run)
        lay.addWidget(self._list, 1)
        self._empty = QLabel(tr("No results found"))
        self._empty.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._empty.setContentsMargins(8, 4, 8, 4)
        self._empty.setEnabled(False)          # faded, as Blender's
        self._empty.hide()
        lay.addWidget(self._empty, 1)
        self._pool: list = []
        self._recent: dict = {}
        self._scope = ""

    # ---- showing ----------------------------------------------------------------
    def _place(self) -> None:
        """Ten rows high, the text field under the mouse pointer — where
        Blender opens it — but inside the modelling area (see fit_box)."""
        row = max(self.fontMetrics().height(), _ICON) + 6
        edit_h = self._edit.sizeHint().height()
        size = QSize(BOX_WIDTH, edit_h + row * VISIBLE_ROWS + 10)
        cursor = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor) or self._window.screen()
        area = getattr(self._window, "command_search_area", None)
        work = area() if callable(area) else self._window.centralWidget()
        work_rect = QRect(work.mapToGlobal(QPoint(0, 0)), work.size())
        self.setGeometry(fit_box(cursor, size, edit_h, work_rect,
                                 screen.availableGeometry()))

    def popup(self, text: str = "", scope: str = "") -> None:
        self._place()
        self._set_scope(scope)
        keys = recent_keys()
        self._recent = {k: len(keys) - i for i, k in enumerate(keys)}
        # The list never has the focus, so it is never "active": paint its
        # current row as if it were, or the row Enter would run is barely
        # told apart. Taken on each opening — the theme may have changed.
        pal = QApplication.palette(self._list)
        for role in (QPalette.Highlight, QPalette.HighlightedText):
            pal.setColor(QPalette.Inactive, role,
                         pal.color(QPalette.Active, role))
        self._list.setPalette(pal)
        self._edit.blockSignals(True)
        self._edit.setText(text)
        self._edit.blockSignals(False)
        self._refill(text)
        self.show()
        self.raise_()
        self._edit.setFocus(Qt.PopupFocusReason)

    def _set_scope(self, scope: str) -> None:
        """Search only under one menu (typed in it), or everywhere."""
        self._scope = scope
        self._pool = commands(self._window, scope)  # plugins come and go
        self._scope_label.setText(scope + " ▸")
        self._scope_label.setToolTip(
            tr("Backspace in the empty box searches everywhere"))
        self._scope_label.setVisible(bool(scope))

    def _refill(self, text: str) -> None:
        rows = search(self._window, text, self._pool, self._recent)
        self._model.set_rows(rows)
        self._list.setVisible(bool(rows))
        self._empty.setVisible(not rows)
        self._select(self._first_enabled(0, 1))

    def _first_enabled(self, start: int, step: int) -> int:
        rows = self._model.rows
        i = start
        while 0 <= i < len(rows):
            if rows[i].action.isEnabled():
                return i
            i += step
        return -1

    def _select(self, row: int) -> None:
        if row < 0:
            self._list.setCurrentIndex(QModelIndex())
            return
        index = self._model.index(row, 0)
        self._list.setCurrentIndex(index)
        self._list.scrollTo(index)

    # ---- keys ---------------------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:
        if obj is self._edit and event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown,
                       Qt.Key_PageUp):
                self._move(key)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._run(self._list.currentIndex())
                return True
            if key == Qt.Key_Escape:
                self.close()
                return True
            if key == Qt.Key_Backspace and self._scope \
                    and not self._edit.text():
                self._set_scope("")
                self._refill("")
                return True
        return super().eventFilter(obj, event)

    def _move(self, key) -> None:
        cur = self._list.currentIndex()
        i = cur.row() if cur.isValid() else -1
        step = 1 if key in (Qt.Key_Down, Qt.Key_PageDown) else -1
        jump = 10 if key in (Qt.Key_PageDown, Qt.Key_PageUp) else 1
        n = len(self._model.rows)
        target = max(0, min(n - 1, i + step * jump))
        row = self._first_enabled(target, step)
        if row < 0:
            row = self._first_enabled(target, -step)
        if row >= 0:
            self._select(row)

    # ---- running --------------------------------------------------------------------
    def _action_at(self, index):
        if not index.isValid() or index.row() >= len(self._model.rows):
            return None
        return self._model.rows[index.row()].action

    def _run(self, index) -> None:
        act = self._action_at(index)
        if act is None or not act.isEnabled():
            return
        self.close()
        remember(act)
        # After the popup is gone: a command that opens a dialog must not
        # find this popup still grabbing the keyboard.
        QTimer.singleShot(0, act.trigger)

    def _context_menu(self, pos) -> None:
        act = self._action_at(self._list.indexAt(pos))
        if act is None:
            return
        if self._preferences_owner() is None:
            return
        menu = QMenu(self)
        change = menu.addAction(tr("Change shortcut…"))
        if menu.exec(self._list.viewport().mapToGlobal(pos)) is change:
            self.change_shortcut(act)

    def change_shortcut(self, act: QAction) -> None:
        """Preferences on this command's shortcut (Blender's right click
        ▸ Change Shortcut)."""
        owner = self._preferences_owner()
        self.close()
        if owner is not None:
            QTimer.singleShot(
                0, lambda: owner.open_preferences(shortcut_of=act))

    def _preferences_owner(self):
        """The window whose Preferences hold the shortcuts: this one, or
        the main window the composer belongs to."""
        w = self._window
        while w is not None and not hasattr(w, "open_preferences"):
            w = w.parentWidget()
        return w


def warm_up(window, delay_ms: int = 2000) -> None:
    """Work out F3's command list while the window idles after opening,
    so even the first F3 shows its list at once.

    Only the list — pure Python. The box and its native popup are made on
    the first F3, as they always were up to 0.5.6.1: made ahead, the popup
    left the main window flickering under GNOME's Wayland, a black band
    and the toolbar drawn half over the menu bar (Marco, 30-09, bisected
    to ``box.winId()`` here; it only shows with two monitors, when
    IngeTrazo runs on Wayland). Kept off on every platform until it has
    been tried on each."""
    def ready() -> None:
        commands(window)
    QTimer.singleShot(delay_ms, window, ready)


def open_search(window, text: str = "", scope: str = "") -> CommandSearch:
    """Show the window's search box (made once, kept)."""
    box = getattr(window, "_command_search", None)
    if box is None:
        box = window._command_search = CommandSearch(window)
    box.popup(text, scope)
    return box


class _MenuTyping(QObject):
    """Blender 4's type-to-search: a letter pressed in an open menu of the
    menu bar closes it and searches that menu, the letter already typed.
    The menus carry no «&» mnemonics, so no letter meant anything there."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window

    def watch(self, menu: QMenu, subs: dict | None = None) -> None:
        if subs is None:
            subs = _submenus(self._window)
        menu.installEventFilter(self)          # once: Qt drops repeats
        for act in menu.actions():
            sub = subs.get(act)
            if sub is not None:
                self.watch(sub, subs)

    def eventFilter(self, menu, event) -> bool:
        if event.type() != event.Type.KeyPress or not isinstance(menu, QMenu):
            return False
        text = event.text()
        mods = event.modifiers() & ~(Qt.ShiftModifier | Qt.KeypadModifier)
        if len(text) != 1 or not text.isprintable() or text.isspace() \
                or mods != Qt.NoModifier:
            return False
        scope = menu_trail(self._window, menu)
        if scope is None:
            return False
        for _ in range(16):                    # the menu and its parents
            popup = QApplication.activePopupWidget()
            if popup is None:
                break
            popup.close()
        QTimer.singleShot(0, lambda: open_search(self._window, text, scope))
        return True


def install_menu_typing(window) -> None:
    """Watch every menu of the menu bar — and, as each opens, the submenus
    a plugin or a rebuild may have added since."""
    typing = _MenuTyping(window)
    for menu in _top_menus(window):
        typing.watch(menu)
        menu.aboutToShow.connect(lambda m=menu: typing.watch(m))
    window._menu_typing = typing
    warm_up(window)
