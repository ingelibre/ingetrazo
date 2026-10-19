# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Extensions installed by hand, as every one was before the manager (0.5.8).

A user who copied «planarq» into the plugins folder under 0.5.7 opened the
0.5.8 manager and was stuck: its catalog card said «A plugin with this ID
already exists» with no way to uninstall, disable or update it, and a plugin
the catalog does not know did not show at all. Now both can be uninstalled
from the manager — set aside, renamed with a dot in front, never deleted —
and a catalog one can be replaced by the catalog version.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

from core import extension_manager as manager
from core.extensions import discover_plugins
from tests.test_extension_manager import (
    TOOL_SOURCE, _extension, _stub_catalog, _wait_for_catalog)


def _hand_package(root, name, source=TOOL_SOURCE):
    folder = root / name
    folder.mkdir()
    (folder / "__init__.py").write_text(source)
    return folder


def _loaded(root):
    return sorted(p.stem for p in discover_plugins([root])[0])


def test_hand_installed_plugins_are_the_ones_the_manager_did_not_install(
        tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    _hand_package(tmp_path, "aberturas")
    (tmp_path / "niveles.py").write_text(TOOL_SOURCE)
    managed = _hand_package(tmp_path, "kitchen")
    (managed / "extension.json").write_text('{"id": "kitchen"}')
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "notes").mkdir()                       # no __init__.py
    _hand_package(tmp_path, ".planarq.manual-20261001-120000")
    names = [manager.hand_installed_ident(p)
             for p in manager.hand_installed_plugins()]
    assert names == ["aberturas", "niveles"]


def test_uninstalling_a_hand_copy_sets_it_aside_and_keeps_its_files(
        tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    folder = _hand_package(tmp_path, "aberturas")
    assert _loaded(tmp_path) == ["aberturas"]

    aside = manager.remove_hand_installed(folder)

    assert not folder.exists()
    assert aside.name.startswith(".aberturas.manual-")
    assert (aside / "__init__.py").read_text() == TOOL_SOURCE   # kept
    assert _loaded(tmp_path) == []                   # no longer loaded
    assert manager.hand_installed_plugins() == []


def test_a_managed_or_outside_folder_is_never_set_aside_as_hand_installed(
        tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    managed = _hand_package(tmp_path, "kitchen")
    (managed / "extension.json").write_text('{"id": "kitchen"}')
    outside = tmp_path.parent / "elsewhere.py"
    outside.write_text("x")
    for path in (managed, outside):
        with pytest.raises(manager.ExtensionManagerError):
            manager.remove_hand_installed(path)
    assert managed.exists() and outside.exists()


def test_a_hand_copy_is_replaced_by_the_catalog_version(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    (tmp_path / "sample.py").write_text("# the 0.5.7 copy\n")
    source = TOOL_SOURCE.encode()
    monkeypatch.setattr(manager, "_get", lambda *_args: source)

    moved = manager.replace_hand_installed(_extension(source))

    assert [p.name.startswith(".sample.py.manual-") for p in moved] == [True]
    assert moved[0].read_text() == "# the 0.5.7 copy\n"
    assert manager.installed_info("sample")["version"] == "1.0"
    assert _loaded(tmp_path) == ["sample"]
    manager.uninstall_extension("sample")            # managed from now on
    assert not (tmp_path / "sample").exists()


def test_a_failed_replacement_puts_the_hand_copy_back(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    folder = _hand_package(tmp_path, "sample", "# mine\n")
    monkeypatch.setattr(manager, "_get", lambda *_args: b"tampered")
    with pytest.raises(manager.ExtensionManagerError, match="Checksum"):
        manager.replace_hand_installed(_extension(b"expected"))
    assert (folder / "__init__.py").read_text() == "# mine\n"
    assert [p.name for p in tmp_path.iterdir()] == ["sample"]


def _dialog(monkeypatch, tmp_path, extensions):
    app = QApplication.instance() or QApplication([])
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, extensions)
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    dialog = dialog_module.ExtensionManagerDialog()
    _wait_for_catalog(dialog, app)
    dialog._tabs.setCurrentIndex(1)                  # Installed
    dialog._render_page("installed")
    return app, dialog


def _rows(dialog):
    grid = dialog._pages["installed"]["grid"]
    return [grid.itemAt(i).widget() for i in range(grid.count())]


def _texts(row, kind):
    return [w.text() for w in row.findChildren(kind)]


def test_a_catalog_extension_installed_by_hand_offers_replace_and_uninstall(
        tmp_path, monkeypatch):
    (tmp_path / "sample.py").write_text("# the 0.5.7 copy\n")
    app, dialog = _dialog(monkeypatch, tmp_path, [_extension(b"catalog")])
    try:
        rows = _rows(dialog)
        assert len(rows) == 1                        # in the Installed tab
        buttons = _texts(rows[0], QPushButton)
        assert "Replace with the catalog version" in buttons
        assert "Uninstall" in buttons
        assert "Download" not in buttons
        assert any("Installed by hand" in text
                   for text in _texts(rows[0], QLabel))
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_a_hand_plugin_the_catalog_does_not_know_can_be_uninstalled(
        tmp_path, monkeypatch):
    folder = _hand_package(tmp_path, "aberturas")
    app, dialog = _dialog(monkeypatch, tmp_path, [_extension(b"catalog")])
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: QMessageBox.Ok))
    try:
        rows = _rows(dialog)
        assert len(rows) == 1
        assert "aberturas" in _texts(rows[0], QLabel)
        uninstall = next(b for b in rows[0].findChildren(QPushButton)
                         if b.text() == "Uninstall")
        uninstall.click()
        app.processEvents()
        assert not folder.exists()
        assert any(p.name.startswith(".aberturas.manual-")
                   for p in tmp_path.iterdir())
        assert _rows(dialog) == []                   # gone from the list
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_an_extension_shipped_with_the_app_installs_from_the_manager(
        tmp_path, monkeypatch):
    # Windowizer ships inside IngeTrazo and is not in the catalog: its card
    # says «Included with IngeTrazo», installs from the local copy (nothing
    # downloaded) and is managed from then on. A bundled one the catalog
    # also lists (Levels) shows once, as the catalog's.
    bundled = manager.Extension(**{
        **_extension(b"x", "windowizer").__dict__,
        "name": {"en": "Windowizer"}, "license": "", "repository": "",
        "download": "", "bundled": str(tmp_path / "src.py")})
    (tmp_path / "src.py").write_text(TOOL_SOURCE)
    twin = manager.Extension(**{**_extension(b"x", "niveles").__dict__,
                                "bundled": str(tmp_path / "src.py")})
    app = QApplication.instance() or QApplication([])
    from views import extension_manager_dialog as dialog_module
    catalog = [_extension(b"catalog", "niveles")]
    _stub_catalog(monkeypatch, dialog_module, catalog)
    monkeypatch.setattr(dialog_module, "bundled_extensions",
                        lambda: [bundled, twin])
    plugins = tmp_path / "plugins"
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: plugins)
    monkeypatch.setattr(manager, "_get", lambda *_a: (_ for _ in ()).throw(
        AssertionError("a bundled extension must not download")))
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        assert [e.id for e in dialog._extensions] == ["niveles", "windowizer"]
        grid = dialog._pages["browse"]["grid"]
        row = grid.itemAt(1).widget()
        labels = _texts(row, QLabel)
        assert "Included with IngeTrazo" in labels
        assert "INCLUDED" in labels
        assert not any("Community extension" in text for text in labels)
        assert "Install" in _texts(row, QPushButton)
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
    manager.install_extension(bundled)
    assert (plugins / "windowizer" / "__init__.py").read_text() == TOOL_SOURCE
    assert manager.installed_info("windowizer") is not None


def test_the_cards_take_as_many_columns_as_the_width_fits(
        tmp_path, monkeypatch):
    # Marco, 09-10: maximised, two fixed columns left an empty band at the
    # right. One column when narrow, two at the usual size, three on a
    # maximised Full HD window — moved, not rebuilt, on resize.
    extensions = [_extension(f"s{i}".encode(), f"ext_{i}") for i in range(7)]
    app = QApplication.instance() or QApplication([])
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, extensions)
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        dialog.show()
        grid = dialog._pages["browse"]["grid"]
        for width, columns in ((700, 1), (1180, 2), (1920, 3)):
            dialog.resize(width, 800)
            app.processEvents()
            used = {grid.getItemPosition(i)[1] for i in range(grid.count())}
            assert used == set(range(columns)), (width, used)
            assert grid.count() == len(extensions)
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_an_included_extension_shows_its_own_preview_and_a_translated_line(
        tmp_path, monkeypatch):
    from core import paths
    from core.i18n import current_language
    root = tmp_path / "app"
    examples = root / "examples" / "extensions"
    examples.mkdir(parents=True)
    # encoding: the «—» is cp1252 on Windows otherwise, and the manager
    # reads extensions as UTF-8 like Python does.
    (examples / "demo.py").write_text(
        '"""Demo — parametric windows from selected faces.\n\nHow to."""\n',
        encoding="utf-8")
    (examples / "demo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(paths, "app_root", lambda: root)
    demo, = manager.bundled_extensions()
    assert demo.screenshot == str(examples / "demo.png")
    assert demo.summary["en"] == "Parametric windows from selected faces."
    lang = current_language().split("-")[0]
    assert lang in demo.summary            # what the card shows, via tr()
