# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""File dialogs start in the last folder the user chose, not in the folder
the program is installed in (Marco, 2026-09-07)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QFileDialog

from views import filedialogs
from views.filedialogs import file_dialogs, last_dir, remember, start_in

_app = QApplication.instance() or QApplication([])


def _fresh():
    QSettings().remove("files/last_dir")


def test_nothing_remembered_means_documents_or_a_fallback(tmp_path):
    _fresh()
    assert last_dir() and os.path.isdir(last_dir())
    assert last_dir(tmp_path) == str(tmp_path)            # the open document's folder
    assert start_in("", tmp_path) == str(tmp_path)
    assert start_in("lamina.pdf", tmp_path) == os.path.join(str(tmp_path), "lamina.pdf")


def test_the_chosen_folder_is_remembered_and_reused(tmp_path):
    _fresh()
    chosen = tmp_path / "planos" / "lamina.pdf"
    chosen.parent.mkdir()
    remember(chosen)
    assert last_dir() == str(chosen.parent)
    assert start_in("") == str(chosen.parent)
    assert start_in("vista.dxf") == str(chosen.parent / "vista.dxf")
    # a start directory the caller chose is respected
    other = tmp_path / "otra"; other.mkdir()
    assert start_in(str(other)) == str(other)
    assert start_in(str(other / "x.igz")) == str(other / "x.igz")
    # a remembered folder that vanished is not used
    QSettings().setValue("files/last_dir", str(tmp_path / "borrada"))
    assert last_dir(tmp_path) == str(tmp_path)


def test_the_shim_feeds_the_dialog_and_learns_from_it(tmp_path, monkeypatch):
    _fresh()
    seen = {}

    def fake_save(parent, caption="", dir="", filter="", *a, **k):
        seen["dir"] = dir
        return (str(tmp_path / "salida" / "lamina.pdf"), filter)
    (tmp_path / "salida").mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake_save))
    remember(tmp_path)
    path, _ = file_dialogs.getSaveFileName(None, "Export PDF…", "lamina.pdf", "PDF (*.pdf)")
    assert seen["dir"] == str(tmp_path / "lamina.pdf")   # started where the user was
    assert last_dir() == str(tmp_path / "salida")         # …and learnt the new folder

    def fake_open(parent, caption="", dir="", filter="", *a, **k):
        seen["open"] = dir
        return ("", "")                                    # cancelled
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(fake_open))
    file_dialogs.getOpenFileName(None, "Open", "", "IGZ (*.igz)")
    assert seen["open"] == str(tmp_path / "salida")
    assert last_dir() == str(tmp_path / "salida")         # a cancel changes nothing


def test_with_nothing_remembered_a_dialog_starts_beside_the_open_document(tmp_path, monkeypatch):
    _fresh()
    (tmp_path / "proyecto").mkdir()

    class _Win:                      # the main window, as the shim sees it
        _current_path = tmp_path / "proyecto" / "poste.igz"

    class _Composer:                 # a composer: its parent is _window
        _window = _Win()
    seen = {}

    def fake_save(parent, caption="", dir="", filter="", *a, **k):
        seen["dir"] = dir
        return ("", "")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake_save))
    file_dialogs.getSaveFileName(_Composer(), "Export PDF…", "lamina.pdf", "PDF (*.pdf)")
    assert seen["dir"] == str(tmp_path / "proyecto" / "lamina.pdf")
