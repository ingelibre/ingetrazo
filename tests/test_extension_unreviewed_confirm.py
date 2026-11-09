# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Installing an extension nobody reviewed asks first, with No as the
default: it is its author's Python code, run with the user's permissions.
The card already said «not reviewed»; one click was enough to install it."""
from __future__ import annotations

import hashlib

from PySide6.QtWidgets import QApplication, QMessageBox

from core import extension_manager as manager
from tests.test_extension_manager import (
    _extension, _stub_catalog, _wait_for_catalog)

SOURCE = b"def setup(app):\n    pass\n"


def _open(monkeypatch, tmp_path, reviewed):
    app = QApplication.instance() or QApplication([])
    from views import extension_manager_dialog as dialog_module
    extension = _extension(SOURCE)
    _stub_catalog(monkeypatch, dialog_module, [extension],
                  {"sample": {"sha256": extension.sha256}} if reviewed else {})
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    monkeypatch.setattr(manager, "_get", lambda *_a: SOURCE)
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: QMessageBox.Ok))
    dialog = dialog_module.ExtensionManagerDialog()
    _wait_for_catalog(dialog, app)
    return app, dialog, extension


def _asked(monkeypatch, answer):
    asked = []

    def warning(parent, title, text, buttons, default):
        asked.append((title, text, default))
        return answer
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(warning))
    return asked


def _close(app, dialog):
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_an_unreviewed_extension_asks_and_no_installs_nothing(
        tmp_path, monkeypatch):
    app, dialog, extension = _open(monkeypatch, tmp_path, reviewed=False)
    asked = _asked(monkeypatch, QMessageBox.No)
    try:
        dialog._install(extension)
        assert len(asked) == 1
        title, text, default = asked[0]
        assert "unreviewed" in title
        assert "Author" in text                     # who they would trust
        assert default == QMessageBox.No
        assert manager.installed_info("sample") is None
    finally:
        _close(app, dialog)


def test_an_unreviewed_extension_installs_once_the_user_says_yes(
        tmp_path, monkeypatch):
    app, dialog, extension = _open(monkeypatch, tmp_path, reviewed=False)
    asked = _asked(monkeypatch, QMessageBox.Yes)
    try:
        dialog._install(extension)
        assert len(asked) == 1
        info = manager.installed_info("sample")
        assert info and info["sha256"] == hashlib.sha256(SOURCE).hexdigest()
    finally:
        _close(app, dialog)


def test_a_reviewed_extension_installs_without_asking(tmp_path, monkeypatch):
    app, dialog, extension = _open(monkeypatch, tmp_path, reviewed=True)
    asked = _asked(monkeypatch, QMessageBox.No)
    try:
        dialog._install(extension)
        assert asked == []
        assert manager.installed_info("sample") is not None
    finally:
        _close(app, dialog)


def test_a_bundled_extension_installs_without_asking(tmp_path, monkeypatch):
    app, dialog, extension = _open(monkeypatch, tmp_path, reviewed=False)
    # The shipped copy lives with the app, not in the plugins folder (there
    # the manager would rightly take it for a copy installed by hand).
    shipped = tmp_path.parent / (tmp_path.name + "-app")
    shipped.mkdir()
    src = shipped / "src.py"
    src.write_bytes(SOURCE)
    bundled = manager.Extension(**{**extension.__dict__, "download": "",
                                   "bundled": str(src)})
    asked = _asked(monkeypatch, QMessageBox.No)
    try:
        dialog._install(bundled)
        assert asked == []
        assert manager.installed_info("sample") is not None
    finally:
        _close(app, dialog)
