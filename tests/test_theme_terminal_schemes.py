# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The themes drawn on Slate's pattern: Studio, Solarized, Campbell and
Sand, after the 3D suites' look and the colour schemes Linux users keep in
their terminals.

Each is a table of the same shades as Slate (SHEET_THEMES) with its own
icon ink, selection and links (SHEET_EXTRAS); applying one sets its
palette and its sheet, its grip, outline and icon ink, it is saved and
offered in Preferences, its name is translated, and its text reads on its
window, and the menu bar item under the pointer keeps a readable text.
Leaving it for Dark leaves nothing of it behind."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

_inst = QGuiApplication.instance()
if _inst is None:
    _app = QApplication(sys.argv[:1])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from views import theme  # noqa: E402

NEW = (theme.STUDIO, theme.SOLARIZED, theme.CAMPBELL, theme.SAND)
LABELS = {theme.STUDIO: "Studio", theme.SOLARIZED: "Solarized",
          theme.CAMPBELL: "Campbell", theme.SAND: "Sand"}


@pytest.fixture
def app():
    a = QApplication.instance()
    before_theme, before_accent = theme.saved_theme(), theme.saved_accent()
    a.setStyleSheet("")
    theme._app_sheet = ""
    yield a
    theme.save_theme(before_theme)
    theme.save_accent(before_accent)
    a.setStyleSheet("")
    theme._app_sheet = ""
    theme.apply_theme(a, theme.DARK)


@pytest.mark.parametrize("mode", NEW)
def test_a_new_theme_applies_its_own_shades(app, mode):
    colours = theme.SHEET_THEMES[mode]
    assert set(colours) == set(theme.SLATE_COLOURS)       # same roles
    assert mode in theme.THEMES
    light = mode in theme.LIGHT_SHEET_THEMES
    assert theme.apply_theme(app, mode) is (not light)
    pal = app.palette()
    assert pal.color(QPalette.Window) == QColor(colours["window"])
    assert pal.color(QPalette.Base) == QColor(colours["deep"])
    extra = theme.SHEET_EXTRAS[mode]
    assert pal.color(QPalette.Highlight) == QColor(extra["highlight"])
    # Its text reads on its window, either way round.
    gap = (pal.color(QPalette.WindowText).lightness()
           - pal.color(QPalette.Window).lightness())
    assert (gap < -120) if light else (gap > 120), gap
    # Its sheet, filled with its own shades, not Slate's.
    sheet = app.styleSheet()
    assert sheet == theme.sheet_for(mode)
    assert "{" + "deep" + "}" not in sheet
    assert colours["raised"] in sheet
    assert theme.SLATE_COLOURS["raised"] not in sheet
    # Grip, outline and icon ink follow it.
    assert theme.grip_colour() == QColor(colours["grip"])
    assert theme.active_tool_colour() == QColor(colours["active"])
    assert theme.icon_ink() == QColor(extra["ink"])
    theme.save_theme(mode)
    assert theme.saved_theme() == mode


def test_the_accent_reaches_a_new_themes_sheet(app):
    theme.apply_theme(app, theme.SOLARIZED)
    theme.save_accent("green")
    theme.apply_accent(app)
    assert "46, 160, 67" in app.styleSheet()
    assert theme.SOLARIZED_COLOURS["raised"] in app.styleSheet()


def test_leaving_a_new_theme_for_dark_leaves_nothing_of_it(app):
    theme.apply_theme(app, theme.CAMPBELL)
    assert app.styleSheet()
    theme.apply_theme(app, theme.DARK)
    assert app.styleSheet() == ""
    assert app.palette().color(QPalette.Window) == \
        theme.dark_palette().color(QPalette.Window)
    assert theme.icon_ink() == QColor(theme.ICON_INKS[theme.DARK])


def test_preferences_offer_every_theme_with_a_translated_name(app):
    from views.main_window import MainWindow
    from views.preferences_dialog import PreferencesDialog
    win = MainWindow()
    try:
        dlg = PreferencesDialog(win)
        offered = [dlg._theme.itemData(i) for i in range(dlg._theme.count())]
        dlg.deleteLater()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
    assert set(offered) == set(theme.THEMES)
    root = Path(__file__).resolve().parent.parent / "i18n"
    for path in root.glob("*.json"):
        if path.name == "en.json":
            continue
        cat = json.loads(path.read_text(encoding="utf-8"))
        for mode, label in LABELS.items():
            assert cat.get(label), (path.name, label)


def test_the_menu_bar_item_under_the_pointer_keeps_a_readable_text(app):
    """On Sand the hovered menu-bar title went white over a pale tint: the
    sheet gives it the theme's own strongest text."""
    theme.apply_theme(app, theme.SAND)
    sheet = app.styleSheet()
    rule = sheet[sheet.index("QMenuBar::item:selected"):]
    rule = rule[:rule.index("}")]
    assert "color: " + theme.SAND_COLOURS["bright"] in rule
    # And an item of an open menu: a tint under it, the same text — Qt left
    # it white with nothing under it on the sheet's menu background.
    rule = sheet[sheet.index("QMenu::item:selected"):]
    rule = rule[:rule.index("}")]
    assert "background: rgba(" in rule
    assert "color: " + theme.SAND_COLOURS["bright"] in rule
