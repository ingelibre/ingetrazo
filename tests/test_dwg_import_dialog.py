# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #401: the DWG import runs the converter without freezing the
window, and says in the user's language why it failed, timed out or stopped."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton  # noqa: E402

from formats import dwg_bridge  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def window():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


@pytest.fixture
def dialogs(monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda parent, title, text: shown.append((title, text)))
    monkeypatch.setattr(dwg_bridge, "have_dwg_support", lambda: True)
    return shown


def _failing(kind, message):
    def convert(self, dwg_path):
        raise dwg_bridge.DwgBridgeError(message, kind)
    return convert


def test_a_failed_conversion_says_so_with_the_converter_output(
        window, dialogs, monkeypatch):
    monkeypatch.setattr(dwg_bridge.DwgConverter, "convert",
                        _failing("failed", "conversion produced no output: boom"))
    assert window._import_dwg_path(Path("x.dwg")) is False
    (title, text), = dialogs
    assert "boom" in text and "DXF" in text


def test_a_timeout_has_its_own_message(window, dialogs, monkeypatch):
    monkeypatch.setattr(dwg_bridge.DwgConverter, "convert",
                        _failing("timeout", "slow"))
    assert window._import_dwg_path(Path("x.dwg")) is False
    (_, text), = dialogs
    assert "too long" in text


def test_cancel_is_quiet_and_reported_in_the_status_bar(
        window, dialogs, monkeypatch):
    monkeypatch.setattr(dwg_bridge.DwgConverter, "convert",
                        _failing("cancelled", "stop"))
    assert window._import_dwg_path(Path("x.dwg")) is False
    assert dialogs == []
    assert "cancelled" in window.statusBar().currentMessage()


def test_the_progress_dialog_offers_cancel_and_cancel_stops_the_converter(
        window, dialogs, monkeypatch):
    seen = {}

    def convert(self, dwg_path):
        dlg = window._progress_dlg
        seen["buttons"] = [b.text() for b in dlg.findChildren(QPushButton)]
        dlg.cancel()                      # what the Cancel button does
        raise dwg_bridge.DwgBridgeError("stopped", "cancelled")

    cancelled = []
    monkeypatch.setattr(dwg_bridge.DwgConverter, "convert", convert)
    monkeypatch.setattr(dwg_bridge.DwgConverter, "cancel",
                        lambda self: cancelled.append(True))
    window._import_dwg_path(Path("x.dwg"))
    assert seen["buttons"] == ["Cancel"]
    assert cancelled
