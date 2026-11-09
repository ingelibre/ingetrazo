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

from functools import lru_cache

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtCore import Signal
from PySide6.QtCore import QKeyCombination
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from core.i18n import current_language, source_of, tr

_GROUP = "shortcuts"
_DEFAULTS = "ingetrazo_default_shortcuts"
_TIP = "ingetrazo_tooltip_base"


def set_tooltip(action: QAction, base: str) -> None:
    """A toolbar tooltip that names the action's CURRENT keys: «Line  (L)»,
    and under them what the action does — its status tip, when it has one.

    The keys used to be written into the text once, at start-up, so a
    shortcut changed in Preferences showed in the menus (Qt reads the
    action) and not on the toolbar buttons (issue #171). The tooltip is
    rebuilt whenever the action changes -- whoever changed the keys."""
    fresh = action.property(_TIP) is None
    action.setProperty(_TIP, base)
    if fresh:
        action.changed.connect(lambda a=action: _refresh_tooltip(a))
    _refresh_tooltip(action)


def _refresh_tooltip(action: QAction) -> None:
    base = action.property(_TIP)
    if base is None:
        return
    keys = action.shortcut().toString(QKeySequence.NativeText)
    tip = f"{base}  ({keys})" if keys else base
    if action.statusTip():
        tip += "\n" + action.statusTip()
    # setToolTip with the same text returns early, so the changed signal
    # this emits does not loop.
    action.setToolTip(tip)


def _plain(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&") \
        .rstrip("…").rstrip(".").strip()


def action_key(action: QAction) -> str:
    name = action.objectName()
    if name:
        return name
    return _text_key(action.text(), current_language())


@lru_cache(maxsize=4096)
def _text_key(text: str, _language: str) -> str:
    # Remembered per language: F3 asks for every action's key several
    # times each time it opens (views/command_search.py).
    return "text:" + _plain(source_of(text))


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


def reserved_reason(seq: QKeySequence):
    """Why ``seq`` cannot be a shortcut, or ``None``. The viewport reads
    some keys itself — not through actions — and an action holding one
    would swallow it: digits and the decimal marks type a measure in the
    value box, Esc cancels, Enter commits, Backspace edits the box, the
    arrows lock an axis, Tab and the bare modifiers steer the tools."""
    if seq.isEmpty():
        return None
    combo = seq[0]
    key = combo.key()
    mods = combo.keyboardModifiers() & ~Qt.KeypadModifier
    plain = mods in (Qt.NoModifier, Qt.ShiftModifier)
    if key in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Backspace,
               Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Shift, Qt.Key_Control,
               Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr):
        return tr("the drawing tools use it (cancel, confirm, edit a value)")
    if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and plain:
        return tr("the arrow keys lock an axis while drawing")
    if plain and (Qt.Key_0 <= key <= Qt.Key_9 or key in (
            Qt.Key_Period, Qt.Key_Comma, Qt.Key_Semicolon, Qt.Key_Minus,
            Qt.Key_Slash, Qt.Key_Asterisk, Qt.Key_Apostrophe,
            Qt.Key_QuoteDbl)):
        return tr("it types a measure in the value box")
    return None


def remember_defaults(window) -> None:
    """Note each action's factory keys (before the user's go on)."""
    for act in collect_actions(window):
        if act.property(_DEFAULTS) is None:
            act.setProperty(_DEFAULTS, _to_text(act.shortcuts()))


def default_shortcuts(action: QAction) -> list:
    return _from_text(action.property(_DEFAULTS) or "")


def _store_key(key: str) -> str:
    """``key`` as a QSettings key: QSettings reads «/» as a group, so
    «text:Push / Pull» was stored as a group «text:Push » holding « Pull»
    and never read back — the key worked until the next start (issue
    #236, @zhang-922). «/», «\\» and «%» travel escaped."""
    return (key.replace("%", "%25").replace("/", "%2F")
            .replace("\\", "%5C"))


def _read_key(stored: str) -> str:
    """The action key a stored QSettings key stands for. Keys written
    before the escape come back through ``allKeys`` with their «/»."""
    import re
    return re.sub(r"%(25|2F|5C)",
                  lambda m: {"25": "%", "2F": "/", "5C": "\\"}[m.group(1)],
                  stored)


def _saved_shortcuts() -> dict:
    st = QSettings()
    st.beginGroup(_GROUP)
    saved = {_read_key(k): str(st.value(k) or "") for k in st.allKeys()}
    st.endGroup()
    return saved


def _unique(seqs) -> list:
    """``seqs`` without repeats, first one kept: a key listed twice on one
    action does not fire (#313)."""
    seen: set = set()
    out = []
    for q in seqs:
        t = q.toString(QKeySequence.PortableText)
        if t and t not in seen:
            seen.add(t)
            out.append(q)
    return out


def apply_user_shortcuts(window) -> int:
    """Put the remembered keys on the window's actions. Returns how many."""
    saved = _saved_shortcuts()
    n = 0
    for act in collect_actions(window):
        key = action_key(act)
        if key in saved:
            seqs = _unique(q for q in _from_text(saved[key])
                           if reserved_reason(q) is None)  # never reserved
            act.setShortcuts(seqs)
            n += 1
    return n


def save_shortcut(action: QAction, seqs: list) -> None:
    st = QSettings()
    key = action_key(action)
    st.remove(f"{_GROUP}/{key}")               # a pre-escape entry, if any
    if _to_text(seqs) == (action.property(_DEFAULTS) or ""):
        st.remove(f"{_GROUP}/{_store_key(key)}")   # back to the factory keys
    else:
        st.setValue(f"{_GROUP}/{_store_key(key)}", _to_text(seqs))
    st.sync()


#: What an exported shortcuts file says it is (issue #142).
EXPORT_FORMAT = "ingetrazo-shortcuts"


def export_shortcuts(window) -> dict:
    """Every action's keys, by its language-free key: a file made in one
    language imports in any other, on any machine (issue #142, @pacaeiro:
    «transfer shortcut configurations between computers, O.S., friends»).
    Actions with no keys are written too, so a cleared key travels."""
    return {"format": EXPORT_FORMAT, "version": 1,
            "shortcuts": {action_key(a): _to_text(a.shortcuts())
                          for a in collect_actions(window)}}


def import_shortcuts(window, data) -> tuple:
    """Put the keys of an exported file on the window's actions, and
    remember them. Actions this machine does not have (a plugin not
    installed) and reserved keys are skipped; a key the file gives to one
    action is taken from any other that held it, as assigning it by hand
    does. A key the file gives to SEVERAL actions stays with the first and
    is taken from the rest: two actions sharing a key both go dead, as Z
    did for Zoom and Zoom Selection in a file written from another
    program's keys (#323, @tomlai-git). Returns ``(applied, skipped,
    clashes)`` — ``clashes`` lists ``(key, kept_by, dropped_from)``; raises
    ValueError for a file that is not an IngeTrazo shortcuts file."""
    if (not isinstance(data, dict) or data.get("format") != EXPORT_FORMAT
            or not isinstance(data.get("shortcuts"), dict)):
        raise ValueError(tr("This is not an IngeTrazo shortcuts file."))
    wanted = {str(k): str(v or "") for k, v in data["shortcuts"].items()}
    actions = collect_actions(window)
    by_key = {action_key(a): a for a in actions}
    applied = 0
    taken: dict = {}                      # key text -> the action that has it
    clashes: list = []
    for key, text in wanted.items():
        act = by_key.get(key)
        if act is None:
            continue
        seqs = []
        for q in _unique(q for q in _from_text(text)
                         if reserved_reason(q) is None):
            t = q.toString(QKeySequence.PortableText)
            if t in taken:
                clashes.append((t, taken[t], act))
                continue
            taken[t] = act
            seqs.append(q)
        act.setShortcuts(seqs)
        save_shortcut(act, seqs)
        applied += 1
    for act in actions:
        if action_key(act) in wanted:
            continue
        kept = [s for s in act.shortcuts()
                if s.toString(QKeySequence.PortableText) not in taken]
        if len(kept) != len(act.shortcuts()):
            act.setShortcuts(kept)
            save_shortcut(act, kept)
    return applied, len(wanted) - applied, clashes


# The digit row by physical key: with Shift held, Qt reports the symbol the
# layout types (Shift+5 → «%» on most layouts) and the shortcut was saved
# as «Shift+%» (#493, @pacaeiro). Qt matches «Shift+5» on a real Shift+5
# (checked by hand on xcb and Wayland, 10-10), so the digit is what we keep.
_DIGITS = "1234567890"
#: macOS virtual key codes (kVK_ANSI_1 … kVK_ANSI_0).
_MAC_DIGIT_VK = {0x12: "1", 0x13: "2", 0x14: "3", 0x15: "4", 0x17: "5",
                 0x16: "6", 0x1A: "7", 0x1C: "8", 0x19: "9", 0x1D: "0"}


def digit_row_key(event):
    """The Qt key of the digit-row key pressed, read from the physical
    key — or ``None`` when it is not one (or the platform says nothing)."""
    from PySide6.QtGui import QGuiApplication
    platform = QGuiApplication.platformName()
    scan = event.nativeScanCode()
    if platform in ("xcb", "wayland", "offscreen"):
        index = scan - 10               # xkb keycodes: «1» is 10 … «0» is 19
    elif platform == "windows":
        index = (scan & 0xFF) - 2       # set-1 scan codes: «1» is 2 … «0» is 11
    elif platform == "cocoa":
        digit = _MAC_DIGIT_VK.get(event.nativeVirtualKey())
        return None if digit is None else Qt.Key(ord(digit))
    else:
        return None
    if 0 <= index < 10:
        return Qt.Key(ord(_DIGITS[index]))
    return None


class _KeyCapture(QLineEdit):
    """A box that takes ONE key combination (the keys pressed in it).

    Not QKeySequenceEdit: that widget hands its focus to an inner line edit
    (a focus proxy), and destroying it inside Preferences — a dialog that
    lives as the main window's child until the window goes — crashed the
    process in QWidget::~QWidget → window() while the window was being torn
    down: the test suite died with a segmentation fault, every run, from the
    commit that put this panel into Preferences on."""

    keyCaptured = Signal(QKeySequence)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText(tr("Click here and press the keys"))
        self._seq = QKeySequence()

    def keySequence(self) -> QKeySequence:
        return self._seq

    def setKeySequence(self, seq: QKeySequence) -> None:
        self._seq = QKeySequence(seq)
        self.setText(self._seq.toString(QKeySequence.NativeText))

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta,
                   Qt.Key_AltGr, Qt.Key_unknown, 0):
            return                            # wait for the real key
        mods = event.modifiers() & ~Qt.KeypadModifier
        if mods & Qt.ShiftModifier and not (Qt.Key_0 <= key <= Qt.Key_9):
            key = digit_row_key(event) or key   # Shift+5, not Shift+%
        self.setKeySequence(QKeySequence(QKeyCombination(mods, Qt.Key(key))))
        self.keyCaptured.emit(self._seq)


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
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels([tr("Action"), tr("Menu"), tr("Shortcut")])
        self._tree.setRootIsDecorated(False)
        # Name and menu share the width: sized to its contents, one long
        # path would leave no room for the names.
        for column in (0, 1):
            self._tree.header().setSectionResizeMode(
                column, QHeaderView.Stretch)
        self._tree.header().setSectionResizeMode(
            2, QHeaderView.ResizeToContents)
        self._tree.currentItemChanged.connect(self._on_row)
        lay.addWidget(self._tree, 1)
        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel(tr("New shortcut:")))
        self._edit = _KeyCapture()
        self._edit.keyCaptured.connect(lambda _seq: self._on_keys())
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
        export = QPushButton(tr("Export…"))
        export.setToolTip(tr("Save these shortcuts to a file, to take them "
                             "to another computer"))
        export.clicked.connect(self._on_export)
        foot.addWidget(export)
        imp = QPushButton(tr("Import…"))
        imp.setToolTip(tr("Use the shortcuts saved in a file"))
        imp.clicked.connect(self._on_import)
        foot.addWidget(imp)
        reset_all = QPushButton(tr("Restore all defaults"))
        reset_all.clicked.connect(self._on_reset_all)
        foot.addWidget(reset_all)
        lay.addLayout(foot)
        self._actions = collect_actions(window)
        # «Selected», «Last» and «All» say little alone: each row also says
        # where its command lives (#1107). Imported here because
        # views/command_search.py imports this module.
        from views.command_search import menu_paths
        self._paths = menu_paths(window)
        self._fill()

    # ---- list -----------------------------------------------------------------
    def _fill(self) -> None:
        self._tree.clear()
        for act in self._actions:
            row = QTreeWidgetItem([_plain(act.text()),
                                   self._paths.get(action_key(act), ""),
                                   _to_text(act.shortcuts())])
            row.setData(0, Qt.UserRole, act)
            row.setToolTip(1, row.text(1))
            self._tree.addTopLevelItem(row)
        self._apply_filter(self._filter.text())

    def _apply_filter(self, text: str) -> None:
        t = (text or "").strip().lower()
        first = None
        for i in range(self._tree.topLevelItemCount()):
            row = self._tree.topLevelItem(i)
            row.setHidden(bool(t) and not any(
                t in row.text(column).lower() for column in range(3)))
            if first is None and not row.isHidden():
                first = row
        cur = self._tree.currentItem()
        if cur is None or cur.isHidden():
            # The box below must never show the keys of a hidden row.
            self._tree.setCurrentItem(first)
            if first is None:
                self._edit.setKeySequence(QKeySequence())

    def pick(self, act: QAction) -> None:
        """Select ``act``'s row, ready for its new keys."""
        self._filter.clear()
        for i in range(self._tree.topLevelItemCount()):
            row = self._tree.topLevelItem(i)
            if row.data(0, Qt.UserRole) is act:
                self._tree.setCurrentItem(row)
                self._tree.scrollToItem(row)
                self._edit.setFocus()
                return

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
        why = reserved_reason(seq)
        if why is not None:
            QMessageBox.information(
                self, tr("Keyboard shortcuts"),
                tr("«{keys}» cannot be a shortcut: {why}.",
                   keys=seq.toString(QKeySequence.NativeText), why=why))
            self._on_row()                    # show the action's keys again
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

    def _on_export(self) -> None:
        import json
        from views.filedialogs import file_dialogs
        path, _ = file_dialogs.getSaveFileName(
            self, tr("Export shortcuts"), "ingetrazo-shortcuts.json",
            tr("Shortcuts (*.json)"))
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(export_shortcuts(self._window), f, indent=1,
                          ensure_ascii=False)
        except OSError as exc:
            QMessageBox.warning(self, tr("Export shortcuts"), str(exc))

    def _on_import(self) -> None:
        import json
        from views.filedialogs import file_dialogs
        path, _ = file_dialogs.getOpenFileName(
            self, tr("Import shortcuts"), "", tr("Shortcuts (*.json)"))
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                applied, skipped, clashes = import_shortcuts(
                    self._window, json.load(f))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("Import shortcuts"), str(exc))
            return
        self._fill()
        msg = tr("{n} shortcuts imported.", n=applied)
        if skipped:
            msg += " " + tr("{n} belong to actions this installation does "
                            "not have (a plugin, say) and were left out.",
                            n=skipped)
        if clashes:
            lines = [tr("{key}: kept for «{kept}», taken from «{dropped}»",
                        key=QKeySequence(k).toString(
                            QKeySequence.NativeText),
                        kept=_plain(kept.text()),
                        dropped=_plain(dropped.text()))
                     for k, kept, dropped in clashes]
            msg += "\n\n" + tr(
                "The file gave the same key to more than one command; "
                "a shared key works for none, so each stays with the "
                "first:") + "\n" + "\n".join(lines)
        QMessageBox.information(self, tr("Import shortcuts"), msg)

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
