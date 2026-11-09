# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Light / dark chrome: follow the desktop, or pin one (views/theme.py).

The suite's QSettings live in a throwaway store (tests/conftest.py), so the
saved mode here never reaches the user's.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QLabel, QToolButton, QWidget

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from views import theme  # noqa: E402


@pytest.fixture
def app():
    a = QApplication.instance()
    before = theme.saved_theme()
    yield a
    # Leave the rest of the suite on the dark chrome it always had.
    theme.save_theme(before)
    theme.apply_theme(a, theme.DARK)


def _window_is_dark(a) -> bool:
    return a.palette().color(QPalette.Window).lightness() < 128


def test_mode_resolution():
    L, D, U = Qt.ColorScheme.Light, Qt.ColorScheme.Dark, Qt.ColorScheme.Unknown
    assert theme.is_dark(theme.SYSTEM, L) is False
    assert theme.is_dark(theme.SYSTEM, D) is True
    # A desktop that says nothing keeps IngeTrazo's historic dark chrome.
    assert theme.is_dark(theme.SYSTEM, U) is True
    for scheme in (L, D, U):
        assert theme.is_dark(theme.LIGHT, scheme) is False
        assert theme.is_dark(theme.DARK, scheme) is True


def test_dark_is_the_default(app):
    # Marco, 2026-09-22: IngeTrazo opens dark; light or «same as the
    # system» is the user's choice.
    from PySide6.QtCore import QSettings
    QSettings().remove("General/theme")
    QSettings().remove("general/theme")
    assert theme.saved_theme() == theme.DARK
    theme.save_theme("sepia")
    assert theme.saved_theme() == theme.DARK


def test_pinned_modes_set_the_palette(app):
    assert theme.apply_theme(app, theme.LIGHT) is False
    assert not _window_is_dark(app)
    assert theme.apply_theme(app, theme.DARK) is True
    assert _window_is_dark(app)


def test_both_palettes_define_the_shades_stylesheets_use():
    # palette(mid)/palette(midlight) in the tray and the sidebar handle; a
    # role left unset would come from the platform theme instead.
    for pal, dark in ((theme.dark_palette(), True),
                      (theme.light_palette(), False)):
        for role in (QPalette.Light, QPalette.Midlight, QPalette.Mid,
                     QPalette.Dark, QPalette.Shadow):
            assert pal.isBrushSet(QPalette.Active, role)
        text = pal.color(QPalette.WindowText).lightness()
        window = pal.color(QPalette.Window).lightness()
        assert (text > window) is dark


def test_muted_template_follows_the_theme(app):
    lbl = QLabel("hint")
    theme.style(lbl, "color:{muted}; font-size:11px;")
    theme.apply_theme(app, theme.LIGHT)
    on_light = lbl.styleSheet()
    theme.apply_theme(app, theme.DARK)
    on_dark = lbl.styleSheet()
    assert on_light != on_dark
    assert "{muted}" not in on_light and "{muted}" not in on_dark


def test_a_sheet_with_palette_refs_repaints_after_a_switch(app):
    # The tray headers stayed light grey on the light theme until the sheet
    # was re-polished: the text colour is resolved once, at polish time.
    theme.apply_theme(app, theme.DARK)
    host = QWidget()
    btn = QToolButton(host)
    btn.setText("Capas")
    btn.setStyleSheet("QToolButton { border-bottom: 1px solid palette(mid); }")
    host.show()
    app.processEvents()
    dark_ink = btn.palette().color(QPalette.ButtonText).lightness()
    theme.apply_theme(app, theme.LIGHT)
    app.processEvents()
    light_ink = btn.palette().color(QPalette.ButtonText).lightness()
    assert dark_ink > 128 > light_ink
    host.close()


def test_tagged_icons_are_redrawn_in_the_new_ink(app):
    theme.apply_theme(app, theme.DARK)
    host = QWidget()
    btn = QToolButton(host)
    from views.icons import tool_icon
    btn.setIcon(tool_icon("select"))
    btn.setProperty("icon_key", "select")
    before = btn.icon().cacheKey()
    theme.apply_theme(app, theme.LIGHT)
    assert btn.icon().cacheKey() != before
    host.close()


def test_system_mode_follows_a_desktop_flip(app, monkeypatch):
    theme.save_theme(theme.SYSTEM)
    monkeypatch.setattr(theme, "_system_scheme",
                        lambda _a: Qt.ColorScheme.Light)
    theme.apply_theme(app)
    assert not _window_is_dark(app)
    # The desktop goes dark: the follower re-applies the saved mode.
    monkeypatch.setattr(theme, "_system_scheme",
                        lambda _a: Qt.ColorScheme.Dark)
    theme._follower.on_scheme(Qt.ColorScheme.Dark)
    assert _window_is_dark(app)


def test_a_pinned_mode_ignores_the_desktop(app, monkeypatch):
    theme.save_theme(theme.LIGHT)
    theme.apply_theme(app)
    monkeypatch.setattr(theme, "_system_scheme",
                        lambda _a: Qt.ColorScheme.Dark)
    theme._follower.on_scheme(Qt.ColorScheme.Dark)
    assert not _window_is_dark(app)
