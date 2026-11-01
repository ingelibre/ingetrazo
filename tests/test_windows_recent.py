# SPDX-License-Identifier: GPL-3.0-or-later
"""Taskbar reporting must not break document operations or pollute test history."""
from types import SimpleNamespace

import pytest

from core import windows_recent as shell


def test_disabled_on_other_platforms(monkeypatch, tmp_path):
    monkeypatch.setattr(shell.sys, "platform", "linux")
    monkeypatch.setattr(shell, "_active_app_id", "test")
    assert not shell.initialize()
    assert not shell.add_recent_document(tmp_path / "model.igz")


def test_not_active_until_gui_initializes(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "_active_app_id", None)
    assert not shell.add_recent_document(tmp_path / "model.igz")


@pytest.mark.parametrize("name", ["missing.igz", "missing.skp", "export.obj", ""])
def test_missing_or_unsupported_files_are_ignored(monkeypatch, tmp_path, name):
    monkeypatch.setattr(shell.sys, "platform", "win32")
    monkeypatch.setattr(shell, "_active_app_id", "test")
    if name == "export.obj":
        (tmp_path / name).write_text("exported geometry")
    assert not shell.add_recent_document(tmp_path / name)


def test_frozen_command_quotes_unicode_document(monkeypatch, tmp_path):
    monkeypatch.setattr(shell.sys, "frozen", True, raising=False)
    monkeypatch.setattr(shell.sys, "executable", r"C:\Program Files\IngeTrazo\ingetrazo.exe")
    path = tmp_path / "house café 模型.igz"
    executable, arguments = shell._launch_command(path)
    assert executable == shell.sys.executable
    assert arguments == '--new-window "' + str(path) + '"'


def test_source_command_also_runs_entry_point(monkeypatch, tmp_path):
    monkeypatch.delattr(shell.sys, "frozen", raising=False)
    _, arguments = shell._launch_command(tmp_path / "model.igz")
    assert "main.py" in arguments
    assert str(tmp_path / "model.igz") in arguments


def test_shell_failure_does_not_fail_document_operation(monkeypatch, tmp_path):
    path = tmp_path / "model.igz"
    path.write_text("{}")
    monkeypatch.setattr(shell.sys, "platform", "win32")
    monkeypatch.setattr(shell, "_active_app_id", "test")

    def unavailable():
        raise OSError("shell unavailable")

    monkeypatch.setattr(shell, "_com", unavailable)
    assert not shell.add_recent_document(path)


def test_native_recent_reports_to_windows_after_settings_update(monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from views.main_window import MainWindow

    path = tmp_path / "saved.igz"
    path.write_text("{}")
    reported = []

    def record(document):
        assert str(path.resolve()) in QSettings().value("recent_files", [])
        reported.append(document)

    monkeypatch.setattr(shell, "add_recent_document", record)
    window = SimpleNamespace(_RECENT_MAX=10, _recent_paths=lambda: [])
    MainWindow._remember_recent(window, path)
    assert reported == [path]
    MainWindow._remember_recent(window, tmp_path / "ignored.skp")
    assert reported == [path]  # imports are reported only AFTER successful parsing


def test_skp_success_reports_import_and_failure_does_not(monkeypatch, tmp_path):
    from formats import skp as skp_format
    from views.main_window import MainWindow

    reported = []
    monkeypatch.setattr(shell, "add_recent_document", reported.append)
    # Exercise the actual importer, stubbing IO/geometry only. The existing
    # SKP tests cover its payload/geometry; this tests the reporting boundary.
    monkeypatch.setattr(skp_format, "can_handle", lambda *_: True)
    window = MainWindow()
    try:
        monkeypatch.setattr(window, "_parse_skp_threaded",
                            lambda *_: ({"empty": True}, None))
        monkeypatch.setattr(window.viewport.history, "execute", lambda *_: None)
        monkeypatch.setattr(window, "_prepare_import_display", lambda *_: None)
        path = tmp_path / "import.skp"
        path.write_text("test")
        assert window.import_skp_path(path)
        assert reported == [path]
        monkeypatch.setattr(window, "_parse_skp_threaded",
                            lambda *_: (None, RuntimeError("invalid SKP")))
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "critical", lambda *_: None)
        assert not window.import_skp_path(path)
        assert reported == [path]
    finally:
        window._saved_version = window.viewport.scene.version
        window.close()
