# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A toolbar that, torn off, looks like a small window: a title strip on
top with the bar's name and a × at the right that closes it where it is
(2026-10-16: «que se vea más como una ventana, con la cruz arriba»).
Before, a floating bar could only be hidden again from the menu.
Docked, it is a plain toolbar: no strip, no ×.

It works on any ``QToolBar``, not a subclass: ``watch_toolbars(window)``
gives it to every toolbar the window has or gets later — the program's,
new ones, and a plugin's, which builds a plain ``QToolBar`` and adds it
to the window itself («que sea aplicable a futuras barras y plugins»).

Qt lays a toolbar's buttons out from its top-left corner whatever its
margins say — a top margin only makes the bar taller. So while floating
the bar keeps a top margin the height of the strip and, after each
layout pass, its buttons are moved down by that much.

The strip is a handle too («que permita acoplar también arrastrando desde
la barra de la ×»): it shows the move cursor and a drag on it is Qt's own
toolbar drag — the bar follows the mouse, the gap opens where it would
land, and it docks on release, as from the dotted grip. Qt starts that
drag only on a press inside the grip's rectangle, so the bar wears a
style that, for the one press the strip passes on, calls the whole bar
the grip; drawn, the grip stays where it was."""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel,
                               QProxyStyle, QSizePolicy, QStyle, QToolBar,
                               QToolButton, QWidget)

from core.i18n import tr

_SHIFT = QEvent.Type(QEvent.registerEventType())
_GRAB = "float_title_grab"      # set on the bar while the strip passes a press


class _GripStyle(QProxyStyle):
    """The application's style, except that while the strip hands a press
    to the bar, the bar's grip is the whole bar — so Qt starts its drag."""

    def subElementRect(self, element, option, widget=None):
        if (element == QStyle.SE_ToolBarHandle and widget is not None
                and widget.property(_GRAB)):
            return widget.rect()
        return super().subElementRect(element, option, widget)


class _TitleStrip(QWidget):
    """The strip itself: the bar's name and the ×. It is a grip: dragging
    it moves the floating bar and docks it, the way the dotted grip does."""

    def __init__(self, tb: QToolBar) -> None:
        super().__init__(tb)
        self.setObjectName("float_title_bar")
        self.setAutoFillBackground(True)
        self.setBackgroundRole(self.palette().ColorRole.Mid)
        self.setCursor(Qt.SizeAllCursor)
        self._tb = tb
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 0, 0)
        lay.setSpacing(4)
        self.label = QLabel(tb.windowTitle(), self)
        self.label.setObjectName("float_title_label")
        self.label.setMinimumWidth(0)
        lay.addWidget(self.label, 1)
        btn = self.close_button = QToolButton(self)
        btn.setObjectName("float_close_button")
        # «×» (Latin-1), not «✕» (Dingbats): every font has it, and a
        # character no font has sends Qt hunting for one (#658).
        btn.setText("×")
        btn.setToolTip(tr("Close this toolbar"))
        btn.setAutoRaise(True)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QToolButton { border: none; padding: 0 6px; }"
            "QToolButton:hover { background: #e81123; color: white; }")
        btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        btn.clicked.connect(tb.hide)
        lay.addWidget(btn)
        tb.windowTitleChanged.connect(self.label.setText)

    def _pass_on(self, e) -> None:
        """Hand the mouse event to the bar, at the same spot on it."""
        tb = self._tb
        local = self.mapTo(tb, e.position().toPoint())
        QApplication.sendEvent(tb, QMouseEvent(
            e.type(), local, e.globalPosition(), e.button(), e.buttons(),
            e.modifiers()))

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.LeftButton:
            super().mousePressEvent(e)
            return
        tb = self._tb
        tb.setProperty(_GRAB, True)
        try:
            self._pass_on(e)
        finally:
            tb.setProperty(_GRAB, False)
        e.accept()

    # Until Qt's drag takes the mouse, the moves still come here.
    def mouseMoveEvent(self, e) -> None:
        if e.buttons() & Qt.LeftButton:
            self._pass_on(e)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._pass_on(e)
            e.accept()
            return
        super().mouseReleaseEvent(e)


class _FloatingTitle(QObject):
    """Rides one toolbar: shows the strip while it floats and keeps its
    buttons under it."""

    def __init__(self, tb: QToolBar) -> None:
        super().__init__(tb)
        self.setObjectName("float_title")
        self.tb = tb
        self.height = 0
        self._pending = False
        self.strip = _TitleStrip(tb)
        self.strip.hide()
        # The application's style, wrapped (it is always Fusion here).
        self._style = _GripStyle(QApplication.style().name())
        self._style.setParent(self)
        tb.setStyle(self._style)
        tb.installEventFilter(self)
        tb.topLevelChanged.connect(self._on_floating)
        if tb.isFloating():
            self._on_floating(True)

    def _on_floating(self, floating: bool) -> None:
        tb = self.tb
        self.height = (tb.fontMetrics().height() + 8) if floating else 0
        tb.setContentsMargins(0, self.height, 0, 0)
        self.strip.setVisible(floating)
        if floating:
            tb.adjustSize()
            self._shift()

    def eventFilter(self, obj, e) -> bool:
        # A hidden bar put back in a dock (Restore default toolbars after
        # its × closed it) docks without topLevelChanged: ask again.
        if (e.type() in (QEvent.Show, QEvent.ParentChange)
                and bool(self.height) != self.tb.isFloating()):
            self._on_floating(self.tb.isFloating())
        # The layout runs right after this filter: move the buttons once
        # it is done (before the bar is painted — repaints queue last).
        if self.height and not self._pending and e.type() in (
                QEvent.Resize, QEvent.LayoutRequest, QEvent.Show):
            self._pending = True
            QCoreApplication.postEvent(self, QEvent(_SHIFT))
        return False

    def event(self, e) -> bool:
        if e.type() == _SHIFT:
            self._pending = False
            self._shift()
            return True
        return super().event(e)

    def _shift(self) -> None:
        """Lay the buttons out again, then move them under the strip."""
        tb, h = self.tb, self.height
        if not h:
            return
        lay = tb.layout()
        lay.setGeometry(tb.contentsRect())
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if w is not None:
                w.move(w.x(), w.y() + h)
        ext = tb.findChild(QToolButton, "qt_toolbar_ext_button")
        if ext is not None:
            ext.move(ext.x(), ext.y() + h)
        self.strip.setGeometry(0, 0, tb.width(), h)
        self.strip.raise_()


def add_floating_title(tb: QToolBar) -> None:
    """Give ``tb`` the title strip and × for when it floats (once)."""
    if tb.findChild(_FloatingTitle, "float_title") is None:
        _FloatingTitle(tb)


class _ToolbarWatcher(QObject):
    # ChildPolished, not ChildAdded: a child is announced mid-construction,
    # before it is a toolbar; it is polished whole, before it first shows —
    # and a bar must show to float.
    def eventFilter(self, obj, e) -> bool:
        if e.type() == QEvent.ChildPolished:
            child = e.child()
            if isinstance(child, QToolBar):
                add_floating_title(child)
        return False


def watch_toolbars(window: QWidget) -> None:
    """Every toolbar ``window`` has, and every one it gets later — the
    program's own or a plugin's — floats as a small window."""
    for tb in window.findChildren(QToolBar):
        add_floating_title(tb)
    watcher = _ToolbarWatcher(window)
    watcher.setObjectName("toolbar_watcher")
    window.installEventFilter(watcher)
