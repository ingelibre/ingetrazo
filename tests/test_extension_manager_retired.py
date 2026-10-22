# SPDX-License-Identifier: GPL-3.0-or-later
"""An extension the manager installed whose id left the catalog (#611).

ArchXQ IT was renamed ``archxq_it_lite`` in the catalog: anyone who had
installed ``archxq_it`` kept its folder, which the manager no longer listed
(no catalog card, not hand-installed) and still loaded, so installing the
replacement loaded both. Now such a folder is listed on its own, can be
disabled and uninstalled, and installing the replacement offers to set it
aside.
"""
from __future__ import annotations

import json

from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton

from core import extension_manager as manager
from core.extensions import discover_plugins
from tests.test_extension_manager import TOOL_SOURCE, _extension
from tests.test_extension_manager_hand_installed import (
    _dialog, _hand_package, _rows, _texts)


def _managed(root, ident, version="1.0"):
    folder = root / ident
    folder.mkdir()
    (folder / "__init__.py").write_bytes(TOOL_SOURCE.encode())   # no CRLF
    (folder / "extension.json").write_text(
        json.dumps({"id": ident, "version": version}))
    return folder


def _loaded(root):
    return sorted(p.stem for p in discover_plugins([root])[0])


def test_retired_extensions_are_the_managed_folders_the_catalog_dropped(
        tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    _managed(tmp_path, "archxq_it")
    _managed(tmp_path, "kitchen")                     # still in the catalog
    _hand_package(tmp_path, "aberturas")              # not managed
    (tmp_path / "notes").mkdir()
    _managed(tmp_path, ".old.manual-20261001-120000")
    retired = manager.retired_extensions(["kitchen", "archxq_it_lite"])
    assert [p.name for p in retired] == ["archxq_it"]


def test_installing_the_replacement_sets_the_retired_copy_aside(
        tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    old = _managed(tmp_path, "archxq_it")
    source = TOOL_SOURCE.encode()
    monkeypatch.setattr(manager, "_get", lambda *_args: source)
    new = _extension(source, "archxq_it_lite")
    asked = []

    def confirm(paths):
        asked.append([p.name for p in paths])
        return True

    manager.install_extension(new, confirm, catalog_ids=["archxq_it_lite"])

    assert asked == [["archxq_it"]]
    assert not old.exists()
    assert (tmp_path / "archxq_it_lite").is_dir()
    assert _loaded(tmp_path) == ["archxq_it_lite"]


def test_a_sibling_the_catalog_still_lists_is_not_taken_for_a_copy(
        tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    _managed(tmp_path, "archxq_it")
    source = TOOL_SOURCE.encode()
    monkeypatch.setattr(manager, "_get", lambda *_args: source)
    new = _extension(source, "archxq_it_lite")
    manager.install_extension(
        new, lambda paths: False, catalog_ids=["archxq_it", "archxq_it_lite"])
    assert _loaded(tmp_path) == ["archxq_it", "archxq_it_lite"]


def test_the_manager_lists_a_retired_extension_and_uninstalls_it(
        tmp_path, monkeypatch):
    folder = _managed(tmp_path, "archxq_it", "2.3")
    app, dialog = _dialog(monkeypatch, tmp_path, [_extension(b"catalog")])
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: QMessageBox.Ok))
    try:
        rows = _rows(dialog)
        assert len(rows) == 1
        labels = _texts(rows[0], QLabel)
        assert "archxq_it" in labels
        assert any("No longer in the catalog" in text and "2.3" in text
                   for text in labels)
        buttons = _texts(rows[0], QPushButton)
        assert "Disable" in buttons and "Uninstall" in buttons
        next(b for b in rows[0].findChildren(QPushButton)
             if b.text() == "Disable").click()
        assert (folder / ".disabled").is_file()
        assert _loaded(tmp_path) == []
        next(b for b in _rows(dialog)[0].findChildren(QPushButton)
             if b.text() == "Uninstall").click()
        app.processEvents()
        assert not folder.exists()
        assert _rows(dialog) == []
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
