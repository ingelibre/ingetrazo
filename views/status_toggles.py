# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""On/off switches in the status bar (#780).

A row of small buttons at the bottom of the window, next to the
measurements box, each one a checkable ``QAction`` that already lives in a
menu: the button shows the action's state (pressed while on), a click
toggles it and the action's shortcut and status tip come with it. A
button may carry a drop-down (``menu``) and a right-click menu
(``context``). Adding a switch is one :meth:`StatusToggles.add` call.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QMenu, QToolButton, QWidget


class StatusToggles(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("status_toggles")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(2)
        self._buttons: dict = {}

    def add(self, key: str, action, menu: QMenu | None = None,
            context: QMenu | None = None,
            popup: bool = False) -> QToolButton:
        """A button for ``action``. With ``popup`` a click opens ``menu``
        (the button only shows the action's state); without it the menu
        drops from the button's arrow."""
        button = QToolButton(self)
        button.setObjectName(f"status_toggle_{key}")
        button.setDefaultAction(action)
        # The icon alone, as the toolbars show theirs; the name, keys and
        # what it does are in the tooltip (``views.shortcuts.set_tooltip``).
        button.setToolButtonStyle(Qt.ToolButtonIconOnly
                                  if not action.icon().isNull()
                                  else Qt.ToolButtonTextOnly)
        button.setIconSize(QSize(18, 18))
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.NoFocus)
        if menu is not None:
            button.setMenu(menu)
            button.setPopupMode(QToolButton.InstantPopup if popup
                                else QToolButton.MenuButtonPopup)
        if context is not None:
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda pos, b=button, m=context: m.exec(b.mapToGlobal(pos)))
        self.layout().addWidget(button)
        self._buttons[key] = button
        return button

    def button(self, key: str) -> QToolButton | None:
        return self._buttons.get(key)

    def keys(self) -> list:
        return list(self._buttons)
