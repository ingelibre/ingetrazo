"""Shortcuts that outlive a hidden workspace (Ctrl+0, clean screen).

A QAction's shortcut only fires while one of the widgets it was added to
is visible. Clean screen hides every toolbar and the menu bar, so the
tools' single keys (L, R, M…) and every other command reachable only
from a bar or a menu stopped answering — the model was there, and
nothing could be drawn on it.

While clean screen is on, every action with a shortcut that lives on a
toolbar or in a menu of the window is added to the window itself, which
stays visible; on the way out they are taken off again. Bars and menus
added by plugins, or later on, are picked up the same way: nothing here
lists actions by name.

Two live actions on one key cancel each other out in Qt (an «ambiguous»
shortcut fires neither), so a key that something still visible already
answers to — the window's own actions, the viewport's — is left alone,
and of two hidden actions on one key only the first is carried over:
the toolbars' before the menu bar's, those before any other menu
(context menus kept for later).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QDockWidget, QMenu, QMenuBar,
                               QToolBar, QWidget)


def _holders(window: QWidget) -> list:
    """The bars and menus whose actions go dark with clean screen, in the
    order their keys are claimed."""
    bars = window.findChildren(QToolBar)
    menu_bar = window.findChild(QMenuBar)
    main_menus = menu_bar.findChildren(QMenu) if menu_bar is not None else []
    seen = set(map(id, main_menus))
    others = [m for m in window.findChildren(QMenu) if id(m) not in seen]
    return [*bars, *main_menus, *others]


def _keys(act) -> list[str]:
    return [s.toString() for s in act.shortcuts() if not s.isEmpty()]


_DARK = (QToolBar, QMenu, QMenuBar, QDockWidget)


def _goes_dark(w: QWidget, window: QWidget) -> bool:
    """Whether clean screen hides ``w``: it is, or sits inside, a bar, a
    menu or a dock (a bar's buttons carry their actions too)."""
    while w is not None and w is not window:
        if isinstance(w, _DARK):
            return True
        w = w.parentWidget()
    return False


def _taken_keys(window: QWidget) -> set[str]:
    """Keys something that stays in sight answers to already."""
    taken: set[str] = set()
    for w in [window, *window.findChildren(QWidget)]:
        if _goes_dark(w, window):
            continue
        for act in w.actions():
            taken.update(_keys(act))
    return taken


def keep_shortcuts_alive(window: QWidget) -> list:
    """Add to ``window`` the bar and menu actions with a shortcut it does
    not carry yet, and return them so :func:`release_shortcuts` can take
    them off."""
    own = set(map(id, window.actions()))
    taken = _taken_keys(window)
    added, seen = [], set()
    for holder in _holders(window):
        for act in holder.actions():
            if act.isSeparator() or id(act) in seen or id(act) in own:
                continue
            seen.add(id(act))
            keys = _keys(act)
            if not keys or any(k in taken for k in keys):
                continue
            taken.update(keys)
            added.append(act)
    window.addActions(added)
    return added


def release_shortcuts(window: QWidget, added) -> None:
    """Take off the window the actions :func:`keep_shortcuts_alive` put
    there; the ones the window had of its own stay."""
    for act in added or ():
        try:
            window.removeAction(act)
        except RuntimeError:        # a plugin's action, gone meanwhile
            pass


class ExitButtonFader(QObject):
    """The «Exit clean screen» button steps aside after a few seconds, so
    nothing but the model is left on screen, and comes back while the
    mouse is near its corner (top right of ``area``) — the way out stays
    findable for whoever does not know Ctrl+0."""

    #: How long the button stays after clean screen starts, or after the
    #: mouse has left its corner (ms).
    HIDE_MS = 3000
    #: The corner that brings it back, measured from the area's top-right.
    CORNER_W = 260
    CORNER_H = 110

    #: The button came back (the window places it again).
    shown = Signal()

    def __init__(self, button: QWidget, area: QWidget) -> None:
        super().__init__(button)
        self._button = button
        self._area = area
        self._active = False
        self._last_pos = None             # where the mouse last moved to
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.HIDE_MS)
        self._timer.timeout.connect(self._fade)

    def start(self) -> None:
        """Clean screen on: the button shows, and goes in HIDE_MS."""
        self._active = True
        self._last_pos = None
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
            app.installEventFilter(self)
        self._button.show()
        self._timer.start()

    def stop(self) -> None:
        """Clean screen off: no more watching the mouse."""
        self._active = False
        self._timer.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._button.hide()

    def _near_corner(self, global_pos) -> bool:
        area = self._area
        if global_pos is None or area is None or not area.isVisible():
            return False
        p = area.mapFromGlobal(global_pos)
        return (area.width() - self.CORNER_W <= p.x() <= area.width()
                and 0 <= p.y() <= self.CORNER_H)

    def _fade(self) -> None:
        if not self._active:
            return
        if self._near_corner(self._last_pos):
            self._timer.start()           # still there: wait for it to go
            return
        self._button.hide()

    def eventFilter(self, obj, event):  # noqa: N802 — Qt override
        if self._active and event.type() == QEvent.MouseMove:
            self._last_pos = event.globalPosition().toPoint()
            if self._near_corner(self._last_pos):
                if not self._button.isVisible():
                    self._button.show()
                    self.shown.emit()
                self._timer.start()
        return False
