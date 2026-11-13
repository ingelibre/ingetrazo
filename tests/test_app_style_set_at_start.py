# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The session's QApplication wears the app's style from the start, as the
app does: a later setStyle walks every widget alive and, mid-batch, met one
whose C++ half was gone (SIGSEGV in QApplication::setStyle, 12-11)."""
from PySide6.QtWidgets import QApplication

from views import theme


def test_the_style_is_already_the_apps():
    assert isinstance(QApplication.instance().style(), theme.ChromeStyle)


def test_applying_a_theme_does_not_set_the_style_again(monkeypatch):
    app = QApplication.instance()
    calls = []
    monkeypatch.setattr(app, "setStyle", calls.append)
    theme.apply_theme(app, theme.DARK)
    assert calls == []
