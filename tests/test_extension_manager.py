# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile

import pytest
from PySide6.QtCore import QBuffer, QEventLoop, QIODevice, QObject, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QPushButton,
    QToolButton,
    QWidget,
)

from core import extension_manager as manager
from core.extensions import discover_plugins
from views.theme import dark_palette


TOOL_SOURCE = """
from tools.base import Tool

class CatalogTool(Tool):
    name = "Catalog tool"
    def on_activate(self, viewport):
        pass
    def on_deactivate(self, viewport):
        pass
"""


def _extension(payload: bytes, ident="sample") -> manager.Extension:
    return manager.Extension(
        id=ident,
        version="1.0",
        author="Author",
        license="MIT",
        repository="https://github.com/example/sample",
        download="https://example.org/sample.py",
        sha256=hashlib.sha256(payload).hexdigest(),
        minimum_version="0.1.0",
        name={"en": "Sample"},
        summary={"en": "Example extension"},
        tags=(),
    )


def _stub_catalog(monkeypatch, module, extensions, reviewed=None):
    snapshot = manager.CatalogSnapshot(
        extensions, reviewed or {}, "2026-10-07T10:00:00+00:00", False)
    monkeypatch.setattr(module, "load_cached_catalog", lambda: snapshot)
    monkeypatch.setattr(module, "refresh_catalog", lambda: snapshot)
    monkeypatch.setattr(module, "load_extension_sources", lambda: [])
    if hasattr(module, "bundled_extensions"):
        # Only the catalog under test: the extensions shipped with the app
        # have their own test (test_extension_manager_hand_installed.py).
        monkeypatch.setattr(module, "bundled_extensions", lambda: [])


def _card_rule(row, widget) -> str:
    """The rule a card's widget wears. Cards share one style sheet, set on
    each page's card area (#555: a dozen per card cost 24 ms a card on
    Windows), and each widget is found in it by its object name."""
    from views.extension_manager_dialog import _CARD_RULES
    sheet = row.parentWidget().styleSheet()
    if widget is row:
        selector = ""
    elif widget.objectName():
        selector = f" {type(widget).__name__}#{widget.objectName()}"
    else:
        selector = f" {type(widget).__name__}"
    assert _CARD_RULES[selector] in sheet
    return _CARD_RULES[selector]


def _wait_for_catalog(dialog, app):
    if not dialog.isVisible():
        dialog.resize(1180, 800)
        dialog.show()
        app.processEvents()
    if dialog._catalog_worker is None:
        dialog._load()
    page = dialog._pages["browse"]
    if dialog._catalog_worker is None and not page["dirty"]:
        return
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(
        lambda: loop.quit()
        if (dialog._catalog_worker is None and not page["dirty"]
            and not page["render_timer"].isActive()
            and not page["pending_indices"]) else None)
    timer.start()
    QTimer.singleShot(15000, loop.quit)
    loop.exec()
    timer.stop()
    assert dialog._catalog_worker is None
    assert not page["dirty"]


def _wait_for_page_render(dialog, app, key):
    page = dialog._pages[key]
    if not page["dirty"] and not page["render_timer"].isActive():
        return
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(
        lambda: loop.quit()
        if (not page["dirty"] and not page["render_timer"].isActive()
            and not page["pending_indices"])
        else None)
    timer.start()
    QTimer.singleShot(15000, loop.quit)
    loop.exec()
    timer.stop()
    assert not page["dirty"]


def test_catalog_validation_and_review_uses_the_reviewed_hash(
        tmp_path, monkeypatch):
    source = b"extension source"
    catalog = {
        "format": 1,
        "extensions": [{
            "id": "sample",
            "version": "1.0",
            "author": "Author",
            "license": "MIT",
            "repository": "https://github.com/example/sample",
            "download": "https://example.org/sample.py",
            "sha256": hashlib.sha256(source).hexdigest(),
            "ingetrazo": "0.5.0",
            "name": {"en": "Sample"},
            "summary": {"en": "Description"},
            "tags": [],
            "reviewed": True,
        }],
    }
    monkeypatch.setattr(manager, "catalog_cache_path",
                        lambda: tmp_path / "catalog-cache.json")
    monkeypatch.setattr(
        manager, "_get",
        lambda url, _limit: (json.dumps(catalog).encode() if "catalog" in url
                             else b'[sample]\nsha256 = "'
                             + hashlib.sha256(source).hexdigest().encode()
                             + b'"\n'))
    extensions, reviewed = manager.load_catalog()
    assert manager.is_reviewed(extensions[0], reviewed)
    reviewed["sample"]["sha256"] = "0" * 64
    assert not manager.is_reviewed(extensions[0], reviewed)


def test_custom_catalog_source_is_merged_but_not_marked_reviewed(
        tmp_path, monkeypatch):
    payload = TOOL_SOURCE.encode()
    custom_url = "https://extensions.example/catalog.json"
    custom_catalog = {
        "format": 1,
        "extensions": [{
            "id": "outside",
            "version": "1.0",
            "author": "Author",
            "license": "MIT",
            "repository": "https://example.org/outside",
            "download": "https://extensions.example/outside.py",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "ingetrazo": "0.1.0",
            "name": {"en": "Outside"},
            "summary": {"en": "External source"},
            "tags": [],
        }],
    }
    monkeypatch.setattr(manager, "catalog_cache_path",
                        lambda: tmp_path / "catalog-cache.json")

    def fetch(url, _limit):
        if url == custom_url:
            return json.dumps(custom_catalog).encode()
        if url == manager.CATALOG_URL:
            return b'{"format": 1, "extensions": []}'
        return b""

    monkeypatch.setattr(manager, "_get", fetch)
    source = manager.normalize_extension_source("catalog", custom_url)
    snapshot = manager.refresh_catalog([source])

    assert [extension.id for extension in snapshot.extensions] == ["outside"]
    assert snapshot.extensions[0].source_name == "extensions.example"
    assert not manager.is_reviewed(snapshot.extensions[0], snapshot.reviewed)


def test_local_folder_source_supports_catalog_and_direct_packages(
        tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path / "user")
    package = tmp_path / "packages"
    package.mkdir()
    payload = TOOL_SOURCE.encode()
    (package / "catalog_package.py").write_bytes(payload)
    catalog_source = tmp_path / "catalog-source"
    catalog_source.mkdir()
    local_packages = catalog_source / "packages"
    local_packages.mkdir()
    local_catalog_package = local_packages / "catalog_package"
    local_catalog_package.mkdir()
    (local_catalog_package / "__init__.py").write_bytes(payload)
    catalog_entry = {
        "id": "catalog_package",
        "version": "1.0",
        "author": "Author",
        "license": "MIT",
        "repository": "https://example.org/catalog_package",
        "download": "packages/catalog_package",
        "sha256": manager._bundle_digest(local_catalog_package),
        "ingetrazo": "0.1.0",
        "name": {"en": "Catalog package"},
        "summary": {"en": "Local catalog"},
        "tags": [],
    }
    (catalog_source / "catalog.json").write_text(json.dumps({
        "format": 1, "extensions": [catalog_entry],
    }), encoding="utf-8")
    local_catalog = manager.normalize_extension_source(
        "folder", str(catalog_source))
    catalog_extension = manager._load_custom_source(local_catalog)[0]
    assert catalog_extension.local_path == str(local_catalog_package)
    manager.install_extension(catalog_extension)
    assert (
        (tmp_path / "user" / "catalog_package" / "__init__.py").read_bytes()
        == payload)

    # Relative catalog paths cannot escape their own source directory.
    catalog_entry["download"] = "../packages/catalog_package.py"
    (catalog_source / "catalog.json").write_text(json.dumps({
        "format": 1, "extensions": [catalog_entry],
    }), encoding="utf-8")
    with pytest.raises(manager.ExtensionManagerError, match="outside"):
        manager._load_custom_source(local_catalog)

    local_payloads = tmp_path / "local-source"
    local_payloads.mkdir()
    local_file = local_payloads / "local_package.py"
    local_file.write_bytes(payload)
    zip_path = local_payloads / "zip_package.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("zip_package.py", payload)
    local_package_folder = local_payloads / "local_folder"
    local_package_folder.mkdir()
    (local_package_folder / "__init__.py").write_bytes(payload)
    nested_package = local_payloads / "grouped" / "nested_folder"
    nested_package.mkdir(parents=True)
    (nested_package / "__init__.py").write_bytes(payload)
    local_folder = manager.normalize_extension_source(
        "folder", str(local_payloads))
    extensions = manager._load_custom_source(local_folder)
    by_id = {extension.id: extension for extension in extensions}
    assert set(by_id) == {
        "nested_folder", "local_folder", "local_package", "zip_package"}
    assert by_id["nested_folder"].local_path == str(nested_package)
    assert by_id["local_package"].local_path == str(local_file)
    manager.install_extension(by_id["zip_package"])
    assert (
        (tmp_path / "user" / "zip_package" / "__init__.py").read_bytes()
        == payload)
    assert not manager.is_reviewed(by_id["local_package"], {})


def test_local_sources_reject_oversized_packages_and_malformed_urls(
        tmp_path, monkeypatch):
    package = tmp_path / "large.py"
    package.write_bytes(b"too large")
    monkeypatch.setattr(manager, "MAX_DOWNLOAD_BYTES", 4)
    with pytest.raises(manager.ExtensionManagerError, match="too large"):
        manager._local_extension(package, "local")
    with pytest.raises(manager.ExtensionManagerError, match="valid HTTPS"):
        manager.normalize_extension_source("catalog", "https://[invalid")


def test_catalog_and_reviewed_list_are_fetched_concurrently(
        tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "catalog_cache_path",
                        lambda: tmp_path / "catalog-cache.json")
    both_requests_started = threading.Barrier(2)

    def fetch(url, _limit):
        both_requests_started.wait(timeout=2)
        if "catalog" in url:
            return b'{"format": 1, "extensions": []}'
        return b""

    monkeypatch.setattr(manager, "_get", fetch)
    snapshot = manager.refresh_catalog()
    assert snapshot.extensions == []
    assert not snapshot.from_cache


def test_catalog_is_cached_and_used_when_refresh_is_offline(
        tmp_path, monkeypatch):
    source = b"extension source"
    catalog = {
        "format": 1,
        "extensions": [{
            "id": "sample",
            "version": "1.0",
            "author": "Author",
            "license": "MIT",
            "repository": "https://github.com/example/sample",
            "download": "https://example.org/sample.py",
            "sha256": hashlib.sha256(source).hexdigest(),
            "ingetrazo": "0.5.0",
            "name": {"en": "Sample"},
            "summary": {"en": "Description"},
            "tags": [],
        }],
    }
    reviewed = b'[sample]\nsha256 = "' + hashlib.sha256(source).hexdigest().encode() + b'"\n'
    monkeypatch.setattr(manager, "catalog_cache_path",
                        lambda: tmp_path / "catalog-cache.json")
    monkeypatch.setattr(
        manager, "_get",
        lambda url, _limit: (json.dumps(catalog).encode()
                             if "catalog" in url else reviewed))
    live = manager.refresh_catalog()
    assert not live.from_cache
    assert manager.load_cached_catalog().extensions[0].id == "sample"

    def offline(*_args):
        raise manager.ExtensionManagerError("offline")
    monkeypatch.setattr(manager, "_get", offline)
    cached = manager.refresh_catalog()
    assert cached.from_cache
    assert cached.fetched_at == live.fetched_at
    assert cached.extensions[0].id == "sample"


def test_catalog_refresh_without_cache_surfaces_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "catalog_cache_path",
                        lambda: tmp_path / "missing-cache.json")
    monkeypatch.setattr(manager, "_get", lambda *_args: (_ for _ in ()).throw(
        manager.ExtensionManagerError("offline")))
    with pytest.raises(manager.ExtensionManagerError, match="offline"):
        manager.refresh_catalog()


def test_first_show_refreshes_catalog_without_manual_refresh(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    from views import extension_manager_dialog as dialog_module
    extension = _extension(b"first-open")
    snapshot = manager.CatalogSnapshot(
        [extension], {}, "2026-10-07T10:00:00+00:00", False)
    refresh_calls = []
    monkeypatch.setattr(
        dialog_module, "load_cached_catalog", lambda: snapshot)
    monkeypatch.setattr(dialog_module, "load_extension_sources", lambda: [])
    monkeypatch.setattr(dialog_module, "bundled_extensions", lambda: [])

    def refresh():
        refresh_calls.append(True)
        return snapshot

    monkeypatch.setattr(dialog_module, "refresh_catalog", refresh)
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        dialog.show()
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(
            lambda: loop.quit()
            if refresh_calls and dialog._catalog_worker is None else None)
        timer.start()
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        timer.stop()

        assert refresh_calls == [True]
        assert [item.id for item in dialog._extensions] == [extension.id]
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_install_verify_disable_and_enable_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    extension = _extension(TOOL_SOURCE.encode())
    monkeypatch.setattr(manager, "_get", lambda *_args: TOOL_SOURCE.encode())
    manager.install_extension(extension)
    target = tmp_path / "sample"
    assert (target / "__init__.py").read_text() == TOOL_SOURCE
    assert manager.installed_info("sample")["version"] == "1.0"
    assert manager.is_extension_enabled("sample")
    assert manager.restart_required("sample", {})
    assert [p.stem for p in discover_plugins([tmp_path])[0]] == ["sample"]

    manager.set_extension_enabled("sample", False)
    assert not manager.is_extension_enabled("sample")
    assert not manager.restart_required("sample", {})
    assert discover_plugins([tmp_path]) == ([], [])

    updated_source = TOOL_SOURCE + "\n# Updated package\n"
    monkeypatch.setattr(manager, "_get", lambda *_args: updated_source.encode())
    manager.install_extension(_extension(updated_source.encode()))
    assert not manager.is_extension_enabled("sample")
    assert not manager.restart_required("sample", {})
    assert discover_plugins([tmp_path]) == ([], [])

    manager.set_extension_enabled("sample", True)
    assert manager.restart_required("sample", {})
    assert [p.stem for p in discover_plugins([tmp_path])[0]] == ["sample"]
    startup = manager.extension_startup_state()
    assert not manager.restart_required("sample", startup)
    monkeypatch.setattr(manager, "_get",
                        lambda *_args: (updated_source + "# newer\n").encode())
    newer = (updated_source + "# newer\n").encode()
    manager.install_extension(_extension(newer))
    assert manager.restart_required("sample", startup)


def test_install_extension_accepts_a_pre_downloaded_verified_payload(
        tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)

    def unexpected_download(*_args):
        raise AssertionError(
            "the supplied payload should avoid a second download")

    monkeypatch.setattr(manager, "_get", unexpected_download)
    payload = TOOL_SOURCE.encode()
    extension = _extension(payload)
    with pytest.raises(manager.ExtensionManagerError, match="Checksum"):
        manager.install_extension(extension, downloaded_data=b"tampered")
    assert not (tmp_path / "sample").exists()

    manager.install_extension(
        extension, downloaded_data=payload)

    assert (tmp_path / "sample" / "__init__.py").read_bytes() == payload


def test_replace_hand_installed_uses_the_downloaded_payload(
        tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    legacy = tmp_path / "sample"
    legacy.mkdir()
    (legacy / "__init__.py").write_text("# hand installed", encoding="utf-8")
    payload = TOOL_SOURCE.encode()
    extension = _extension(payload)

    def unexpected_download(*_args):
        raise AssertionError(
            "the supplied payload should avoid a second download")

    monkeypatch.setattr(manager, "_get", unexpected_download)
    manager.replace_hand_installed(extension, downloaded_data=payload)

    assert (legacy / "extension.json").is_file()
    assert (legacy / "__init__.py").read_bytes() == payload
    assert list(tmp_path.glob(".sample.manual-*"))


def test_uninstall_removes_only_manager_owned_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    source = TOOL_SOURCE.encode()
    monkeypatch.setattr(manager, "_get", lambda *_args: source)
    manager.install_extension(_extension(source))
    startup = manager.extension_startup_state()

    manager.uninstall_extension("sample")

    assert not (tmp_path / "sample").exists()
    assert manager.installed_info("sample") is None
    assert manager.restart_required("sample", startup)
    with pytest.raises(manager.ExtensionManagerError, match="not an installed"):
        manager.uninstall_extension("sample")


def test_restart_required_detects_disable_against_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    source = TOOL_SOURCE.encode()
    monkeypatch.setattr(manager, "_get", lambda *_args: source)
    manager.install_extension(_extension(source))
    startup = manager.extension_startup_state()
    assert not manager.restart_required("sample", startup)
    manager.set_extension_enabled("sample", False)
    assert manager.restart_required("sample", startup)


def test_restart_button_tracks_extension_enablement_changes(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    folder = tmp_path / "sample"
    folder.mkdir()
    (folder / "extension.json").write_text(json.dumps({
        "id": "sample",
        "version": "1.0",
        "sha256": "a" * 64,
    }))
    from views import extension_manager_dialog as dialog_module
    from PySide6.QtWidgets import QWidget
    parent = QWidget()
    parent._extension_startup_state = {
        "sample": {"sha256": "a" * 64, "enabled": True}}
    dialog = dialog_module.ExtensionManagerDialog(parent)
    try:
        dialog._restart_candidates = {"sample"}
        dialog._sync_restart_button()
        assert dialog._restart_button.isHidden()

        (folder / ".disabled").write_text("", encoding="utf-8")
        dialog._sync_restart_button()
        assert not dialog._restart_button.isHidden()

        (folder / ".disabled").unlink()
        dialog._sync_restart_button()
        assert dialog._restart_button.isHidden()
    finally:
        dialog.close()
        dialog.deleteLater()
        parent.deleteLater()
        app.processEvents()


def test_download_checksum_mismatch_never_creates_install(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    extension = _extension(b"expected")
    monkeypatch.setattr(manager, "_get", lambda *_args: b"tampered")
    with pytest.raises(manager.ExtensionManagerError, match="Checksum mismatch"):
        manager.install_extension(extension)
    assert not (tmp_path / "sample").exists()


def test_zip_package_is_extracted_and_traversal_is_rejected(
        tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("sample/__init__.py", TOOL_SOURCE)
        archive.writestr("sample/subpackage/__init__.py", "")
        archive.writestr("sample/helper.txt", "data")
    payload = output.getvalue()
    extension = _extension(payload)
    monkeypatch.setattr(manager, "_get", lambda *_args: payload)
    manager.install_extension(extension)
    assert (tmp_path / "sample" / "__init__.py").read_text() == TOOL_SOURCE
    assert (tmp_path / "sample" / "subpackage" / "__init__.py").is_file()
    assert (tmp_path / "sample" / "helper.txt").read_text() == "data"

    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("../escape.py", "no")
        archive.writestr("sample.py", TOOL_SOURCE)
    malicious = bad.getvalue()
    monkeypatch.setattr(manager, "_get", lambda *_args: malicious)
    with pytest.raises(manager.ExtensionManagerError, match="unsafe path"):
        manager.install_extension(_extension(malicious, "other"))
    assert not (tmp_path.parent / "escape.py").exists()


def test_manual_plugin_collision_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    (tmp_path / "sample.py").write_text("user code")
    extension = _extension(b"catalog code")
    monkeypatch.setattr(manager, "_get", lambda *_args: b"catalog code")
    with pytest.raises(manager.ExtensionManagerError, match="not managed"):
        manager.install_extension(extension)
    assert (tmp_path / "sample.py").read_text() == "user code"


def test_minimum_version_comparison():
    extension = _extension(b"")
    assert manager.compatible_with_current(extension)
    assert manager.compatible_with_current(
        manager.Extension(**{**extension.__dict__,
                             "minimum_version": "99.0"})) is False


def test_incompatible_extension_is_rejected_before_download(
        tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    extension = manager.Extension(**{
        **_extension(b"future").__dict__,
        "minimum_version": "99.0",
    })
    called = False

    def unexpected_download(*_args):
        nonlocal called
        called = True
        return b"future"

    monkeypatch.setattr(manager, "_get", unexpected_download)
    with pytest.raises(manager.ExtensionManagerError, match="requires IngeTrazo"):
        manager.install_extension(extension)
    assert not called
    assert not (tmp_path / extension.id).exists()


def test_tested_version_age_is_a_nonblocking_warning():
    extension = _extension(b"")
    assert manager.tested_version_is_old(
        manager.Extension(**{**extension.__dict__,
                             "minimum_version": "0.0.0"}))


def test_extension_sort_modes_and_recent_date_availability(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    alpha = manager.Extension(
        **{**_extension(b"alpha", "alpha").__dict__,
           "name": {"en": "Alpha"},
           "updated_at": "2026-01-01"})
    beta = manager.Extension(
        **{**_extension(b"beta", "beta").__dict__,
           "name": {"en": "Beta"},
           "updated_at": "2026-03-01"})
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, [alpha, beta],
                  {"beta": {"sha256": beta.sha256}})
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    for extension, digest in ((alpha, "old-hash"), (beta, beta.sha256)):
        target = tmp_path / extension.id
        target.mkdir()
        (target / "extension.json").write_text(json.dumps({
            "id": extension.id,
            "version": "0.9" if extension.id == "alpha" else "1.0",
            "sha256": digest,
        }))
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        page = dialog._pages["browse"]
        sort = page["sort"]
        sort.setCurrentIndex(sort.findData("name"))
        assert [ext.id for ext in dialog._filtered_extensions()] == [
            "alpha", "beta"]
        sort.setCurrentIndex(sort.findData("reviewed"))
        assert [ext.id for ext in dialog._filtered_extensions()] == [
            "beta", "alpha"]
        sort.setCurrentIndex(sort.findData("updates"))
        assert [ext.id for ext in dialog._filtered_extensions()] == [
            "alpha", "beta"]
        sort.setCurrentIndex(sort.findData("recent"))
        assert [ext.id for ext in dialog._filtered_extensions()] == [
            "beta", "alpha"]
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()

    no_date_entries = [
        manager.Extension(**{**extension.__dict__, "updated_at": None})
        for extension in (alpha, beta)
    ]
    _stub_catalog(monkeypatch, dialog_module, no_date_entries)
    no_dates = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(no_dates, app)
        recent = no_dates._pages["browse"]["sort"].model().item(
            no_dates._pages["browse"]["sort"].findData("recent"))
        assert not recent.isEnabled()
    finally:
        no_dates.close()
        no_dates.deleteLater()
        app.processEvents()


def test_failed_extension_card_offers_recovery_actions(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    extension = _extension(TOOL_SOURCE.encode())
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, [extension])
    monkeypatch.setattr(dialog_module, "extension_startup_state", lambda: {})
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    target = tmp_path / extension.id
    target.mkdir()
    (target / "extension.json").write_text(json.dumps({
        "id": extension.id,
        "version": extension.version,
        "sha256": extension.sha256,
    }))
    parent = QWidget()
    parent._extension_load_errors = {
        extension.id: {"error": "ImportError: missing dependency",
                       "path": str(target / "__init__.py")}
    }
    dialog = dialog_module.ExtensionManagerDialog(parent)
    try:
        _wait_for_catalog(dialog, app)
        labels = dialog._pages["browse"]["cards"].findChildren(QLabel)
        assert any(label.text() == "Failed to load at startup"
                   for label in labels)
        buttons = dialog._pages["browse"]["cards"].findChildren(QPushButton)
        names = {button.text() for button in buttons}
        assert {"View load error", "Disable extension",
                "Open extension folder", "Open logs folder"} <= names
    finally:
        dialog.close()
        dialog.deleteLater()
        parent.deleteLater()
        app.processEvents()


def test_manager_shows_update_and_trust_details_without_downloading(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    extension = manager.Extension(**{
        **_extension(b"catalog-current").__dict__,
        "tags": ("drawing",),
    })
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, [extension])
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    target = tmp_path / extension.id
    target.mkdir()
    (target / "extension.json").write_text(json.dumps({
        "id": extension.id,
        "version": "0.9",
        "sha256": "0" * 64,
    }))
    download_calls = []
    monkeypatch.setattr(
        dialog_module, "install_extension",
        lambda item: download_calls.append(item.id))
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        row = dialog._pages["browse"]["grid"].itemAt(0).widget()
        labels = [label.text() for label in row.findChildren(QLabel)]
        buttons = [button.text() for button in row.findChildren(QPushButton)]
        assert any("Update available" in label for label in labels)
        assert "License: MIT" in labels
        assert any("not reviewed by an IngeTrazo maintainer" in label
                   for label in labels)
        assert any("v1.0" in label and "Tested with IngeTrazo" in label
                   for label in labels)
        assert "Update" in buttons
        assert "Repository ↗" in buttons
        repository = next(button for button in row.findChildren(QPushButton)
                          if button.text() == "Repository ↗")
        assert "padding: 3px 7px" in _card_rule(row, repository)
        author_column = row.findChildren(QLabel)
        author = next(label for label in row.findChildren(QLabel)
                      if label.text() == "by Author")
        assert "font-size: 13px" in _card_rule(row, author)
        license_label = next(label for label in row.findChildren(QLabel)
                             if label.text() == "License: MIT")
        assert author_column.index(license_label) > author_column.index(
            next(label for label in author_column
                 if label.text().startswith("Drawing")))
        assert "font-size: 13px" in _card_rule(row, license_label)
        assert "font-weight: bold" in _card_rule(row, license_label)
        assert download_calls == []
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_successful_install_uses_inline_status_without_success_popup(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    extension = manager.Extension(**{
        **_extension(TOOL_SOURCE.encode()).__dict__,
        "bundled": str(tmp_path / "sample.py"),
    })
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, [extension])
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    installed = []
    information = []
    monkeypatch.setattr(
        dialog_module, "install_extension",
        lambda item, **_kwargs: installed.append(item.id))
    monkeypatch.setattr(
        dialog_module.QMessageBox, "information",
        staticmethod(lambda *args: information.append(args)))
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        dialog._install(extension)
        app.processEvents()
        assert installed == ["sample"]
        assert information == []
        assert "Restart IngeTrazo" in dialog._install_status.text()
        assert not dialog._install_retry.isVisible()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_unreviewed_install_still_requires_trust_confirmation(monkeypatch):
    app = QApplication.instance() or QApplication([])
    from views import extension_manager_dialog as dialog_module
    dialog = dialog_module.ExtensionManagerDialog()
    warnings = []
    monkeypatch.setattr(dialog, "_reviewed", {})
    monkeypatch.setattr(
        dialog_module.QMessageBox, "warning",
        staticmethod(lambda *args: warnings.append(args)
                     or dialog_module.QMessageBox.No))
    try:
        assert not dialog._confirm_unreviewed(_extension(b"sample"))
        assert warnings
        assert "not been reviewed" in warnings[0][2]
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_extension_download_progress_can_be_cancelled_before_install(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    from views import extension_manager_dialog as dialog_module
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    dialog = dialog_module.ExtensionManagerDialog()

    class FakeReply:
        aborted = False

        def abort(self):
            self.aborted = True

    reply = FakeReply()
    dialog._active_install_reply = reply
    dialog._show_install_progress(
        "Downloading…", indeterminate=True, cancellable=True)
    try:
        dialog._extension_download_progress(reply, 1024, 2048)
        assert dialog._install_progress.value() == 50
        dialog._cancel_install_download()
        assert reply.aborted
        assert dialog._install_cancelled
        dialog._retry_install_request = (_extension(b"retry"), False)
        dialog._fail_install("Download failed. You can retry.", retry=True)
        assert "You can retry" in dialog._install_status.text()
        assert not dialog._install_retry.isHidden()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_catalog_install_downloads_with_progress_then_installs(
        tmp_path, monkeypatch):
    from PySide6.QtCore import QByteArray, QObject, QUrl
    from PySide6.QtNetwork import QNetworkReply

    app = QApplication.instance() or QApplication([])
    payload = TOOL_SOURCE.encode()
    extension = _extension(payload)
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, [extension], {
        extension.id: {"sha256": extension.sha256}})
    monkeypatch.setattr(dialog_module, "extension_startup_state", lambda: {})
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    installed = []

    class FakeReply(QObject):
        downloadProgress = Signal(int, int)
        finished = Signal()

        def error(self):
            return QNetworkReply.NetworkError.NoError

        def attribute(self, _attribute):
            return 200

        def url(self):
            return QUrl("https://example.org/sample.py")

        def readAll(self):
            return QByteArray(payload)

        def errorString(self):
            return ""

    class FakeNetwork:
        def get(self, _request):
            return reply

    reply = FakeReply()
    monkeypatch.setattr(
        dialog_module, "install_extension",
        lambda item, **kwargs:
        installed.append((item.id, kwargs["downloaded_data"])))
    dialog = dialog_module.ExtensionManagerDialog()
    dialog._network = FakeNetwork()
    try:
        _wait_for_catalog(dialog, app)
        dialog._begin_install(extension)
        received = len(payload) // 2
        reply.downloadProgress.emit(received, len(payload))
        assert dialog._install_progress.value() == received * 100 // len(payload)
        reply.downloadProgress.emit(len(payload), len(payload))
        reply.finished.emit()
        app.processEvents()
        assert installed == [("sample", payload)]
        assert "Restart IngeTrazo" in dialog._install_status.text()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_long_author_tags_and_license_wrap_within_preview_width(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    extension = manager.Extension(**{
        **_extension(b"long-details").__dict__,
        "author": "A very long extension author name that should wrap "
                  "rather than push the card layout",
        "license": "A long custom license name that should wrap below tags",
        # Enough chips that they cannot share one 256 px row on any
        # platform's font metrics (three fit on one row on macOS).
        "tags": ("architecture-and-urban-planning",
                 "productivity-workflow", "data-import-export",
                 "structural-engineering", "quantity-takeoff"),
    })
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, [extension])
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        dialog.show()
        app.processEvents()
        row = dialog._pages["browse"]["grid"].itemAt(0).widget()
        author = next(label for label in row.findChildren(QLabel)
                      if label.text().startswith("by A very long"))
        license_label = next(label for label in row.findChildren(QLabel)
                             if label.text().startswith("License: A long"))
        assert author.wordWrap()
        assert license_label.wordWrap()
        assert author.width() <= dialog_module._IMAGE_SIZE[0]
        assert license_label.width() <= dialog_module._IMAGE_SIZE[0]
        assert author.height() > author.fontMetrics().height()
        assert license_label.height() > license_label.fontMetrics().height()
        assert row.width() <= dialog_module._ROW_MAX_WIDTH
        tags_layout = next(layout for layout in row.findChildren(
            dialog_module.FlowLayout))
        image_details = tags_layout.parentWidget()
        assert _card_rule(row, image_details) == "background: transparent;"
        assert tags_layout.heightForWidth(dialog_module._IMAGE_SIZE[0]) \
            > max(tags_layout.itemAt(index).sizeHint().height()
                  for index in range(tags_layout.count()))
        title = next(label for label in row.findChildren(QLabel)
                     if label.text() == "Sample")
        assert not title.wordWrap()
        version_label = next(label for label in row.findChildren(QLabel)
                             if label.text().startswith("v1.0 · Tested with"))
        assert title.geometry().top() - version_label.geometry().bottom() < 20
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_a_tag_chip_stays_on_one_line_unless_wider_than_the_card(
        tmp_path, monkeypatch):
    """Word wrap on every chip let Qt size each one narrow, so a short tag
    broke in two with room to spare (and, with some fonts, the chips all
    crowded onto one row). Only a tag wider than the card wraps."""
    app = QApplication.instance() or QApplication([])
    huge = "-".join(["a-very-long-tag-name"] * 6)
    extension = manager.Extension(**{
        **_extension(b"chips").__dict__,
        "tags": ("data-import-export", huge),
    })
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, [extension])
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        dialog.show()
        app.processEvents()
        row = dialog._pages["browse"]["grid"].itemAt(0).widget()
        chips = {label.text(): label for label in row.findChildren(QLabel)
                 if label.objectName() == "extChip"}
        short = chips[dialog_module._tag_label("data-import-export")]
        long_ = chips[dialog_module._tag_label(huge)]
        assert not short.wordWrap()
        assert short.height() < 2 * short.fontMetrics().height()
        assert long_.wordWrap()
        assert long_.width() <= dialog_module._IMAGE_SIZE[0]
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_incompatible_extension_is_not_offered_for_install_or_enable(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    extension = manager.Extension(**{
        **_extension(b"future").__dict__,
        "minimum_version": "99.0",
    })
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, [extension])
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        row = dialog._pages["browse"]["grid"].itemAt(0).widget()
        labels = [label.text() for label in row.findChildren(QLabel)]
        buttons = [button.text() for button in row.findChildren(QPushButton)]
        assert any("Requires IngeTrazo 99.0 or later" in label
                   for label in labels)
        assert "Download" not in buttons
        assert "Enable" not in buttons
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_unexpected_catalog_refresh_error_keeps_cached_catalog_visible(
        monkeypatch):
    app = QApplication.instance() or QApplication([])
    extension = _extension(TOOL_SOURCE.encode())
    from views import extension_manager_dialog as dialog_module
    snapshot = manager.CatalogSnapshot(
        [extension], {}, "2026-10-07T10:00:00+00:00", True)
    monkeypatch.setattr(dialog_module, "load_cached_catalog",
                        lambda: snapshot)

    def fail_refresh():
        raise RuntimeError("unexpected parser failure")

    monkeypatch.setattr(dialog_module, "refresh_catalog", fail_refresh)
    monkeypatch.setattr(dialog_module, "bundled_extensions", lambda: [])
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        assert [item.id for item in dialog._extensions] == [extension.id]
        assert "Could not refresh catalog" in (
            dialog._catalog_info.text())
        assert dialog._refresh.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_extension_manager_search_tags_and_reviewed_filter(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    first = manager.Extension(
        **{**_extension(b"one", "loop_cut").__dict__,
           "tags": ("drawing", "productivity")})
    second = manager.Extension(
        **{**_extension(b"two", "terrain_tool").__dict__,
           "name": {"en": "Terrain Tool"},
           "summary": {"en": "Terrain editor"},
           "tags": ("terrain",)})
    reviewed = {"loop_cut": {"sha256": first.sha256}}
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, [first, second], reviewed)
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    installed = tmp_path / "loop_cut"
    installed.mkdir()
    (installed / "extension.json").write_text(json.dumps({
        "id": "loop_cut",
        "version": "1.0",
        "sha256": first.sha256,
    }))
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        assert "2 of 2 extensions" in dialog._catalog_info.text()
        assert "Refreshed" in dialog._catalog_info.text()
        assert dialog._pages["browse"]["divider"].frameShape() == \
            QFrame.HLine
        assert len(dialog._filtered_extensions()) == 2
        dialog._pages["browse"]["search"].setText("editor")
        assert [ext.id for ext in dialog._filtered_extensions()] == [
            "terrain_tool"]

        dialog._pages["browse"]["search"].clear()
        terrain = next(button for button in
                       dialog._pages["browse"]["tags_group"].buttons()
                       if button.property("tag") == "terrain")
        terrain.click()
        assert [ext.id for ext in dialog._filtered_extensions()] == [
            "terrain_tool"]

        dialog._select_tag("browse", "")
        dialog._pages["browse"]["reviewed"].setChecked(True)
        assert [ext.id for ext in dialog._filtered_extensions()] == [
            "loop_cut"]

        assert [ext.id for ext in
                dialog._filtered_extensions("installed")] == ["loop_cut"]
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_catalog_refresh_reuses_cards_and_renders_installed_tab_lazily(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    extension = _extension(TOOL_SOURCE.encode())
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, [extension])
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    installed = tmp_path / extension.id
    installed.mkdir()
    (installed / "extension.json").write_text(json.dumps({
        "id": extension.id,
        "version": extension.version,
        "sha256": extension.sha256,
    }))
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        browse = dialog._pages["browse"]
        row = browse["grid"].itemAt(0).widget()
        assert browse["dirty"] is False

        dialog._apply_catalog(dialog._catalog_snapshot)
        assert browse["grid"].itemAt(0).widget() is row
        assert dialog._pages["installed"]["dirty"] is True

        dialog._tabs.setCurrentIndex(1)
        installed_page = dialog._pages["installed"]
        _wait_for_page_render(dialog, app, "installed")
        assert installed_page["dirty"] is False
        assert installed_page["shown"] == 1, (
            dialog._tabs.currentIndex(), installed_page["render_items"],
            installed_page["pending_indices"])
        assert installed_page["grid"].count() == 1, (
            installed_page["shown"],
            [extension.id for extension in
             dialog._filtered_extensions("installed")])
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_catalog_update_rebuilds_only_cards_with_changed_data(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    extensions = [
        _extension(f"source {index}".encode(), f"sample_{index}")
        for index in range(4)
    ]
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, extensions)
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        page = dialog._pages["browse"]
        previous = dict(page["rows"])
        changed = manager.Extension(**{
            **extensions[1].__dict__,
            "version": "2.0",
        })
        updated = manager.CatalogSnapshot(
            [extensions[0], changed, extensions[2], extensions[3]],
            dialog._reviewed,
            "2026-10-12T11:00:00+00:00",
            False,
        )
        dialog._apply_catalog(updated)
        _wait_for_page_render(dialog, app, "browse")
        assert page["rows"]["sample_0"] is previous["sample_0"]
        assert page["rows"]["sample_1"] is not previous["sample_1"]
        assert page["rows"]["sample_2"] is previous["sample_2"]
        assert page["rows"]["sample_3"] is previous["sample_3"]
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_large_card_render_is_split_into_event_loop_batches(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    extensions = [
        _extension(f"source {index}".encode(), f"sample_{index}")
        for index in range(60)
    ]
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, extensions)
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        dialog.resize(1180, 800)
        dialog.show()
        app.processEvents()
        dialog._load()
        _wait_for_catalog(dialog, app)
        page = dialog._pages["browse"]
        assert page["grid"].count() == len(extensions)
        assert len(page["rows"]) < len(extensions)
        first_card = page["rows"]["sample_0"]

        scrollbar = page["scroll"].verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(
            lambda: loop.quit()
            if not page["render_timer"].isActive()
            and not page["pending_indices"] else None)
        timer.start()
        QTimer.singleShot(15000, loop.quit)
        loop.exec()
        timer.stop()
        assert not page["render_timer"].isActive()
        assert "sample_59" in page["rows"]
        assert len(page["rows"]) < len(extensions)

        scrollbar.setValue(0)
        app.processEvents()
        assert page["rows"]["sample_0"] is first_card
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_extension_views_use_two_columns_and_16_by_10_previews(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    extensions = [
        _extension(f"source {index}".encode(), f"extension_{index}")
        for index in range(5)
    ]
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, extensions)
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        dialog.resize(1180, 800)
        dialog.show()
        app.processEvents()
        _wait_for_page_render(dialog, app, "browse")
        grid = dialog._pages["browse"]["grid"]
        assert grid.count() == len(extensions)
        for index in range(len(extensions)):
            row, column = divmod(index, 2)
            item = grid.itemAtPosition(row, column)
            assert item is not None
            assert item.widget() is not None
            assert item.widget().width() >= 400
        image = dialog._pages["browse"]["image_labels"]["extension_0"]
        assert image.width() * 10 == image.height() * 16
        assert image.width() > 200
        row = grid.itemAt(0).widget()
        assert row.width() >= int(
            dialog._pages["browse"]["scroll"].viewport().width() * 0.4)
        assert row.maximumWidth() <= dialog_module._ROW_MAX_WIDTH
        assert row.maximumHeight() == dialog_module._ROW_MAX_HEIGHT
        search = dialog._pages["browse"]["search"]
        assert search.parentWidget() is not None
        assert "background: palette(base)" in search.styleSheet()
        tags = dialog._pages["browse"]["tags_group"].buttons()
        assert tags and tags[0].text() == "All"
        assert dialog._pages["browse"]["tags_layout"].spacing() == 8
        assert dialog._pages["installed"]["tags_layout"].spacing() == 8
        assert all(button.sizePolicy().horizontalPolicy()
                   == dialog_module.QSizePolicy.Fixed for button in tags)
        assert dialog._pages["browse"]["filters"].contentsMargins().right() \
            == 10
        tags_scroll = dialog._pages["browse"]["tags_scroll"]
        assert tags_scroll.isVisible()
        assert all(button.isVisible() for button in tags)
        sort = dialog._pages["browse"]["sort"]
        assert "padding: 5px 8px" in sort.styleSheet()
        assert "QComboBox:hover { color: palette(text)" in sort.styleSheet()
        assert dialog._pages["installed"]["grid"].count() == 0
        dialog._tabs.setCurrentIndex(1)
        assert dialog._pages["installed"]["grid"].count() == 0
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_extension_manager_styles_follow_dark_palette(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    original_palette = app.palette()
    extension = _extension(TOOL_SOURCE.encode())
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, [extension])
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    try:
        app.setPalette(dark_palette())
        dialog = dialog_module.ExtensionManagerDialog()
        try:
            _wait_for_catalog(dialog, app)
            row = dialog._pages["browse"]["grid"].itemAt(0).widget()
            assert "background: palette(window)" in dialog.styleSheet()
            assert "background: palette(base)" in _card_rule(row, row)
            assert "color: palette(text)" in _card_rule(row, QLabel())
            assert "background: palette(base)" in (
                dialog._pages["browse"]["search"].styleSheet())
            assert "color: palette(link)" in _card_rule(row, next(
                button for button in row.findChildren(QPushButton)
                if button.text() == "Repository ↗"))
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()
    finally:
        app.setPalette(original_palette)


def test_installed_card_shows_restart_status(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    extension = _extension(TOOL_SOURCE.encode())
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, [extension])
    monkeypatch.setattr(dialog_module, "extension_startup_state", lambda: {})
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    target = tmp_path / extension.id
    target.mkdir()
    (target / "extension.json").write_text(json.dumps({
        "id": extension.id,
        "version": extension.version,
        "sha256": extension.sha256,
    }))
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        dialog.show()
        app.processEvents()
        labels = dialog._pages["browse"]["cards"].findChildren(
            QLabel)
        assert any(label.text() == "Restart required to apply changes"
                   for label in labels)
        row = dialog._pages["browse"]["grid"].itemAt(0).widget()
        state = next(label for label in row.findChildren(QLabel)
                     if label.text().startswith("Up to date"))
        actions = next(button for button in row.findChildren(QPushButton)
                       if button.text() == "Up to date")
        assert row.rect().bottom() - actions.geometry().bottom() < 15
        assert actions.geometry().top() - state.geometry().bottom() < 15
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_zip_names_with_a_colon_are_rejected(tmp_path, monkeypatch):
    # On Windows «C:x» is drive-relative and «a.py:s» a data stream: both
    # can write outside the stage. Linux would extract them quietly.
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    for name in ("sample/C:escape.py", "sample/helper.py:stream"):
        bad = io.BytesIO()
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("sample/__init__.py", TOOL_SOURCE)
            archive.writestr(name, "no")
        payload = bad.getvalue()
        monkeypatch.setattr(manager, "_get", lambda *_a, p=payload: p)
        with pytest.raises(manager.ExtensionManagerError, match="unsafe path"):
            manager.install_extension(_extension(payload))
        assert not (tmp_path / "sample").exists()


def test_catalog_text_is_shown_as_plain_text(tmp_path, monkeypatch):
    # A catalog entry publishes with no human in between: its HTML must
    # not render (a fake «REVIEWED» badge in a summary).
    from PySide6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    extension = manager.Extension(**{
        **_extension(b"html").__dict__,
        "summary": {"en": "<b style='color:green'>REVIEWED</b> trust me"},
        "repository": "file:///etc/passwd",
    })
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, [extension])
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        row = dialog._pages["browse"]["grid"].itemAt(0).widget()
        labels = row.findChildren(QLabel)
        assert labels and all(label.textFormat() == Qt.PlainText
                              for label in labels)
        repository = next(button for button in row.findChildren(QPushButton)
                          if button.text() == "Repository ↗")
        assert not repository.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def _zip(files: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return out.getvalue()


def test_a_hand_installed_copy_under_another_name_is_set_aside(
        tmp_path, monkeypatch):
    # OpenTrace used to be unpacked by hand as «arquitetura_parametrica»;
    # installed from the catalog as «opentrace_bim» it loaded twice.
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    old = tmp_path / "arquitetura_parametrica"
    (old / "nested").mkdir(parents=True)
    for name in ("beam.py", "column.py", "slab.py", "nested/roof.py"):
        (old / name).write_text("# old version\n")
    (old / "__init__.py").write_text("# old entry\n")
    other = tmp_path / "unrelated"
    other.mkdir()
    (other / "__init__.py").write_text(TOOL_SOURCE)
    (other / "a.py").write_text("x = 1\n")
    payload = _zip({f"opentrace_bim/{n}": "# new\n" for n in (
        "__init__.py", "beam.py", "column.py", "slab.py", "nested/roof.py",
        "walls.py")})
    monkeypatch.setattr(manager, "_get", lambda *_a: payload)
    extension = _extension(payload, "opentrace_bim")

    asked = []
    with pytest.raises(manager.ExtensionManagerError, match="by hand"):
        manager.install_extension(
            extension, confirm_manual_copies=lambda p: asked.append(p) or False)
    assert [p.name for p in asked[0]] == ["arquitetura_parametrica"]
    assert old.is_dir() and not (tmp_path / "opentrace_bim").exists()

    manager.install_extension(extension, confirm_manual_copies=lambda p: True)
    assert (tmp_path / "opentrace_bim" / "__init__.py").is_file()
    assert not old.exists() and other.is_dir()           # only the copy goes
    aside = [p for p in tmp_path.iterdir()
             if p.name.startswith(".arquitetura_parametrica.manual-")]
    assert len(aside) == 1 and (aside[0] / "beam.py").is_file()
    stems = [plug.stem for plug in discover_plugins([tmp_path])[0]]
    assert "arquitetura_parametrica" not in stems


def test_an_identical_loose_file_counts_as_a_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    # newline="\n": byte for byte what the catalog serves (on Windows
    # write_text puts \r\n and the copy is no longer identical).
    (tmp_path / "my_old_name.py").write_text(TOOL_SOURCE, newline="\n")
    payload = TOOL_SOURCE.encode()
    monkeypatch.setattr(manager, "_get", lambda *_a: payload)
    with pytest.raises(manager.ExtensionManagerError, match="my_old_name.py"):
        manager.install_extension(_extension(payload))
    assert not (tmp_path / "sample").exists()


def test_a_loose_file_with_crlf_line_endings_counts_as_a_copy(
        tmp_path, monkeypatch):
    # #764: a hand-installed copy whose line endings were converted to
    # CRLF (a Windows editor, a zip tool, Path.write_text on Windows)
    # is the same extension, even though its raw bytes differ.
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    crlf = TOOL_SOURCE.encode().replace(b"\n", b"\r\n")
    (tmp_path / "my_old_name.py").write_bytes(crlf)
    payload = TOOL_SOURCE.encode()
    monkeypatch.setattr(manager, "_get", lambda *_a: payload)
    with pytest.raises(manager.ExtensionManagerError, match="my_old_name.py"):
        manager.install_extension(_extension(payload))
    assert not (tmp_path / "sample").exists()


def test_a_loose_file_with_a_bom_and_crlf_counts_as_a_copy(
        tmp_path, monkeypatch):
    # #764: a UTF-8 BOM saved by a Windows editor must not hide a copy
    # either.
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    crlf = TOOL_SOURCE.encode().replace(b"\n", b"\r\n")
    (tmp_path / "my_old_name.py").write_bytes(b"\xef\xbb\xbf" + crlf)
    payload = TOOL_SOURCE.encode()
    monkeypatch.setattr(manager, "_get", lambda *_a: payload)
    with pytest.raises(manager.ExtensionManagerError, match="my_old_name.py"):
        manager.install_extension(_extension(payload))
    assert not (tmp_path / "sample").exists()


def test_a_package_whose_entry_has_crlf_line_endings_counts_as_a_copy(
        tmp_path, monkeypatch):
    # #764, the package form: only the entry module's endings changed.
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: plugins)
    hand = plugins / "hand_copy"
    hand.mkdir()
    (hand / "__init__.py").write_bytes(
        TOOL_SOURCE.encode().replace(b"\n", b"\r\n"))
    package = tmp_path / "catalog_copy"
    package.mkdir()
    (package / "__init__.py").write_bytes(TOOL_SOURCE.encode())
    assert manager.manual_copies("sample", package) == [hand]


def test_a_different_loose_file_with_crlf_is_not_a_copy(
        tmp_path, monkeypatch):
    # Normalizing endings must not collapse different code into a copy:
    # a file that differs beyond its line endings stays unrelated.
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    other = TOOL_SOURCE.replace("Catalog tool", "Another tool")
    (tmp_path / "my_old_name.py").write_bytes(
        other.encode().replace(b"\n", b"\r\n"))
    payload = TOOL_SOURCE.encode()
    monkeypatch.setattr(manager, "_get", lambda *_a: payload)
    manager.install_extension(_extension(payload))
    assert (tmp_path / "sample" / "__init__.py").is_file()
    assert (tmp_path / "my_old_name.py").is_file()


def test_switching_tabs_keeps_the_cards_and_their_screenshots(
        tmp_path, monkeypatch):
    """#555: every tab switch rebuilt all the cards, the old ones stayed
    painted until deleteLater and each new card started without its
    picture — a flash between the tabs, worst on Windows."""
    app = QApplication.instance() or QApplication([])
    extensions = [
        manager.Extension(**{
            **_extension(f"source {index}".encode(),
                         f"extension_{index}").__dict__,
            "screenshot": f"extension_{index}.png"})
        for index in range(3)
    ]
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, extensions)
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    monkeypatch.setattr(dialog_module.QStandardPaths, "writableLocation",
                        lambda _location: str(tmp_path / "data"))
    pixmap = QPixmap(64, 40)
    pixmap.fill(QColor("red"))
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    png = bytes(buffer.data())
    shots = tmp_path / "data" / "extension-screenshots"
    shots.mkdir(parents=True)
    for extension in extensions:
        (shots / extension.screenshot).write_bytes(png)
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        dialog.resize(1180, 800)
        dialog.show()
        app.processEvents()
        grid = dialog._pages["browse"]["grid"]
        cards = dict(dialog._pages["browse"]["rows"])
        labels = dict(dialog._pages["browse"]["image_labels"])
        assert set(dialog._screenshots) == {e.id for e in extensions}
        assert all(not label.pixmap().isNull() for label in labels.values())

        dialog._tabs.setCurrentIndex(1)
        app.processEvents()
        dialog._tabs.setCurrentIndex(0)
        app.processEvents()
        assert dialog._pages["browse"]["rows"] == cards
        assert "3 of 3 extensions" in dialog._catalog_info.text()

        # Filtering and sorting reuse card widgets and their decoded images.
        dialog._render_page("browse")
        assert dialog._pages["browse"]["rows"] == cards
        for ident, label in dialog._pages["browse"]["image_labels"].items():
            assert label is labels[ident]
            assert not label.pixmap().isNull()
            assert label.text() == ""
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_opening_decodes_only_the_visible_screenshots_and_a_same_refresh_keeps_the_cards(
        tmp_path, monkeypatch):
    """#555, the white window when the manager opens on Windows: every
    screenshot was decoded before the first paint (the cards were not laid
    out yet, so all looked visible), and the refresh that brings the same
    catalog as the cached one rebuilt both pages again."""
    app = QApplication.instance() or QApplication([])
    extensions = [
        manager.Extension(**{
            **_extension(f"source {index}".encode(),
                         f"extension_{index}").__dict__,
            "screenshot": f"extension_{index}.png"})
        for index in range(20)
    ]
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, extensions)
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    monkeypatch.setattr(dialog_module.QStandardPaths, "writableLocation",
                        lambda _location: str(tmp_path / "data"))
    pixmap = QPixmap(64, 40)
    pixmap.fill(QColor("red"))
    shots = tmp_path / "data" / "extension-screenshots"
    shots.mkdir(parents=True)
    for extension in extensions:
        pixmap.save(str(shots / extension.screenshot), "PNG")
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        grid = dialog._pages["browse"]["grid"]
        cards = [grid.itemAt(i).widget() for i in range(grid.count())]
        dialog.resize(1180, 800)
        dialog.show()
        app.processEvents()
        assert 0 < len(dialog._screenshots) < len(extensions)
        # The refresh in the background brought the same catalog: the
        # cards on screen stay.
        assert [grid.itemAt(i).widget() for i in range(grid.count())] == cards
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_on_windows_the_manager_appears_only_once_painted(
        tmp_path, monkeypatch):
    """#555: Windows showed the new window white until its first paint
    (~0.4 s); it now opens transparent and appears once painted."""
    app = QApplication.instance() or QApplication([])
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, [_extension(b"one")])
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    monkeypatch.setattr(dialog_module, "_HIDE_UNTIL_PAINTED", True)
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        assert dialog.windowOpacity() == 0.0
        dialog.show()
        dialog.repaint()
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()
        assert dialog.windowOpacity() == 1.0
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_building_the_manager_never_shows_a_stray_window(tmp_path, monkeypatch):
    """#555: each card's «Repository ↗» button got setVisible(True) before
    it was in the card, so it became a window of its own and was shown —
    on Windows 43 little windows flashed and the build took 0.9 s."""
    app = QApplication.instance() or QApplication([])
    from PySide6.QtCore import QEvent, QObject
    extensions = [_extension(f"source {i}".encode(), f"extension_{i}")
                  for i in range(5)]
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, extensions)
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    shown = []

    class Watch(QObject):
        def eventFilter(self, obj, event):
            if (event.type() == QEvent.Show and obj.isWidgetType()
                    and obj.isWindow()):
                shown.append(type(obj).__name__)
            return False

    watch = Watch()
    app.installEventFilter(watch)
    try:
        dialog = dialog_module.ExtensionManagerDialog()
        app.processEvents()
        assert shown == []
        dialog.show()
        _wait_for_catalog(dialog, app)
    finally:
        app.removeEventFilter(watch)
    try:
        assert shown == ["ExtensionManagerDialog"]
        app.processEvents()
        row = dialog._pages["browse"]["grid"].itemAtPosition(0, 0).widget()
        repository = next(button for button in row.findChildren(QPushButton)
                          if button.text() == "Repository ↗")
        assert repository.isVisible()
        assert dialog._pages["browse"]["reviewed"].isVisible()
        assert not dialog._pages["installed"]["reviewed"].isVisibleTo(dialog)
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


class _FakeReply(QObject):
    finished = Signal()

    def __init__(self, data: bytes, ok: bool):
        super().__init__()
        self._data, self._ok = data, ok
        QTimer.singleShot(0, self.finished.emit)

    def readAll(self):            # noqa: N802 — Qt's name
        return self._data

    def attribute(self, _what):
        return 200 if self._ok else None

    def error(self):
        from PySide6.QtNetwork import QNetworkReply
        return (QNetworkReply.NetworkError.NoError if self._ok
                else QNetworkReply.NetworkError.HostNotFoundError)

    def errorString(self):        # noqa: N802 — Qt's name
        return "" if self._ok else "host not found"


class _FakeNetwork:
    """GitHub fails, the website answers — and every URL asked is kept."""

    def __init__(self, png: bytes):
        self.png, self.urls = png, []

    def get(self, request):
        url = request.url().toString()
        self.urls.append(url)
        return _FakeReply(self.png, "ingetrazo.com" in url)


def test_a_screenshot_that_failed_is_asked_again_from_the_website(
        tmp_path, monkeypatch):
    """Caza 2 (16-10): a screenshot whose download failed once stayed
    «Preview unavailable» until the list was scrolled; the website, which
    serves the same files through its own cache, showed them all."""
    from PySide6.QtCore import QByteArray
    app = QApplication.instance() or QApplication([])
    from views import extension_manager_dialog as dialog_module
    extension = manager.Extension(**{
        **_extension(b"one", "with_shot").__dict__,
        "screenshot": "with_shot.png"})
    _stub_catalog(monkeypatch, dialog_module, [extension])
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    monkeypatch.setattr(dialog_module.QStandardPaths, "writableLocation",
                        lambda _location: str(tmp_path / "data"))
    monkeypatch.setattr(dialog_module, "_SCREENSHOT_RETRY_MS", 10)
    pixmap = QPixmap(64, 40)
    pixmap.fill(QColor("red"))
    raw = QByteArray()
    buf = QBuffer(raw)
    buf.open(QIODevice.WriteOnly)
    pixmap.save(buf, "PNG")
    network = _FakeNetwork(bytes(raw))
    dialog = dialog_module.ExtensionManagerDialog()
    dialog._network = network
    try:
        _wait_for_catalog(dialog, app)
        dialog.resize(1180, 800)
        dialog.show()
        loop = QEventLoop()
        QTimer.singleShot(500, loop.quit)
        loop.exec()
        assert "with_shot" in dialog._screenshots       # without scrolling
        assert "raw.githubusercontent.com" in network.urls[0]
        assert network.urls[1].startswith(dialog_module._SCREENSHOT_MIRROR)
        assert (tmp_path / "data" / "extension-screenshots"
                / "with_shot.png").is_file()            # cached for next time
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def _shots_setup(tmp_path, monkeypatch, count):
    extensions = [
        manager.Extension(**{
            **_extension(f"source {index}".encode(),
                         f"extension_{index}").__dict__,
            "screenshot": f"extension_{index}.png"})
        for index in range(count)
    ]
    from views import extension_manager_dialog as dialog_module
    _stub_catalog(monkeypatch, dialog_module, extensions)
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    monkeypatch.setattr(dialog_module.QStandardPaths, "writableLocation",
                        lambda _location: str(tmp_path / "data"))
    pixmap = QPixmap(640, 400)
    pixmap.fill(QColor("red"))
    shots = tmp_path / "data" / "extension-screenshots"
    shots.mkdir(parents=True)
    for extension in extensions:
        pixmap.save(str(shots / extension.screenshot), "PNG")
    return dialog_module, extensions, shots


def _wait_ms(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _open(dialog_module, app):
    dialog = dialog_module.ExtensionManagerDialog()
    _wait_for_catalog(dialog, app)
    dialog.resize(1180, 800)
    dialog.show()
    app.processEvents()
    return dialog


def _close(dialog, app):
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_opening_the_manager_again_shows_every_card_with_its_screenshot(
        tmp_path, monkeypatch):
    """Marco, 18-10: each opening decoded the full screenshots again and
    the cards came up «Preview unavailable» before their picture. The
    first opening scales the rest in the background; the next one builds
    every card already wearing it, with no screenshot decoded."""
    app = QApplication.instance() or QApplication([])
    dialog_module, extensions, _shots = _shots_setup(tmp_path, monkeypatch, 20)
    dialog = _open(dialog_module, app)
    try:
        assert 0 < len(dialog._screenshots) < len(extensions)
        _wait_ms(1500)                       # the background rounds
        assert set(dialog._screenshots) == {e.id for e in extensions}
    finally:
        _close(dialog, app)

    decoded = []
    monkeypatch.setattr(
        dialog_module.QImage, "loadFromData",
        lambda self, *a: decoded.append(1) or False)
    dialog = dialog_module.ExtensionManagerDialog()
    try:
        _wait_for_catalog(dialog, app)
        labels = dialog._pages["browse"]["image_labels"]
        assert 0 < len(labels) < len(extensions)
        for label in labels.values():
            assert not label.pixmap().isNull() and label.text() == ""
        assert decoded == []
    finally:
        _close(dialog, app)


def test_the_scaled_screenshot_is_kept_on_disk_until_the_screenshot_changes(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    dialog_module, extensions, shots = _shots_setup(tmp_path, monkeypatch, 1)
    dialog = _open(dialog_module, app)
    _close(dialog, app)
    source = shots / extensions[0].screenshot
    thumb = dialog_module.ExtensionManagerDialog._thumb_path(source)
    assert thumb.is_file()
    small = QPixmap(str(thumb))
    assert small.width() == 256 and small.height() == 160
    assert thumb.stat().st_size < source.stat().st_size

    def colour_after_restart():
        dialog_module._SCALED_SHOTS.clear()   # a new run of IngeTrazo
        dialog = _open(dialog_module, app)
        try:
            label = dialog._pages["browse"]["image_labels"][extensions[0].id]
            return label.pixmap().toImage().pixelColor(5, 5).name()
        finally:
            _close(dialog, app)

    # The next run reads the small copy, not the screenshot.
    blue = QPixmap(256, 160)
    blue.fill(QColor("blue"))
    blue.save(str(thumb), "PNG")
    assert colour_after_restart() == "#0000ff"

    # A new screenshot (an update downloaded) is scaled again.
    green = QPixmap(640, 400)
    green.fill(QColor("green"))
    green.save(str(source), "PNG")
    import os
    later = thumb.stat().st_mtime_ns + 10_000_000_000
    os.utime(source, ns=(later, later))
    assert colour_after_restart() == "#008000"


def test_the_background_rounds_fetch_the_missing_pictures_a_few_at_a_time(
        tmp_path, monkeypatch):
    """#1296: once the visible cards are in, the pictures not on disk are
    fetched in the background, a few at a time, so scrolling finds them
    ready (before, each waited for its card to be seen)."""
    app = QApplication.instance() or QApplication([])
    dialog_module, extensions, shots = _shots_setup(tmp_path, monkeypatch, 20)
    missing = extensions[-6:]
    for extension in missing:
        (shots / extension.screenshot).unlink()
    png = (shots / extensions[0].screenshot).read_bytes()
    network = _HeldNetwork(lambda url: (png, True), delay_ms=40)
    dialog = dialog_module.ExtensionManagerDialog()
    dialog._network = network
    try:
        _wait_for_catalog(dialog, app)
        dialog.resize(1180, 800)
        dialog.show()
        app.processEvents()
        _wait_ms(2500)
        assert set(dialog._screenshots) == {e.id for e in extensions}
        assert sorted(network.urls) == sorted(
            dialog_module._SCREENSHOT_BASE + e.screenshot for e in missing)
        assert max(network.in_flight) <= dialog_module._PREFETCH_DOWNLOADS
    finally:
        _close(dialog, app)


class _HeldReply(_FakeReply):
    def __init__(self, data, ok, delay_ms, network):
        QObject.__init__(self)
        self._data, self._ok = data, ok
        network.open += 1
        self.finished.connect(lambda: setattr(network, "open",
                                              network.open - 1))
        QTimer.singleShot(delay_ms, self.finished.emit)


class _HeldNetwork:
    """Answers each URL as ``answer(url)`` says, a moment later; keeps the
    URLs asked and how many were on their way at each request."""

    def __init__(self, answer, delay_ms=0):
        self.answer, self.delay_ms = answer, delay_ms
        self.urls, self.in_flight, self.open = [], [], 0

    def get(self, request):
        url = request.url().toString()
        self.urls.append(url)
        data, ok = self.answer(url)
        reply = _HeldReply(data, ok, self.delay_ms, self)
        self.in_flight.append(self.open)
        return reply


def _png(colour="red", size=(64, 40)) -> bytes:
    from PySide6.QtCore import QByteArray
    pixmap = QPixmap(*size)
    pixmap.fill(QColor(colour))
    raw = QByteArray()
    buf = QBuffer(raw)
    buf.open(QIODevice.WriteOnly)
    pixmap.save(buf, "PNG")
    return bytes(raw)


_SHA_A = "0123456789abcdef"
_SHA_B = "fedcba9876543210"


def _one_card(tmp_path, monkeypatch, **fields):
    from views import extension_manager_dialog as dialog_module
    extension = manager.Extension(**{
        **_extension(b"one", "with_shot").__dict__,
        "screenshot": "with_shot.png", **fields})
    _stub_catalog(monkeypatch, dialog_module, [extension])
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: tmp_path)
    monkeypatch.setattr(dialog_module.QStandardPaths, "writableLocation",
                        lambda _location: str(tmp_path / "data"))
    monkeypatch.setattr(dialog_module, "_SCREENSHOT_RETRY_MS", 10)
    dialog_module._SCALED_SHOTS.clear()
    return dialog_module, extension


def _show_with(dialog_module, network, app, ms=500):
    dialog = dialog_module.ExtensionManagerDialog()
    dialog._network = network
    _wait_for_catalog(dialog, app)
    dialog.resize(1180, 800)
    dialog.show()
    _wait_ms(ms)
    return dialog


def test_a_catalog_thumb_is_fetched_instead_of_the_screenshot(
        tmp_path, monkeypatch):
    """#1296: the card shows the catalog's 512 × 320 copy, not the full
    screenshot of up to 600 KB."""
    app = QApplication.instance() or QApplication([])
    dialog_module, _ext = _one_card(tmp_path, monkeypatch,
                                    thumb="with_shot.webp",
                                    screenshot_sha=_SHA_A)
    network = _HeldNetwork(lambda url: (_png(), True))
    dialog = _show_with(dialog_module, network, app)
    try:
        assert "with_shot" in dialog._screenshots
        assert network.urls == [
            "https://raw.githubusercontent.com/ingelibre/"
            "ingetrazo-extensions/main/thumbs/with_shot.webp"]
        assert (tmp_path / "data" / "extension-screenshots"
                / "catalog-thumbs" / f"with_shot-{_SHA_A}.webp").is_file()
    finally:
        _close(dialog, app)


def test_without_a_thumb_the_screenshot_is_fetched_under_its_print(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    dialog_module, _ext = _one_card(tmp_path, monkeypatch,
                                    screenshot_sha=_SHA_A)
    network = _HeldNetwork(lambda url: (_png(), True))
    dialog = _show_with(dialog_module, network, app)
    try:
        assert "with_shot" in dialog._screenshots
        assert network.urls == [
            dialog_module._SCREENSHOT_BASE + "with_shot.png"]
        assert (tmp_path / "data" / "extension-screenshots"
                / f"with_shot-{_SHA_A}.png").is_file()
    finally:
        _close(dialog, app)


def test_a_new_print_under_the_same_name_is_fetched_again(
        tmp_path, monkeypatch):
    """#1296: the cache went by name only, so a screenshot changed in the
    catalog under the same name was never fetched again."""
    app = QApplication.instance() or QApplication([])
    dialog_module, _ext = _one_card(tmp_path, monkeypatch,
                                    thumb="with_shot.webp",
                                    screenshot_sha=_SHA_B)
    folder = tmp_path / "data" / "extension-screenshots" / "catalog-thumbs"
    folder.mkdir(parents=True)
    old = folder / f"with_shot-{_SHA_A}.webp"
    old.write_bytes(_png("blue"))
    unprinted = folder / "with_shot.webp"
    unprinted.write_bytes(_png("blue"))
    other = folder / f"another-{_SHA_A}.webp"
    other.write_bytes(_png("blue"))
    old_scaled = dialog_module.ExtensionManagerDialog._thumb_path(old)
    old_scaled.parent.mkdir(parents=True)
    old_scaled.write_bytes(_png("blue", (256, 160)))
    network = _HeldNetwork(lambda url: (_png("green"), True))
    dialog = _show_with(dialog_module, network, app)
    try:
        assert network.urls == [dialog_module._THUMB_BASE + "with_shot.webp"]
        assert (folder / f"with_shot-{_SHA_B}.webp").is_file()
        assert not old.exists() and not unprinted.exists()
        assert not old_scaled.exists()
        assert other.is_file()                     # another extension's
        label = dialog._pages["browse"]["image_labels"]["with_shot"]
        assert label.pixmap().toImage().pixelColor(5, 5).name() == "#008000"
    finally:
        _close(dialog, app)


def test_a_thumb_github_failed_to_send_is_asked_from_the_website(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    dialog_module, _ext = _one_card(tmp_path, monkeypatch,
                                    thumb="with_shot.webp",
                                    screenshot_sha=_SHA_A)
    network = _HeldNetwork(lambda url: (_png(), "ingetrazo.com" in url))
    dialog = _show_with(dialog_module, network, app)
    try:
        assert "with_shot" in dialog._screenshots
        assert network.urls[:2] == [
            dialog_module._THUMB_BASE + "with_shot.webp",
            "https://ingetrazo.com/extensiones-img/thumbs/with_shot.webp"]
    finally:
        _close(dialog, app)


def test_a_bad_thumb_or_print_is_ignored_and_the_extension_kept():
    base = {
        "id": "sample", "version": "1.0", "author": "A", "license": "MIT",
        "repository": "https://github.com/example/sample",
        "download": "https://example.org/sample.py", "sha256": "a" * 64,
        "ingetrazo": "0.1.0", "name": {"en": "S"}, "summary": {"en": "S"},
        "screenshot": "sample.png"}
    good = manager._parse_extension(
        {**base, "thumb": "sample.webp", "screenshot_sha": _SHA_A})
    assert (good.thumb, good.screenshot_sha) == ("sample.webp", _SHA_A)
    for thumb, sha in (("../sample.webp", "0123456789ABCDEF"),
                       ("a/b.webp", "0123"), ("a\\b.webp", 12345),
                       ("sample.exe", "g" * 16), (7, None), ("", "")):
        parsed = manager._parse_extension(
            {**base, "thumb": thumb, "screenshot_sha": sha})
        assert parsed.id == "sample" and parsed.screenshot == "sample.png"
        assert parsed.thumb is None and parsed.screenshot_sha is None
    old = manager._parse_extension(base)              # an older catalog
    assert old.thumb is None and old.screenshot_sha is None


def test_a_downloaded_picture_is_decoded_once(tmp_path, monkeypatch):
    """#1296: it was decoded to check it and again to scale it, both on
    the UI thread."""
    app = QApplication.instance() or QApplication([])
    dialog_module, _ext = _one_card(tmp_path, monkeypatch,
                                    thumb="with_shot.webp",
                                    screenshot_sha=_SHA_A)
    data = _png()
    decodes = []
    for cls in (dialog_module.QImage, dialog_module.QPixmap):
        for name in ("loadFromData", "load"):
            real = getattr(cls, name)
            monkeypatch.setattr(
                cls, name,
                lambda self, *a, _real=real, _n=f"{cls.__name__}.{name}":
                decodes.append(_n) or _real(self, *a))
    network = _HeldNetwork(lambda url: (data, True))
    dialog = _show_with(dialog_module, network, app)
    try:
        assert "with_shot" in dialog._screenshots
        assert len(network.urls) == 1
        assert decodes == ["QImage.loadFromData"]
    finally:
        _close(dialog, app)
