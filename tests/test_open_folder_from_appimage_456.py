# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""«Open extensions folder» from the AppImage hands the host its own
environment.

#456 (@architecturep, AppImage): the click did nothing. Qt passed
``xdg-open`` the frozen build's environment — PyInstaller's
``LD_LIBRARY_PATH`` on the bundled libraries and the AppRun's
``GIO_MODULE_DIR`` on an empty folder of ours — and the host's file
manager died on them."""
from __future__ import annotations

from pathlib import Path

import pytest

import core.desktop_open as D

APPIMAGE_ENV = {
    "APPDIR": "/tmp/.mount_IngeTrAbc",
    "APPIMAGE": "/home/u/IngeTrazo.AppImage",
    "GIO_MODULE_DIR": "/tmp/.mount_IngeTrAbc/usr/lib/gio/modules",
    "LD_LIBRARY_PATH": "/tmp/.mount_IngeTrAbc/usr/bin/_internal",
    "LD_LIBRARY_PATH_ORIG": "/usr/local/lib",
    "QT_QPA_PLATFORM": "wayland;xcb",
    "HOME": "/home/u",
}


def test_host_env_drops_what_the_bundle_set_for_itself():
    env = D.host_env(APPIMAGE_ENV)
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert "GIO_MODULE_DIR" not in env
    assert "QT_QPA_PLATFORM" not in env
    assert env["HOME"] == "/home/u"


def test_a_host_gio_module_dir_is_left_alone():
    env = D.host_env({**APPIMAGE_ENV, "GIO_MODULE_DIR": "/usr/lib/gio"})
    assert env["GIO_MODULE_DIR"] == "/usr/lib/gio"


@pytest.fixture
def frozen_appimage(monkeypatch):
    monkeypatch.setattr(D.sys, "platform", "linux")
    monkeypatch.setattr(D.sys, "frozen", True, raising=False)
    monkeypatch.setattr(D.os, "environ", dict(APPIMAGE_ENV))
    monkeypatch.setattr(D.shutil, "which", lambda name: "/usr/bin/xdg-open")
    calls = []
    monkeypatch.setattr(D.subprocess, "Popen",
                        lambda cmd, **kw: calls.append((cmd, kw)))
    return calls


def test_the_folder_opens_through_xdg_open_with_the_host_env(frozen_appimage):
    assert D.open_url(Path("/home/u/.local/share/IngeTrazo/plugins"))
    (cmd, kw), = frozen_appimage
    assert cmd == ["/usr/bin/xdg-open", "/home/u/.local/share/IngeTrazo/plugins"]
    assert kw["env"]["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert "GIO_MODULE_DIR" not in kw["env"]


def test_a_web_page_too(frozen_appimage):
    D.open_url("https://ingetrazo.com/extensiones")
    (cmd, _kw), = frozen_appimage
    assert cmd[1] == "https://ingetrazo.com/extensiones"


@pytest.mark.parametrize("box", ["FLATPAK_ID", "SNAP"])
def test_flatpak_and_snap_keep_their_portal(frozen_appimage, monkeypatch, box):
    monkeypatch.setitem(D.os.environ, box, "x")
    opened = []
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url) or True))
    D.open_url(Path("/tmp/x"))
    assert not frozen_appimage and len(opened) == 1
