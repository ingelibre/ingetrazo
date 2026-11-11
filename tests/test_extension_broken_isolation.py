# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #1152: one extension must never cost the manager or the others.

The reported chain, on Windows: an extension installed from a run as
administrator landed in a folder the same user, running normally, could not
read. The first such folder ended the plugin scan (no extension loaded, built
in ones included) and raised while the manager built its cards (the menu entry
did nothing). Up to Python 3.13 — the packaged builds run 3.12 —
``Path.is_file`` raises on such a path; 3.14 returns False. :func:`py312_paths`
puts the 3.12 behaviour back, so these tests mean the same on every Python.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import stat
import sys
import textwrap
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

_app = QApplication.instance() or QApplication([])

import core.extension_manager as manager                 # noqa: E402
import core.extensions as extensions                     # noqa: E402
from core.extensions import discover_plugins             # noqa: E402

needs_permissions = pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions that bind this user")


def _strict(check):
    def probe(self, **kwargs):
        try:
            return check(self.stat(**kwargs).st_mode)
        except OSError as exc:
            if exc.errno not in (errno.ENOENT, errno.ENOTDIR, errno.EBADF,
                                 errno.ELOOP):
                raise
            return False
    return probe


@pytest.fixture
def py312_paths(monkeypatch):
    monkeypatch.setattr(Path, "is_file", _strict(stat.S_ISREG))
    monkeypatch.setattr(Path, "is_dir", _strict(stat.S_ISDIR))
    monkeypatch.setattr(Path, "exists", _strict(lambda _mode: True))


@pytest.fixture
def plugins(tmp_path, monkeypatch):
    root = tmp_path / "plugins"
    root.mkdir()
    monkeypatch.setattr(manager, "user_plugins_dir", lambda: root)
    monkeypatch.setattr(extensions, "user_plugins_dir", lambda: root)
    locked = []
    yield root
    for path in root.iterdir():
        locked.append(path)
    for path in locked:
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o755)


def _package(root: Path, name: str, source: str = "def setup(app):\n    pass\n",
             managed: bool = False) -> Path:
    folder = root / name
    folder.mkdir()
    (folder / "__init__.py").write_text(textwrap.dedent(source))
    if managed:
        (folder / "extension.json").write_text(
            json.dumps({"id": name, "version": "1.0", "sha256": "0" * 64}))
    return folder


def _extension(ident: str, payload: bytes = b"def setup(app):\n    pass\n"):
    return manager.Extension(
        id=ident, version="1.0", author="Author", license="MIT",
        repository="https://github.com/example/sample",
        download="https://example.org/sample.py",
        sha256=hashlib.sha256(payload).hexdigest(),
        minimum_version="0.1.0", name={"en": ident}, summary={"en": "x"},
        tags=())


# ---- the plugin scan ------------------------------------------------------

@needs_permissions
def test_an_unreadable_folder_costs_only_itself(plugins, py312_paths):
    _package(plugins, "aaa_ok")
    _package(plugins, "locked", managed=True).chmod(0)
    _package(plugins, "zzz_ok")
    found, errors = discover_plugins([plugins])
    assert [p.stem for p in found] == ["aaa_ok", "zzz_ok"]
    assert [e.stem for e in errors] == ["locked"]
    assert "PermissionError" in errors[0].error


@needs_permissions
def test_an_unreadable_plugin_folder_is_not_an_exception(tmp_path, py312_paths):
    root = tmp_path / "shut"
    root.mkdir()
    (tmp_path / "other").mkdir()
    _package(tmp_path / "other", "fine")
    root.chmod(0)
    try:
        found, errors = discover_plugins([root, tmp_path / "other"])
    finally:
        root.chmod(0o755)
    assert [p.stem for p in found] == ["fine"] and errors == []


def test_sys_exit_while_importing_costs_only_that_extension(plugins):
    (plugins / "quits.py").write_text("import sys\nsys.exit(3)\n")
    _package(plugins, "zzz_ok")
    found, errors = discover_plugins([plugins])
    assert [p.stem for p in found] == ["zzz_ok"]
    assert [e.stem for e in errors] == ["quits"]
    assert "SystemExit" in errors[0].error


@pytest.mark.parametrize("inner", [
    "same_name/__init__.py",           # Windows «Extract all» of x.zip: x/x/
    "repo-main/pkg/__init__.py",
    "loose_module.py",
])
def test_a_folder_holding_the_extension_one_level_down_says_so(plugins, inner):
    path = plugins / "same_name" / inner
    path.parent.mkdir(parents=True)
    path.write_text("def setup(app):\n    raise AssertionError('not loaded')\n")
    found, errors = discover_plugins([plugins])
    assert found == []
    assert [e.stem for e in errors] == ["same_name"]
    assert "__init__.py" in errors[0].error
    assert Path(inner).parts[0] in errors[0].error


def test_a_folder_of_plain_data_stays_silent(plugins):
    data = plugins / "presets"
    data.mkdir()
    (data / "a.json").write_text("{}")
    (data / "README.md").write_text("x")
    assert discover_plugins([plugins]) == ([], [])


def test_a_disabled_package_stays_silent(plugins):
    folder = _package(plugins, "off")
    (folder / ".disabled").write_text("")
    assert discover_plugins([plugins]) == ([], [])


def test_a_load_failure_reaches_the_error_log(plugins, tmp_path, monkeypatch):
    import core.paths
    monkeypatch.setattr(core.paths, "user_log_dir", lambda: tmp_path)
    (plugins / "broken.py").write_text("raise RuntimeError('boom 1152')\n")
    discover_plugins([plugins])
    log = (tmp_path / "ingetrazo-errors.log").read_text(encoding="utf-8")
    assert "broken" in log and "boom 1152" in log and "Traceback" in log


# ---- the manager's own reads ----------------------------------------------

@needs_permissions
def test_the_manager_reads_survive_an_unreadable_folder(plugins, py312_paths):
    folder = _package(plugins, "locked", managed=True)
    folder.chmod(0)
    assert manager.installed_info("locked") is None
    assert manager.installation_conflict("locked") is True
    assert manager.is_extension_enabled("locked") is False
    assert manager.extension_startup_state() == {}
    assert manager.hand_installed_plugins() == [folder]
    assert manager.retired_extensions(["other"]) == []
    assert manager.manual_copies("x", plugins) == []


@needs_permissions
def test_an_unreadable_folder_can_be_replaced_without_rights_on_it(
        plugins, py312_paths, monkeypatch):
    payload = b"def setup(app):\n    pass\n"
    extension = _extension("locked", payload)
    monkeypatch.setattr(manager, "_get", lambda *_args: payload)
    _package(plugins, "locked", managed=True).chmod(0)
    asides = manager.replace_hand_installed(extension)
    assert manager.installed_info("locked")["version"] == "1.0"
    assert (plugins / "locked" / "__init__.py").read_bytes() == payload
    assert len(asides) == 1 and asides[0].name.startswith(".locked")
    asides[0].chmod(0o755)


@pytest.mark.parametrize("content", [
    b"\xff\xfe\x00 not json", b"[1, 2]", b'{"id": 7}', b"",
])
def test_a_corrupt_extension_record_is_not_fatal(plugins, content):
    folder = _package(plugins, "sample")
    (folder / "extension.json").write_bytes(content)
    assert manager.installed_info("sample") is None
    assert manager.extension_startup_state() == {}
    assert manager.installation_conflict("sample") is True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_an_installed_folder_keeps_the_folders_normal_permissions(
        plugins, monkeypatch):
    # tempfile.mkdtemp's 0o700 is, on Windows, the private ACL behind #1152.
    # The mode is what can be seen from here; the Windows side is on the
    # round's checklist.
    payload = b"def setup(app):\n    pass\n"
    monkeypatch.setattr(manager, "_get", lambda *_args: payload)
    old = os.umask(0o022)
    try:
        manager.install_extension(_extension("sample", payload))
    finally:
        os.umask(old)
    assert stat.S_IMODE((plugins / "sample").stat().st_mode) == 0o755


# ---- the dialog -----------------------------------------------------------

def _stub_catalog(monkeypatch, module, catalog):
    snapshot = manager.CatalogSnapshot(
        catalog, {}, "2026-11-03T10:00:00+00:00", False)
    monkeypatch.setattr(module, "load_cached_catalog", lambda: snapshot)
    monkeypatch.setattr(module, "refresh_catalog", lambda: snapshot)
    monkeypatch.setattr(module, "bundled_extensions", lambda: [])


def _settle(dialog):
    dialog.resize(1180, 800)
    dialog.show()
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(
        lambda: loop.quit()
        if (dialog._catalog_snapshot is not None
            and not dialog._initial_load_timer.isActive()
            and dialog._catalog_worker is None
            and not dialog._pages["browse"]["dirty"]
            and not dialog._pages["browse"]["render_timer"].isActive()
            and not dialog._pages["browse"]["pending_indices"]) else None)
    timer.start()
    QTimer.singleShot(15000, loop.quit)
    loop.exec()
    timer.stop()


@needs_permissions
def test_the_manager_opens_with_an_unreadable_extension(
        plugins, py312_paths, monkeypatch):
    from views import extension_manager_dialog as module
    _stub_catalog(monkeypatch, module,
                  [_extension("locked"), _extension("other")])
    _package(plugins, "locked", managed=True).chmod(0)
    dialog = module.ExtensionManagerDialog()
    try:
        _settle(dialog)
        cards = dialog._pages["browse"]["cards"]
        texts = {label.text() for label in cards.findChildren(QLabel)}
        assert {"locked", "other"} <= texts
        buttons = {b.text() for b in cards.findChildren(QPushButton)}
        assert "Replace with the catalog version" in buttons
    finally:
        dialog.close()
        dialog.deleteLater()


def test_a_card_that_cannot_be_built_costs_only_itself(plugins, monkeypatch):
    from views import extension_manager_dialog as module
    _stub_catalog(monkeypatch, module, [_extension("bad"), _extension("good")])
    real = module.ExtensionManagerDialog._make_row

    def make_row(self, extension, *args):
        if extension.id == "bad":
            raise ValueError("this card")
        return real(self, extension, *args)

    monkeypatch.setattr(module.ExtensionManagerDialog, "_make_row", make_row)
    dialog = module.ExtensionManagerDialog()
    try:
        _settle(dialog)
        cards = dialog._pages["browse"]["cards"]
        assert "good" in {label.text() for label in cards.findChildren(QLabel)}
        assert "bad" not in {label.text()
                             for label in cards.findChildren(QLabel)}
    finally:
        dialog.close()
        dialog.deleteLater()


# ---- the window -----------------------------------------------------------

def _close(window):
    window._saved_version = window.viewport.scene.version   # no "save?" modal
    window.close()


@pytest.fixture
def window():
    from views.main_window import MainWindow
    win = MainWindow(defer_extensions=True)
    yield win
    _close(win)


def test_a_manager_that_fails_to_open_says_so(window, monkeypatch):
    from views import extension_manager_dialog as module
    shown = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda _parent, _title, text: shown.append(text))

    def explode(_parent):
        raise PermissionError(13, "denied")

    monkeypatch.setattr(module, "ExtensionManagerDialog", explode)
    window._on_manage_extensions()
    assert len(shown) == 1 and "denied" in shown[0]


def test_sys_exit_in_setup_costs_only_that_extension(
        window, plugins, monkeypatch):
    _package(plugins, "aaa_quits", """\
        import sys
        def setup(app):
            sys.exit(0)
        """)
    _package(plugins, "zzz_ok", """\
        def setup(app):
            app.add_menu_action("ZZZ fine", lambda: None)
        """)
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [plugins])
    window.load_extensions()
    texts = []
    for action in window._ext_menu.actions():
        texts.append(action.text())
        if action.menu() is not None:
            texts += [a.text() for a in action.menu().actions()]
    assert "ZZZ fine" in texts
    assert "aaa_quits" in window._extension_load_errors


def test_a_tool_with_an_unusable_entry_costs_only_itself(
        window, plugins, monkeypatch):
    (plugins / "aaa_bad.py").write_text(textwrap.dedent("""\
        from tools.base import Tool
        class Bad(Tool):
            name = "Bad tool"
            description = "bad"
            shortcut = ["not", "a", "key"]
            def on_activate(self, viewport): pass
            def on_deactivate(self, viewport): pass
        """))
    (plugins / "zzz_good.py").write_text(textwrap.dedent("""\
        from tools.base import Tool
        class Good(Tool):
            name = "Good tool"
            description = "good"
            def on_activate(self, viewport): pass
            def on_deactivate(self, viewport): pass
        """))
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [plugins])
    window.load_extensions()
    assert any(key.endswith("zzz_good_Good") for key in window._tools)
    assert not any(key.endswith("aaa_bad_Bad") for key in window._tools)
    assert "Good tool" in [a.text() for a in window._ext_menu.actions()]
