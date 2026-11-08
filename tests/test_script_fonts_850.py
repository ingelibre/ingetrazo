# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Lao on Windows (#850): the interface font starts with one that holds
the script, so the vowel and tone marks compose with their consonant.
Every other language, and Lao elsewhere, start exactly as before."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from views import script_fonts
from views.script_fonts import apply_script_font, script_font_for

_app = QApplication.instance() or QApplication([])

WINDOWS_FONTS = ["Segoe UI", "Leelawadee UI", "Noto Sans Lao", "Arial"]


def test_lao_on_windows_takes_leelawadee_ui():
    assert script_font_for("lo", WINDOWS_FONTS, "win32") == "Leelawadee UI"


def test_lao_on_windows_without_leelawadee_takes_the_next():
    assert script_font_for("lo", ["Segoe UI", "Noto Sans Lao"],
                           "win32") == "Noto Sans Lao"
    assert script_font_for("lo", ["Segoe UI", "Lao UI"], "win32") == "Lao UI"


def test_lao_on_windows_with_no_lao_font_changes_nothing():
    assert script_font_for("lo", ["Segoe UI", "Arial"], "win32") is None


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_lao_elsewhere_changes_nothing(platform):
    assert script_font_for("lo", WINDOWS_FONTS, platform) is None


@pytest.mark.parametrize("lang", ["es", "en", "th", "ar", "zh-CN", "", None])
def test_other_languages_change_nothing(lang):
    assert script_font_for(lang, WINDOWS_FONTS, "win32") is None


def test_region_tags_read_as_their_language():
    assert script_font_for("lo-LA", WINDOWS_FONTS, "win32") == "Leelawadee UI"
    assert script_font_for("lo_LA", WINDOWS_FONTS, "win32") == "Leelawadee UI"


@pytest.fixture
def app_font():
    before = _app.font()
    try:
        yield
    finally:
        _app.setFont(before)


def test_apply_puts_the_script_font_first_and_keeps_the_rest(app_font,
                                                              monkeypatch):
    installed = QFontDatabase.families()
    assert installed, "no font at all in this Qt"
    lao_font = installed[-1]
    monkeypatch.setitem(script_fonts.SCRIPT_FONTS, "lo", (lao_font,))
    before = list(_app.font().families() or [_app.font().family()])
    size = _app.font().pointSizeF()

    assert apply_script_font(_app, "lo", "win32") is True
    fams = list(_app.font().families())
    assert fams[0] == lao_font
    assert [f for f in before if f != lao_font] == fams[1:]
    assert _app.font().pointSizeF() == size


@pytest.mark.parametrize("lang,platform", [("es", "win32"), ("lo", "linux")])
def test_apply_leaves_the_font_as_it_was(app_font, lang, platform):
    before = _app.font()
    assert apply_script_font(_app, lang, platform) is False
    assert _app.font() == before


def test_startup_hook_runs_with_the_language(app_font, monkeypatch, tmp_path):
    """main's language loader calls the hook with the chosen language."""
    import main
    seen = []
    monkeypatch.setattr(script_fonts, "apply_script_font",
                        lambda app, lang: seen.append(lang) or False)
    monkeypatch.setattr(main.i18n, "resolve_language", lambda _c: "lo")
    monkeypatch.setattr(main, "_install_qt_translator", lambda _l: None)
    try:
        main._init_language()
    finally:
        main.i18n.set_language("en")
    assert seen == ["lo"]
