# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Keyboard shortcuts of one's own (issue #138, @pacaeiro)."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QMessageBox

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def _window():
    from views.main_window import MainWindow
    return MainWindow()


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _action(win, english):
    from views.shortcuts import action_key, collect_actions
    return next(a for a in collect_actions(win)
                if action_key(a) == "text:" + english)


def _keys(act):
    return [s.toString(QKeySequence.PortableText) for s in act.shortcuts()]


@pytest.mark.parametrize("lang", ["es", "ja"])
def test_a_shortcut_of_ones_own_survives_a_restart_and_the_language(
        monkeypatch, lang):
    from core.i18n import set_language
    from views.shortcuts import ShortcutsPanel
    QSettings().remove("shortcuts")
    win = _window()
    try:
        act = _action(win, "Explode Group")
        dlg = ShortcutsPanel(win)
        assert dlg.assign(act, [QKeySequence("Ctrl+Alt+E")])
        assert _keys(act) == ["Ctrl+Alt+E"]
    finally:
        _close(win)
    set_language(lang)
    try:
        win = _window()
        try:
            assert _keys(_action(win, "Explode Group")) == ["Ctrl+Alt+E"]
        finally:
            _close(win)
    finally:
        set_language("en")
        QSettings().remove("shortcuts")


def test_japanese_keeps_every_action_key(monkeypatch, tmp_path):
    """Duplicate translations must not rename persisted shortcut actions."""
    import core.extensions as extensions
    from core.i18n import current_language, set_language
    from core.paths import app_root
    from views.shortcuts import action_key

    monkeypatch.setattr(extensions, "plugin_dirs",
                        lambda: [app_root() / "plugins", tmp_path])
    original_language = current_language()
    keys = []
    try:
        for language in ("en", "ja"):
            set_language(language)
            win = _window()
            try:
                keys.append([action_key(a) for a in win.findChildren(QAction)])
            finally:
                _close(win)
        assert keys[0] == keys[1]
    finally:
        set_language(original_language)


def test_a_clash_takes_the_keys_from_the_other_action(monkeypatch):
    from views.shortcuts import ShortcutsPanel, collect_actions
    QSettings().remove("shortcuts")
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    win = _window()
    try:
        group = _action(win, "Make Group")
        explode = _action(win, "Explode Group")
        taken = _keys(group)[0]
        ShortcutsPanel(win).assign(explode, [QKeySequence(taken)])
        assert _keys(explode) == [taken]
        assert taken not in _keys(group)            # only one holds it
        seen: dict = {}
        for a in collect_actions(win):                # no key twice
            for k in _keys(a):
                assert k not in seen, (k, seen.get(k), a.text())
                seen[k] = a.text()
    finally:
        _close(win)
        QSettings().remove("shortcuts")


def test_default_puts_the_factory_keys_back(monkeypatch):
    from views.shortcuts import ShortcutsPanel, default_shortcuts
    QSettings().remove("shortcuts")
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    win = _window()
    try:
        act = _action(win, "Make Group")
        factory = _keys(act)
        dlg = ShortcutsPanel(win)
        dlg.assign(act, [])
        assert _keys(act) == []
        dlg.assign(act, default_shortcuts(act))
        assert _keys(act) == factory
        assert not QSettings().contains("shortcuts/text:Make Group")
    finally:
        _close(win)
        QSettings().remove("shortcuts")


def test_keys_the_viewport_reads_itself_are_refused():
    """Digits and decimal marks type a measure, Esc cancels, the arrows
    lock an axis: an action holding one would swallow it."""
    from views.shortcuts import reserved_reason
    for bad in ("5", "0", ".", ",", ";", "Esc", "Return", "Backspace",
                "Left", "Shift+Up", "Tab"):
        assert reserved_reason(QKeySequence(bad)) is not None, bad
    for good in ("Ctrl+5", "Alt+Left", "Ctrl+Shift+G", "F4", "K",
                 "Shift+K"):
        assert reserved_reason(QKeySequence(good)) is None, good


def test_the_key_box_captures_one_combination(monkeypatch):
    """The box takes the keys pressed in it — a real key event, modifiers
    alone ignored — and assigns them."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from views.shortcuts import ShortcutsPanel
    QSettings().remove("shortcuts")
    win = _window()
    try:
        panel = ShortcutsPanel(win)
        panel._filter.setText("Make Group")
        panel._tree.setCurrentItem(panel._tree.topLevelItem(
            next(i for i in range(panel._tree.topLevelItemCount())
                 if not panel._tree.topLevelItem(i).isHidden())))
        QTest.keyClick(panel._edit, Qt.Key_Control)          # alone: nothing
        assert _keys(_action(win, "Make Group")) == ["Ctrl+G"]
        QTest.keyClick(panel._edit, Qt.Key_K,
                       Qt.ControlModifier | Qt.AltModifier)
        assert _keys(_action(win, "Make Group")) == ["Ctrl+Alt+K"]
    finally:
        _close(win)
        QSettings().remove("shortcuts")


def test_a_shortcut_on_an_action_with_a_slash_survives_a_restart():
    """«Push / Pull» and «Toggle Perspective / Parallel» on keys of one's own:
    QSettings read the «/» as a group, stored them nested and never read
    them back — the keys worked until the next start (issue #236,
    @zhang-922)."""
    from views.shortcuts import ShortcutsPanel
    QSettings().remove("shortcuts")
    win = _window()
    try:
        panel = ShortcutsPanel(win)
        assert panel.assign(_action(win, "Push / Pull"),
                            [QKeySequence("Ctrl+Alt+Shift+J")])
        assert panel.assign(_action(win, "Toggle Perspective / Parallel"),
                            [QKeySequence("Ctrl+Alt+Shift+H")])
    finally:
        _close(win)
    win = _window()
    try:
        assert _keys(_action(win, "Push / Pull")) == ["Ctrl+Alt+Shift+J"]
        assert _keys(_action(win, "Toggle Perspective / Parallel")) == \
            ["Ctrl+Alt+Shift+H"]
    finally:
        _close(win)
        QSettings().remove("shortcuts")


def test_a_shortcut_saved_nested_by_an_earlier_version_is_read_back():
    """What 0.5.6.1 wrote — a group «text:Push » with a key « Pull» — is
    recovered, not lost."""
    QSettings().remove("shortcuts")
    st = QSettings()
    st.setValue("shortcuts/text:Push / Pull", "Ctrl+Alt+Shift+J")
    st.sync()
    win = _window()
    try:
        assert _keys(_action(win, "Push / Pull")) == ["Ctrl+Alt+Shift+J"]
    finally:
        _close(win)
        QSettings().remove("shortcuts")


def _rows(panel):
    tree = panel._tree
    return [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]


def _row_of(panel, act):
    from PySide6.QtCore import Qt
    return next(r for r in _rows(panel) if r.data(0, Qt.UserRole) is act)


@pytest.mark.parametrize("name", ["Selected", "Last", "All"])
def test_a_command_says_which_menu_it_lives_in(name):
    """«Selected», «Last» and «All» say little alone (#1107)."""
    from views.shortcuts import ShortcutsPanel
    win = _window()
    try:
        panel = ShortcutsPanel(win)
        row = _row_of(panel, _action(win, name))
        assert row.text(0) == name
        assert row.text(1) == "Edit ▸ Unhide"
    finally:
        _close(win)


def test_a_command_found_only_on_a_toolbar_says_the_toolbar():
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QToolBar
    from views.shortcuts import ShortcutsPanel
    win = _window()
    try:
        bar = QToolBar("My Extension", win)
        win.addToolBar(bar)
        act = QAction("Only On A Toolbar", win)
        bar.addAction(act)
        panel = ShortcutsPanel(win)
        assert _row_of(panel, act).text(1) == "My Extension"
    finally:
        _close(win)


def test_the_filter_finds_every_command_of_a_menu():
    from views.shortcuts import ShortcutsPanel
    win = _window()
    try:
        panel = ShortcutsPanel(win)
        panel._filter.setText("unhide")
        shown = {r.text(0) for r in _rows(panel) if not r.isHidden()}
        assert {"Selected", "Last", "All"} <= shown
        assert "Make Group" not in shown
    finally:
        _close(win)


def test_the_filter_still_finds_a_name_and_a_key():
    from views.shortcuts import ShortcutsPanel
    win = _window()
    try:
        panel = ShortcutsPanel(win)
        panel._filter.setText("Make Group")
        assert "Make Group" in {r.text(0) for r in _rows(panel)
                                if not r.isHidden()}
        panel._filter.setText("Ctrl+G")
        assert "Make Group" in {r.text(0) for r in _rows(panel)
                                if not r.isHidden()}
        panel._filter.setText("no such command anywhere")
        assert not [r for r in _rows(panel) if not r.isHidden()]
    finally:
        _close(win)


def test_the_new_keys_show_in_their_column_and_the_menu_stays():
    from views.shortcuts import ShortcutsPanel
    QSettings().remove("shortcuts")
    win = _window()
    try:
        panel = ShortcutsPanel(win)
        act = _action(win, "All")
        assert panel.assign(act, [QKeySequence("Ctrl+Alt+Shift+U")])
        row = _row_of(panel, act)
        assert row.text(1) == "Edit ▸ Unhide"
        assert row.text(2) == "Ctrl+Alt+Shift+U"
        assert QSettings().value("shortcuts/text:All") == "Ctrl+Alt+Shift+U"
    finally:
        _close(win)
        QSettings().remove("shortcuts")


@pytest.mark.parametrize("lang,word", [("es", "Menú"), ("ja", "メニュー"),
                                       ("ar", "القائمة")])
def test_the_column_heading_is_translated(lang, word):
    from core.i18n import set_language
    from views.shortcuts import ShortcutsPanel
    set_language(lang)
    try:
        win = _window()
        try:
            panel = ShortcutsPanel(win)
            assert panel._tree.headerItem().text(1) == word
        finally:
            _close(win)
    finally:
        set_language("en")


def test_every_language_has_the_column_heading():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "i18n"
    for path in root.glob("*.json"):
        if path.stem != "en":
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data.get("Menu"), path.name


def test_a_window_without_a_menu_bar_lists_its_commands_with_no_menu():
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QWidget
    from views.shortcuts import ShortcutsPanel
    win = QWidget()
    act = QAction("Loose Command", win)
    panel = ShortcutsPanel(win)
    assert _row_of(panel, act).text(0) == "Loose Command"
    assert _row_of(panel, act).text(1) == ""


def test_a_long_menu_path_leaves_room_for_the_names():
    """Sized to its contents, the Menu column left the names 20 px wide in
    the Preferences window."""
    from views.shortcuts import ShortcutsPanel
    win = _window()
    try:
        panel = ShortcutsPanel(win)
        panel.resize(533, 500)
        panel.show()
        QApplication.processEvents()
        tree = panel._tree
        assert tree.columnWidth(0) == pytest.approx(tree.columnWidth(1), abs=2)
        assert tree.columnWidth(0) > 150
        panel.close()
    finally:
        _close(win)
