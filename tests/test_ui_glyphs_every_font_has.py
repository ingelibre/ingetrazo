# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The panels built at start-up write only characters every interface font
has (#658).

The 0.5.8 Flatpak died at start-up, on one machine, while building the
Browser: its buttons were the characters ◎ ⊞, which few interface fonts
have, so Qt went looking through fontconfig for one that does — the same
fallback where #279 died on a broken user font. Drawn icons need no font.
Latin-1 and the usual typographic marks (— – … ‘ ’ “ ” • ‹ ›) are in every
font; anything else on a button or a label built at start-up is a risk."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel  # noqa: E402

_app = QApplication.instance() or QApplication([])
_SAFE = set("—–…‘’“”•‹›")


def _risky(widget) -> set:
    out = set()
    for cls in (QAbstractButton, QLabel):
        for w in widget.findChildren(cls):
            out |= {ch for ch in w.text() if ord(ch) > 0xFF
                    and ch not in _SAFE}
    return out


def test_the_browser_writes_no_character_a_font_may_lack():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        assert _risky(win.project_browser) == set()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_floating_toolbar_s_close_button_needs_no_rare_character():
    from PySide6.QtWidgets import QMainWindow, QToolBar
    from views.floating_toolbar import watch_toolbars
    win = QMainWindow()
    tb = QToolBar("Draw", win)
    win.addToolBar(tb)
    watch_toolbars(win)
    assert _risky(tb) == set()
