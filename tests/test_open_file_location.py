# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Open File Location: on a project tab's right-click menu and in the File
menu, it opens the folder that holds the project's file with the file
picked out in it — Explorer on Windows, Finder on macOS, the freedesktop
file manager on Linux (the folder alone when none answers). A project
never saved has no folder: the item is greyed out."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import core.desktop_open as D

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


# ---- reveal_in_folder -----------------------------------------------------
@pytest.fixture
def launched(monkeypatch):
    """Commands started (none really run) and folders opened."""
    calls = {"popen": [], "run": [], "opened": []}
    monkeypatch.setattr(D.subprocess, "Popen",
                        lambda cmd, **kw: calls["popen"].append(cmd))
    monkeypatch.setattr(D, "open_url",
                        lambda target: calls["opened"].append(target) or True)
    return calls


@pytest.fixture
def igz(tmp_path):
    f = tmp_path / "carpeta con espacios" / "casa.igz"
    f.parent.mkdir()
    f.write_bytes(b"PK")
    return f


def test_windows_explorer_picks_the_file_out(monkeypatch, launched, igz):
    monkeypatch.setattr(D.sys, "platform", "win32")
    assert D.reveal_in_folder(igz)
    cmd, = launched["popen"]
    # One string: «/select,» then the path in quotes, spaces and all.
    assert cmd.startswith('explorer /select,"') and cmd.endswith('"')
    assert Path(cmd[len('explorer /select,"'):-1]) == igz.absolute()
    assert not launched["opened"]


def test_macos_finder_picks_the_file_out(monkeypatch, launched, igz):
    monkeypatch.setattr(D.sys, "platform", "darwin")
    assert D.reveal_in_folder(igz)
    assert launched["popen"] == [["open", "-R", str(igz.absolute())]]


def test_linux_asks_the_file_manager_over_dbus(monkeypatch, launched, igz):
    monkeypatch.setattr(D.sys, "platform", "linux")
    monkeypatch.setattr(D.shutil, "which", lambda n: "/usr/bin/dbus-send")
    sent = []

    def run(cmd, **kw):
        sent.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(D.subprocess, "run", run)
    assert D.reveal_in_folder(igz)
    cmd, = sent
    assert "org.freedesktop.FileManager1.ShowItems" in cmd
    assert f"array:string:{igz.absolute().as_uri()}" in cmd
    assert not launched["opened"]


def test_linux_without_a_file_manager_opens_the_folder(monkeypatch,
                                                       launched, igz):
    monkeypatch.setattr(D.sys, "platform", "linux")
    monkeypatch.setattr(D.shutil, "which", lambda n: "/usr/bin/dbus-send")
    monkeypatch.setattr(D.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1))
    assert D.reveal_in_folder(igz)
    assert launched["opened"] == [igz.absolute().parent]


def test_linux_without_dbus_send_opens_the_folder(monkeypatch, launched, igz):
    monkeypatch.setattr(D.sys, "platform", "linux")
    monkeypatch.setattr(D.shutil, "which", lambda n: None)
    assert D.reveal_in_folder(igz)
    assert launched["opened"] == [igz.absolute().parent]


def test_a_file_gone_opens_the_folder_it_was_in(monkeypatch, launched, igz):
    monkeypatch.setattr(D.sys, "platform", "win32")
    igz.unlink()
    assert D.reveal_in_folder(igz)
    assert launched["opened"] == [igz.absolute().parent]
    assert not launched["popen"]


def test_nothing_to_open(launched, tmp_path):
    assert not D.reveal_in_folder(None)
    assert not D.reveal_in_folder(tmp_path / "no" / "esta.igz")
    assert not launched["popen"] and not launched["opened"]


# ---- the menus ------------------------------------------------------------
@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    for doc in list(w._documents):
        doc.saved_content = doc.viewport.scene.content_version
    w._saved_version = w.viewport.scene.version
    w.close()


@pytest.fixture
def revealed(monkeypatch):
    got = []
    monkeypatch.setattr(D, "reveal_in_folder",
                        lambda path: got.append(Path(path)) or True)
    return got


def _item(menu):
    from core.i18n import tr
    acts = [a for a in menu.actions() if a.text() == tr("Open File Location")]
    assert len(acts) == 1
    return acts[0]


def _file_menu(win):
    # Through the QMenu objects, not QAction.menu(): PySide can hand back
    # a dead wrapper for that one.
    from PySide6.QtWidgets import QMenu
    from core.i18n import tr
    top = win.menuBar().actions()
    menu, = [m for m in win.findChildren(QMenu)
             if m.title() == tr("File") and m.menuAction() in top]
    return menu


def test_the_tab_menu_opens_that_projects_folder(win, revealed, tmp_path):
    """A tab in the back: its own file, not the one that was in front."""
    a = win._doc
    b = win._new_document()
    a.path = tmp_path / "a.igz"
    b.path = tmp_path / "otra" / "b.igz"
    menu = win._build_project_tab_menu(b)
    act = _item(menu)
    assert act.isEnabled() and act.statusTip()
    act.trigger()
    assert revealed == [tmp_path / "otra" / "b.igz"]
    menu.close()


def test_the_tab_menu_greys_it_out_for_a_project_never_saved(win, revealed):
    assert win._doc.path is None
    menu = win._build_project_tab_menu(win._doc)
    act = _item(menu)
    assert not act.isEnabled()
    menu.close()
    assert not win.open_file_location()
    assert not revealed


def test_the_file_menu_has_it_after_save_as(win, revealed, tmp_path):
    from core.i18n import tr
    menu = _file_menu(win)
    texts = [a.text() for a in menu.actions()]
    i = texts.index(tr("Save As…"))
    assert texts[i + 1] == tr("Open File Location")
    act = _item(menu)
    menu.aboutToShow.emit()
    assert not act.isEnabled(), "never saved: no folder yet"
    win._doc.path = tmp_path / "casa.igz"
    menu.aboutToShow.emit()
    assert act.isEnabled()
    act.trigger()
    assert revealed == [tmp_path / "casa.igz"]


def test_the_file_menu_follows_the_project_in_front(win, revealed, tmp_path):
    a = win._doc
    b = win._new_document()
    a.path = tmp_path / "a.igz"
    win.activate_document(b)
    act = _item(_file_menu(win))
    _file_menu(win).aboutToShow.emit()
    assert not act.isEnabled()
    win.activate_document(a)
    _file_menu(win).aboutToShow.emit()
    assert act.isEnabled()
    act.trigger()
    assert revealed == [tmp_path / "a.igz"]
