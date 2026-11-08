# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Help ▸ Documentation opens the online manual (#1036), at the address the
manual is really published on, and its texts exist in every language."""
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_help_documentation_opens_the_manual(monkeypatch):
    from PySide6.QtGui import QDesktopServices
    from views.main_window import MainWindow
    from core.i18n import tr
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toString()) or True))
    win = MainWindow()
    try:
        help_menu = next(a.menu() for a in win.menuBar().actions()
                         if a.text() == tr("Help"))
        act = next(a for a in help_menu.actions()
                   if a.text() == tr("Documentation"))
        act.trigger()
        assert opened == ["https://ingetrazo-docs.pages.dev/"]
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_documentation_texts_translated_everywhere():
    keys = ("Documentation",
            "Open the IngeTrazo documentation in the web browser.")
    root = Path(__file__).resolve().parent.parent / "i18n"
    for f in sorted(root.glob("*.json")):
        if f.stem == "en":
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        for k in keys:
            assert data.get(k), f"{f.name}: {k!r}"
