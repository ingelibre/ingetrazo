# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Help ▸ What's New, and the link beside the version in About IngeTrazo,
open the release notes of every version; their texts exist in every
language."""
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

_app = QApplication.instance() or QApplication([])

RELEASES = "https://github.com/ingelibre/ingetrazo/releases"
WHATS_NEW = "What's New"


def test_releases_page_is_the_github_one():
    from core.update_check import RELEASES_PAGE
    assert RELEASES_PAGE == RELEASES


def test_help_whats_new_opens_the_releases_page(monkeypatch):
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
        texts = [a.text() for a in help_menu.actions()]
        # Right below Documentation, with the other web page.
        assert texts.index(tr(WHATS_NEW)) == texts.index(tr("Documentation")) + 1
        act = next(a for a in help_menu.actions()
                   if a.text() == tr(WHATS_NEW))
        assert act.objectName() == "whats_new"
        act.trigger()
        assert opened == [RELEASES]
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_about_links_whats_new_beside_the_version():
    from views.about_dialog import AboutDialog
    from core.i18n import tr
    dlg = AboutDialog(None, "9.8.7")
    try:
        head = next(lab for lab in dlg.findChildren(QLabel)
                    if "9.8.7" in lab.text())
        link = f"<a href='{RELEASES}'>{tr(WHATS_NEW)}</a>"
        assert link in head.text()
        assert head.openExternalLinks()
    finally:
        dlg.close()


def test_whats_new_texts_translated_everywhere():
    keys = (WHATS_NEW, "See what changed in each version of IngeTrazo.")
    root = Path(__file__).resolve().parent.parent / "i18n"
    for f in sorted(root.glob("*.json")):
        if f.stem == "en":
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        for k in keys:
            assert data.get(k), f"{f.name}: {k!r}"
