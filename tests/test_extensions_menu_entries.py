# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Extensions menu's own entries all work. «Develop an extension…» lost
the guide's address when the example-extensions submenu went away and did
nothing but raise (app bench, 10-10)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_develop_an_extension_opens_the_guide(monkeypatch):
    from PySide6.QtGui import QDesktopServices
    from views.main_window import MainWindow
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toString()) or True))
    win = MainWindow()
    try:
        win._on_develop_plugin()
        assert opened and opened[0].endswith("docs/plugins.md")
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_manage_extensions_reuses_the_dialog_and_its_card_cache(monkeypatch):
    from views.extension_manager_dialog import ExtensionManagerDialog
    from views.main_window import MainWindow
    opened = []
    monkeypatch.setattr(
        ExtensionManagerDialog, "exec",
        lambda dialog: opened.append(dialog) or 0)
    win = MainWindow()
    try:
        win._on_manage_extensions()
        first = win._extension_manager_dialog
        win._on_manage_extensions()
        assert win._extension_manager_dialog is first
        assert opened == [first, first]
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_extension_restart_relaunches_the_current_document(
        tmp_path, monkeypatch):
    from PySide6.QtCore import QProcess
    from views.main_window import MainWindow

    class FakeWindow:
        _current_path = tmp_path / "drawing.igz"
        _restart_confirmed = False

        @staticmethod
        def _new_window_command():
            return ["ingetrazo", "--new-window"]

        @staticmethod
        def _save_window_settings():
            pass

        def close(self):
            self.closed = True

    win = FakeWindow()
    launched = []
    monkeypatch.setattr(
        QProcess, "startDetached",
        staticmethod(lambda program, args:
                     launched.append((program, args)) or True))
    assert MainWindow._launch_extension_restart(win)
    assert launched == [
        ("ingetrazo", ["--new-window", str(tmp_path / "drawing.igz")])]
    assert win.closed
    assert win._restart_confirmed


def test_cancelled_extension_restart_request_is_consumed(monkeypatch):
    from views.main_window import MainWindow

    class FakeDialog:
        _restart_requested = True

        @staticmethod
        def exec():
            pass

    class FakeWindow:
        _extension_manager_dialog = FakeDialog()

        def _prepare_extension_restart(self):
            return False

        def _launch_extension_restart(self):
            raise AssertionError("cancelled restart must not launch")

    win = FakeWindow()
    MainWindow._on_manage_extensions(win)
    assert not win._extension_manager_dialog._restart_requested
