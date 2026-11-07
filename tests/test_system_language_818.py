# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""#818: "Same as the system" as a UI language choice.

The OS display language picks the closest catalog; the choice is offered
in Preferences (and Window ▸ Language) and is what an unset choice means.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import PySide6.QtCore as QtCore
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget

from core import i18n

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

import views.preferences_dialog as prefs_mod  # noqa: E402
from views.preferences_dialog import PreferencesDialog  # noqa: E402


@pytest.mark.parametrize("locales, expected", [
    (["es-ES"], "es"),
    (["pt-BR"], "pt-BR"),
    (["pt-PT"], "pt-BR"),            # same base language
    (["de_AT"], "de"),               # Qt's underscore spelling too
    (["zh-Hans-CN"], "zh-CN"),
    (["it-IT", "en-US"], "it"),
    (["en-US", "es-ES"], "en"),      # the first preferred one decides
    (["nl-NL", "fr-FR"], "fr"),      # no Dutch catalog: next preference
    (["nl-NL"], "en"),
    ([], "en"),
])
def test_system_locales_pick_the_closest_catalog(locales, expected):
    assert i18n.language_for_locales(locales) == expected


class _FakeLocale:
    languages = ["fr-FR", "en-US"]

    @classmethod
    def system(cls):
        return cls

    @classmethod
    def uiLanguages(cls):
        return cls.languages


@pytest.fixture
def system_is_french(monkeypatch):
    monkeypatch.setattr(QtCore, "QLocale", _FakeLocale)


def test_unset_or_system_follows_the_os_and_a_pinned_one_stays(system_is_french):
    assert i18n.resolve_language(None) == "fr"
    assert i18n.resolve_language("") == "fr"
    assert i18n.resolve_language(i18n.SYSTEM) == "fr"
    assert i18n.resolve_language("de") == "de"


@pytest.fixture
def prefs(tmp_path, monkeypatch, system_is_french):
    """A throwaway settings file, the app running in French as the
    system's, and the restart notes counted instead of shown."""
    path = tmp_path / "prefs.ini"
    monkeypatch.setattr(prefs_mod, "QSettings",
                        lambda: QSettings(str(path), QSettings.IniFormat))
    notes = []
    monkeypatch.setattr(prefs_mod.QMessageBox, "information",
                        lambda *a, **k: notes.append(a))
    before = i18n.current_language()
    i18n.set_language("fr")
    yield path, notes
    i18n.set_language(before)


class _Win(QWidget):
    def __init__(self):
        super().__init__()

        class _VP:
            edit_rest_mode = "fade"

            def set_edit_rest_mode(self, mode):
                self.edit_rest_mode = mode

        self.viewport = _VP()
        self._rest_actions = {}


def test_preferences_offers_the_system_language_first_and_by_default(prefs):
    dlg = PreferencesDialog(_Win())
    assert dlg._lang.itemData(0) == i18n.SYSTEM
    assert dlg._lang.currentData() == i18n.SYSTEM     # nothing saved yet


def test_going_back_to_the_system_language_is_saved(prefs):
    path, notes = prefs
    st = QSettings(str(path), QSettings.IniFormat)
    st.setValue("language", "fr")
    st.sync()
    dlg = PreferencesDialog(_Win())
    assert dlg._lang.currentData() == "fr"
    dlg._lang.setCurrentIndex(dlg._lang.findData(i18n.SYSTEM))
    dlg.accept()
    assert QSettings(str(path), QSettings.IniFormat).value("language") == "system"
    # The system's language is the one running: nothing to restart for.
    assert notes == []
    assert i18n.current_language() == "fr"


def test_pinning_another_language_over_the_system_one_asks_a_restart(prefs):
    path, notes = prefs
    dlg = PreferencesDialog(_Win())
    dlg._lang.setCurrentIndex(dlg._lang.findData("de"))
    dlg.accept()
    assert QSettings(str(path), QSettings.IniFormat).value("language") == "de"
    assert len(notes) == 1
    assert i18n.current_language() == "de"


@pytest.mark.parametrize("saved", [None, i18n.SYSTEM, "de"])
def test_startup_resolves_the_saved_choice(saved, tmp_path, monkeypatch,
                                           system_is_french):
    """main._init_language runs the same resolution as the menus: an
    unset choice or "system" starts in the OS language, never crashes
    nor activates a catalog literally named "system"."""
    import main
    path = tmp_path / "start.ini"
    st = QSettings(str(path), QSettings.IniFormat)
    if saved is not None:
        st.setValue("language", saved)
    st.sync()
    monkeypatch.setattr(main, "QSettings",
                        lambda: QSettings(str(path), QSettings.IniFormat))
    installed = []
    monkeypatch.setattr(main, "_install_qt_translator", installed.append)
    before = i18n.current_language()
    try:
        main._init_language()
        expected = "de" if saved == "de" else "fr"
        assert i18n.current_language() == expected
        assert installed == [expected]
    finally:
        i18n.set_language(before)
