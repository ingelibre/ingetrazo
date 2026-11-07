# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Preferences ▸ General ▸ Accent colour (#393): the icons' dots and the
toolbar hovers follow it; orange stays the default."""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QToolButton

from views import theme
from views.icons import tool_icon

ORANGE = QColor(243, 115, 41)


def _has(icon, colour: QColor) -> bool:
    image = icon.pixmap(48, 48).toImage()
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if (c.alpha() > 200 and abs(c.red() - colour.red()) < 12
                    and abs(c.green() - colour.green()) < 12
                    and abs(c.blue() - colour.blue()) < 12):
                return True
    return False


def test_orange_is_the_default_and_every_choice_has_a_colour():
    QApplication.instance() or QApplication([])
    assert theme.saved_accent() == theme.ORANGE
    assert theme.accent_color() == ORANGE
    for key, _label, _rgb in theme.ACCENTS:
        assert theme.accent_color(key).isValid()
    theme.save_accent("not a colour")
    try:
        assert theme.saved_accent() == theme.ORANGE
    finally:
        theme.save_accent(theme.ORANGE)


def test_the_icons_and_the_toolbar_hover_follow_the_accent():
    app = QApplication.instance() or QApplication([])
    button = QToolButton()
    theme.style(button, "QToolButton:hover {{ background: "
                        "rgb({accent_rgb}); }}")
    assert "rgb(243, 115, 41)" in button.styleSheet()
    assert _has(tool_icon("line"), ORANGE)
    blue = theme.accent_color("blue")
    try:
        theme.save_accent("blue")
        theme.apply_accent(app)
        assert "rgb(53, 132, 228)" in button.styleSheet()
        assert _has(tool_icon("line"), blue)
        assert not _has(tool_icon("line"), ORANGE)
    finally:
        theme.save_accent(theme.ORANGE)
        theme.apply_accent(app)
    assert "rgb(243, 115, 41)" in button.styleSheet()


def test_the_system_accent_is_a_real_colour():
    app = QApplication.instance() or QApplication([])
    theme._remember_system_accent(app)
    assert theme.accent_color(theme.SYSTEM_ACCENT).isValid()
