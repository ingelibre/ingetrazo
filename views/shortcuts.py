# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Keyboard shortcuts of one's own (issue #138, @pacaeiro: «right now
there's no way to configure our own shortcuts»).

Every action of the main window — menus and tools — can take the keys the
user wants. They are remembered per action in QSettings (``shortcuts/<key>``)
and put back at start-up over the factory ones. The key of an action is its
object name or, failing that, its ENGLISH text: the menus are translated, and
a shortcut set in Spanish must survive a switch to Portuguese.

Two actions must never hold the same keys: Qt then fires neither («Ambiguous
shortcut overload», tests/test_shortcuts.py). The dialog takes the keys away
from the action that had them, after asking.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QKeySequenceEdit,
                               QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from core.i18n import source_of, tr

_GROUP = "shortcuts"
_DEFAULTS = "ingetrazo_default_shortcuts"


def _plain(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&") \
        .rstrip("…").rstrip(".").strip()


def action_key(action: QAction) -> str:
    name = action.objectName()
    if name:
        return name
    return "text:" + _plain(source_of(action.text()))


def collect_actions(window) -> list:
    """The window's actions a user can press: with text, not a separator,
    not a submenu, one per key (the first wins)."""
    seen: dict = {}
    for act in window.findChildren(QAction):
        if act.isSeparator() or act.menu() is not None:
            continue
        if not _plain(act.text()):
            continue
        seen.setdefault(action_key(act), act)
    return sorted(seen.values(), key=lambda a: _plain(a.text()).lower())


def _to_text(seqs) -> str:
    return "; ".join(s.toString(QKeySequence.PortableText) for s in seqs
                     if not s.isEmpty())


def _from_text(text: str) -> list:
    return [QKeySequence.fromString(t.strip(), QKeySequence.PortableText)
            for t in (text or "").split(";") if t.strip()]


def remember_defaults(window) -> None:
    """Note each action's factory keys (before the user's go on)."""
    for act in collect_actions(window):
        if act.property(_DEFAULTS) is None:
            act.setProperty(_DEFAULTS, _to_text(act.shortcuts()))


def default_shortcuts(action: QAction) -> list:
    return _from_text(action.property(_DEFAULTS) or "")


def apply_user_shortcuts(window) -> int:
    """Put the remembered keys on the window's actions. Returns how many."""
    st = QSettings()
    st.beginGroup(_GROUP)
    saved = {k: str(st.value(k) or "") for k in st.childKeys()}
    st.endGroup()
    n = 0
    for act in collect_actions(window):
        key = action_key(act)
        if key in saved:
            act.setShortcuts(_from_text(saved[key]))
            n += 1
    return n


def save_shortcut(action: QAction, seqs: list) -> None:
    st = QSettings()
    key = action_key(action)
    if _to_text(seqs) == (action.property(_DEFAULTS) or ""):
        st.remove(f"{_GROUP}/{key}")           # back to the factory keys
    else:
        st.setValue(f"{_GROUP}/{key}", _to_text(seqs))
    st.sync()


class ShortcutsPanel(QWidget):
    """Preferences ▸ Keyboard shortcuts (Marco, 26-09: «deberían estar
    dentro de preferencias»): every action, its keys, a search box; pick a
    row and press the new keys. Changes apply at once and are remembered."""

    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self._window = window
        lay = QVBoxLayout(self)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText(tr("Search an action or a key…"))
        self._filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self._filter)
        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels([tr("Action"), tr("Shortcut")])
        self._tree.setRootIsDecorated(False)
        self._tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tree.header().setSectionResizeMode(
            1, QHeaderView.ResizeToContents)
        self._tree.currentItemChanged.connect(self._on_row)
        lay.addWidget(self._tree, 1)
        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel(tr("New shortcut:")))
        self._edit = QKeySequenceEdit()
        self._edit.setMaximumSequenceLength(1)
        self._edit.editingFinished.connect(self._on_keys)
        edit_row.addWidget(self._edit, 1)
        clear = QPushButton(tr("Clear"))
        clear.clicked.connect(self._on_clear)
        edit_row.addWidget(clear)
        reset = QPushButton(tr("Default"))
        reset.setToolTip(tr("Back to this action's factory shortcut"))
        reset.clicked.connect(self._on_reset)
        edit_row.addWidget(reset)
        lay.addLayout(edit_row)
        foot = QHBoxLayout()
        hint = QLabel(tr("Pick an action, click the box and press the keys. "
                         "Changes apply at once and are remembered."))
        hint.setWordWrap(True)
        foot.addWidget(hint, 1)
        reset_all = QPushButton(tr("Restore all defaults"))
        reset_all.clicked.connect(self._on_reset_all)
        foot.addWidget(reset_all)
        lay.addLayout(foot)
        self._actions = collect_actions(window)
        self._fill()

    # ---- list -----------------------------------------------------------------
    def _fill(self) -> None:
        self._tree.clear()
        for act in self._actions:
            row = QTreeWidgetItem([_plain(act.text()),
                                   _to_text(act.shortcuts())])
            row.setData(0, Qt.UserRole, act)
            self._tree.addTopLevelItem(row)
        self._apply_filter(self._filter.text())

    def _apply_filter(self, text: str) -> None:
        t = (text or "").strip().lower()
        first = None
        for i in range(self._tree.topLevelItemCount()):
            row = self._tree.topLevelItem(i)
            row.setHidden(bool(t) and t not in row.text(0).lower()
                          and t not in row.text(1).lower())
            if first is None and not row.isHidden():
                first = row
        cur = self._tree.currentItem()
        if cur is None or cur.isHidden():
            # The box below must never show the keys of a hidden row.
            self._tree.setCurrentItem(first)
            if first is None:
                self._edit.setKeySequence(QKeySequence())

    def _current(self):
        row = self._tree.currentItem()
        return (row, row.data(0, Qt.UserRole)) if row is not None \
            else (None, None)

    def _on_row(self, *_a) -> None:
        _row, act = self._current()
        self._edit.setKeySequence(
            act.shortcuts()[0] if act is not None and act.shortcuts()
            else QKeySequence())

    # ---- editing ----------------------------------------------------------------
    def assign(self, act: QAction, seqs: list, ask: bool = True) -> bool:
        """Give ``act`` these keys, taking them from any other action that
        holds them (after asking) — two actions on one key both go dead."""
        wanted = {s.toString(QKeySequence.PortableText) for s in seqs}
        clash = [a for a in self._actions if a is not act and wanted &
                 {s.toString(QKeySequence.PortableText) for s in a.shortcuts()}]
        if clash and ask:
            names = ", ".join(_plain(a.text()) for a in clash)
            if QMessageBox.question(
                    self, tr("Keyboard shortcuts"),
                    tr("«{keys}» is already used by: {names}. Give it to "
                       "«{action}» instead?", keys=_to_text(seqs),
                       names=names, action=_plain(act.text()))
                    ) != QMessageBox.Yes:
                return False
        for other in clash:
            kept = [s for s in other.shortcuts()
                    if s.toString(QKeySequence.PortableText) not in wanted]
            other.setShortcuts(kept)
            save_shortcut(other, kept)
        act.setShortcuts(seqs)
        save_shortcut(act, seqs)
        self._fill()
        return True

    def _on_keys(self) -> None:
        _row, act = self._current()
        seq = self._edit.keySequence()
        if act is None or seq.isEmpty():
            return
        self.assign(act, [seq])

    def _on_clear(self) -> None:
        _row, act = self._current()
        if act is not None:
            self.assign(act, [], ask=False)

    def _on_reset(self) -> None:
        _row, act = self._current()
        if act is not None:
            self.assign(act, default_shortcuts(act))

    def _on_reset_all(self) -> None:
        if QMessageBox.question(
                self, tr("Keyboard shortcuts"),
                tr("Put every action back on its factory shortcut?")
                ) != QMessageBox.Yes:
            return
        st = QSettings()
        st.remove(_GROUP)
        st.sync()
        for act in self._actions:
            act.setShortcuts(default_shortcuts(act))
        self._fill()
