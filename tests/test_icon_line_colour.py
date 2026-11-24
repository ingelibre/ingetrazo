# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Preferences ▸ General ▸ Icon line colour, and the size of the Make
Faces, Make Faces and Extrude and Two-point perspective icons.

«Automatic» — the default — keeps the theme's grey for the icons' lines,
exactly as before; any other choice paints them in that colour on every
theme, and applies at once like the accent. The three icons used to come
out smaller than their neighbours on the bar: their face (the accent
fill) is now as large as the others'.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

import views.preferences_dialog as prefs_mod  # noqa: E402
from views import theme  # noqa: E402
from views.icons import tool_icon  # noqa: E402


def _count(icon, colour: QColor, tol: int = 14) -> int:
    """Opaque pixels of ``icon`` (at 48 px) close to ``colour``."""
    image = icon.pixmap(48, 48).toImage()
    n = 0
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if (c.alpha() > 200 and abs(c.red() - colour.red()) < tol
                    and abs(c.green() - colour.green()) < tol
                    and abs(c.blue() - colour.blue()) < tol):
                n += 1
    return n


def _face_area(key: str) -> int:
    """Pixels of ``key``'s icon in the accent's hue, the faces it fills
    and its accent points: how large its subject is drawn."""
    image = tool_icon(key).pixmap(48, 48).toImage()
    hue = theme.accent_color().hsvHue()
    n = 0
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if (c.alpha() > 60 and c.hsvSaturation() > 80
                    and c.hsvHue() >= 0 and abs(c.hsvHue() - hue) < 15):
                n += 1
    return n


@pytest.fixture
def keep_ink():
    app = QApplication.instance()
    before = theme.saved_icon_ink()
    yield app
    theme.save_icon_ink(before)
    theme.apply_accent(app)


# ---- the setting --------------------------------------------------------------

def test_automatic_is_the_default_and_is_the_theme_grey(keep_ink):
    theme.save_icon_ink(theme.AUTO_ICON_INK)
    assert theme.saved_icon_ink() == theme.AUTO_ICON_INK
    assert theme.icon_ink() == theme.theme_icon_ink()
    assert theme.ICON_INK_CHOICES[0][0] == theme.AUTO_ICON_INK


def test_every_choice_has_a_colour_and_a_bad_one_falls_back(keep_ink):
    for key, _label, _rgb in theme.ICON_INK_CHOICES:
        assert theme.icon_ink(key).isValid()
    theme.save_icon_ink("not a colour")
    assert theme.saved_icon_ink() == theme.AUTO_ICON_INK


def test_automatic_still_follows_the_theme(keep_ink):
    theme.save_icon_ink(theme.AUTO_ICON_INK)
    key = theme._grip_key
    try:
        theme._grip_key = theme.DARK
        dark = theme.icon_ink()
        theme._grip_key = theme.LIGHT
        light = theme.icon_ink()
    finally:
        theme._grip_key = key
    assert dark == QColor(theme.ICON_INKS[theme.DARK])
    assert light == QColor(theme.ICON_INKS[theme.LIGHT])
    assert dark != light


def test_a_chosen_colour_paints_the_icon_lines(keep_ink):
    app = keep_ink
    theme.save_icon_ink(theme.AUTO_ICON_INK)
    theme.apply_accent(app)
    grey = theme.theme_icon_ink()
    assert _count(tool_icon("offset"), grey) > 50
    blue = theme.icon_ink("blue")
    theme.save_icon_ink("blue")
    theme.apply_accent(app)
    assert _count(tool_icon("offset"), blue) > 50
    assert _count(tool_icon("offset"), grey) == 0
    # The accent's dots stay the accent.
    assert _count(tool_icon("line"), theme.accent_color()) > 0


def test_a_chosen_colour_holds_on_every_theme(keep_ink):
    theme.save_icon_ink("purple")
    key = theme._grip_key
    try:
        theme._grip_key = theme.LIGHT
        assert theme.icon_ink() == theme.icon_ink("purple")
        theme._grip_key = theme.DARK
        assert theme.icon_ink() == theme.icon_ink("purple")
    finally:
        theme._grip_key = key


# ---- Preferences ---------------------------------------------------------------

@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "prefs.ini"
    monkeypatch.setattr(
        prefs_mod, "QSettings",
        lambda: QSettings(str(path), QSettings.IniFormat))
    return path


class _Win(QWidget):
    def __init__(self):
        super().__init__()

        class _VP:
            edit_rest_mode = "fade"
            edit_rest_fade = 0.75

            def set_edit_rest_mode(self, mode):
                self.edit_rest_mode = mode

            def set_edit_rest_fade(self, strength):
                self.edit_rest_fade = strength

        self.viewport = _VP()
        self._rest_actions = {}
        self.refreshed = 0

    def _refresh_toolbar_icons(self):
        self.refreshed += 1


def test_preferences_offer_it_after_the_accent_and_apply_it(settings_file,
                                                             keep_ink):
    theme.save_icon_ink(theme.AUTO_ICON_INK)
    win = _Win()
    dlg = prefs_mod.PreferencesDialog(win)
    assert dlg._icon_ink.currentData() == theme.AUTO_ICON_INK
    assert dlg._icon_ink.count() == len(theme.ICON_INK_CHOICES)
    dlg._icon_ink.setCurrentIndex(dlg._icon_ink.findData("green"))
    dlg.accept()
    assert theme.saved_icon_ink() == "green"
    assert win.refreshed >= 1                 # the bars were drawn again
    again = prefs_mod.PreferencesDialog(win)
    assert again._icon_ink.currentData() == "green"
    again.restore_defaults()
    assert again._icon_ink.currentData() == theme.AUTO_ICON_INK


# ---- the three icons' size -------------------------------------------------------

def test_make_faces_is_drawn_as_large_as_the_projection_boxes():
    assert _face_area("make_faces") >= _face_area("proj_perspective")


def test_make_faces_and_extrude_is_as_large_as_push_pull():
    assert _face_area("make_faces_extrude") >= _face_area("pushpull")


def test_two_point_box_is_as_large_as_the_perspective_one():
    assert _face_area("proj_two_point") >= _face_area("proj_perspective")


# ---- 4K screens ----------------------------------------------------------------

class _Screen:
    def __init__(self, dpr):
        self._dpr = dpr

    def devicePixelRatio(self):
        return self._dpr


@pytest.mark.parametrize("dpr, sizes", [
    (1.0, [48]), (1.25, [48, 96]), (2.0, [48, 96]),
    (3.0, [48, 96, 144]), (4.0, [48, 96, 144, 192])])
def test_icons_are_drawn_big_enough_for_the_screen(monkeypatch, dpr, sizes):
    """A 40 px icon on a 4K screen at 300 % shows 120 device pixels: it
    is drawn at 144 px, never stretched from the 48 px drawing."""
    from PySide6.QtGui import QGuiApplication
    monkeypatch.setattr(QGuiApplication, "screens",
                        staticmethod(lambda: [_Screen(1.0), _Screen(dpr)]))
    icon = tool_icon("make_faces")
    assert sorted(s.width() for s in icon.availableSizes()) == sizes
    big = icon.pixmap(sizes[-1], sizes[-1])
    assert big.width() == sizes[-1]


def test_the_big_drawing_is_the_small_one_scaled(monkeypatch):
    """The 144 px drawing is the 48 px one with three times the pixels:
    the same ink, in the same place, at the same weight."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtCore import Qt as _Qt
    monkeypatch.setattr(QGuiApplication, "screens",
                        staticmethod(lambda: [_Screen(3.0)]))
    icon = tool_icon("proj_two_point")
    small = icon.pixmap(48, 48).toImage()
    big = icon.pixmap(144, 144).toImage().scaled(
        48, 48, _Qt.IgnoreAspectRatio, _Qt.SmoothTransformation)
    diff = 0
    for y in range(48):
        for x in range(48):
            diff += abs(small.pixelColor(x, y).alpha()
                        - big.pixelColor(x, y).alpha())
    assert diff / (48 * 48) < 12


# ---- Apply ---------------------------------------------------------------------

def test_apply_saves_and_keeps_preferences_open(settings_file, keep_ink):
    """Apply: the change takes effect at once and the dialog stays open,
    so several colours can be tried one after another."""
    from PySide6.QtWidgets import QDialogButtonBox
    theme.save_icon_ink(theme.AUTO_ICON_INK)
    win = _Win()
    dlg = prefs_mod.PreferencesDialog(win)
    dlg.show()
    apply_btn = dlg._buttons.button(QDialogButtonBox.Apply)
    assert apply_btn is not None and apply_btn is dlg._apply_btn
    assert not apply_btn.autoDefault()        # Enter stays OK
    for colour in ("blue", "red"):
        dlg._icon_ink.setCurrentIndex(dlg._icon_ink.findData(colour))
        apply_btn.click()
        assert theme.saved_icon_ink() == colour
        assert dlg.isVisible()                 # still open
        assert dlg.result() == 0
    refreshed = win.refreshed
    apply_btn.click()                          # nothing new: nothing redrawn
    assert win.refreshed == refreshed
    dlg.close()
