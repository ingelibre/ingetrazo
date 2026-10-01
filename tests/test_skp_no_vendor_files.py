# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""No third-party vendor files (copyright notice, 2026-09-28): a .skp the
built-in reader cannot open is reported -- no converter runs, nothing is
downloaded -- there is no .skp export, and no bundle carries openskp's
SDK-written blank template."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]


def test_an_unreadable_skp_is_reported_and_nothing_else_runs(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    from views.main_window import MainWindow

    for name in ("_find_skp_converter", "_install_skp_converter",
                 "_extract_skp_dlls", "_on_export_skp"):
        assert not hasattr(MainWindow, name), name
    said = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: said.append(a[2]) or QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: pytest.fail("asked to install something")))
    import subprocess
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: pytest.fail("ran an external program"))
    win = MainWindow()
    try:
        bad = tmp_path / "roto.skp"
        bad.write_bytes(b"not a .skp file at all")
        assert win.import_skp_path(bad) is False
        assert said and "COLLADA" in said[-1]
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_no_skp_export_in_the_menu():
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        exports = []
        for action in win.menuBar().actions():
            menu = action.menu()
            if menu is None:
                continue
            for sub in menu.actions():
                inner = sub.menu()
                if inner is not None and sub.text().replace("&", "") in ("Export", "Exportar"):
                    exports += [a.text() for a in inner.actions()]
        assert exports, "no Export menu found"
        assert not [t for t in exports if ".skp" in t], exports
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_bundle_spec_leaves_the_sdk_template_out():
    text = (ROOT / "ingetrazo.spec").read_text(encoding="utf-8")
    assert "'_scaffold' not in src" in text
    flatpak = (ROOT / "packaging/flatpak/com.ingetrazo.IngeTrazo.yml").read_text(encoding="utf-8")
    assert "openskp/_scaffold" in flatpak and "rm -rf" in flatpak
    snap = (ROOT / "packaging/snap/snapcraft.yaml.in").read_text(encoding="utf-8")
    assert "_scaffold" in snap
