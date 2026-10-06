# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Qt's own standard buttons (OK, Cancel, Yes, No…) follow the app language.

Our catalog only covers ``tr()``; those buttons come from Qt's
``qtbase_<lang>.qm``, and without it they stayed in English. The keys in
the shortcuts stay in English on purpose: only the buttons are taken."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])


@pytest.mark.parametrize("lang, yes, cancel", [
    ("es", "&Sí", "Cancelar"),
    ("pt-BR", "&Sim", "Cancelar"),
])
def test_standard_buttons_are_translated(monkeypatch, lang, yes, cancel):
    import main
    monkeypatch.setattr(main, "_qt_translator", None)
    main._install_qt_translator(lang)
    try:
        assert main._qt_translator is not None
        box = QMessageBox(QMessageBox.Question, "", "",
                          QMessageBox.Yes | QMessageBox.Cancel)
        assert box.button(QMessageBox.Yes).text() == yes
        assert box.button(QMessageBox.Cancel).text() == cancel
    finally:
        QApplication.removeTranslator(main._qt_translator)


def test_english_installs_nothing(monkeypatch):
    import main
    monkeypatch.setattr(main, "_qt_translator", None)
    main._install_qt_translator("en")
    assert main._qt_translator is None


# TODO(MAC-03): Baseline macOS NativeText returns key symbols, not portable key names.
# See docs/macos-test-failures.md; confirmed on the baseline commit, not fixed yet.
def test_shortcuts_keep_their_english_key_names(monkeypatch):
    import main
    monkeypatch.setattr(main, "_qt_translator", None)
    main._install_qt_translator("es")
    try:
        shown = QKeySequence("Ctrl+Shift+PgUp").toString(QKeySequence.NativeText)
        assert shown == "Ctrl+Shift+PgUp"            # not «Control+Mayúsculas…»
        assert QKeySequence("Esc").toString(QKeySequence.NativeText) == "Esc"
    finally:
        QApplication.removeTranslator(main._qt_translator)
