# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Open a folder, a file or a web page with the desktop's own program.

A frozen Linux build runs with an environment made for IT: PyInstaller's
``LD_LIBRARY_PATH`` points at the bundled libraries, and the AppImage's
AppRun points ``GIO_MODULE_DIR`` at an empty folder of ours. Qt hands that
environment to ``xdg-open``, and the host's file manager or browser loads
our libraries and dies without a word — «Open extensions folder» did
nothing in the AppImage (#456). There we launch ``xdg-open`` ourselves with
the host's environment back; everywhere else (source, Flatpak and snap,
which go through their portals, Windows, macOS) Qt does it as before.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _launch_ourselves(environ=None) -> bool:
    env = os.environ if environ is None else environ
    if not sys.platform.startswith("linux") or not getattr(sys, "frozen", False):
        return False
    return not env.get("FLATPAK_ID") and not env.get("SNAP")


def host_env(environ=None) -> dict:
    """The environment a host program expects: the Blender child's
    (``core.render_blender.clean_env``) without the AppImage's GIO
    redirect either."""
    from core.render_blender import clean_env
    env = clean_env(environ)
    gio, appdir = env.get("GIO_MODULE_DIR", ""), env.get("APPDIR", "")
    if gio and appdir and gio.startswith(appdir):
        env.pop("GIO_MODULE_DIR")
    return env


def open_url(target) -> bool:
    """Open ``target`` — a ``Path``, a path string, an ``http(s)`` URL or a
    ``QUrl`` — with the desktop's program for it."""
    from PySide6.QtCore import QUrl
    if isinstance(target, Path):
        url = QUrl.fromLocalFile(str(target))
    elif isinstance(target, QUrl):
        url = target
    elif "://" in str(target):
        url = QUrl(str(target))
    else:
        url = QUrl.fromLocalFile(str(target))
    opener = shutil.which("xdg-open") if _launch_ourselves() else None
    if opener:
        arg = url.toLocalFile() if url.isLocalFile() else url.toString()
        try:
            subprocess.Popen([opener, arg], env=host_env(),
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return True
        except OSError:
            pass
    from PySide6.QtGui import QDesktopServices
    return QDesktopServices.openUrl(url)


def _reveal_command(path: Path):
    """The command that opens the folder of ``path`` with the file picked
    out in it, or None where the system has no such command (Linux: the
    file manager is asked over D-Bus, ``_ask_file_manager``)."""
    if sys.platform == "win32":
        # One string, not a list: Explorer reads «/select,» and the quoted
        # path as they are, and a list quotes the two together.
        return f'explorer /select,"{os.path.normpath(str(path))}"'
    if sys.platform == "darwin":
        return ["open", "-R", str(path)]
    return None


def _ask_file_manager(path: Path) -> bool:
    """Linux and the BSDs: the freedesktop FileManager1 service shows the
    file picked out in its folder (Files, Dolphin, Nemo, Caja, Thunar…).
    False when there is no ``dbus-send`` or no file manager answers."""
    sender = shutil.which("dbus-send")
    if not sender:
        return False
    env = host_env() if _launch_ourselves() else None
    try:
        done = subprocess.run(
            [sender, "--session", "--print-reply",
             "--dest=org.freedesktop.FileManager1",
             "/org/freedesktop/FileManager1",
             "org.freedesktop.FileManager1.ShowItems",
             f"array:string:{path.as_uri()}", "string:"],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def reveal_in_folder(path) -> bool:
    """Open the folder that holds ``path`` with the file picked out in it
    (File ▸ Open File Location). A file that is gone opens the folder it
    was in, if that is still there. False when there is nothing to open."""
    if not path:
        return False
    path = Path(path).absolute()
    if not path.exists():
        folder = path.parent
        return folder.is_dir() and open_url(folder)
    cmd = _reveal_command(path)
    if cmd is not None:
        try:
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except OSError:
            pass
    elif _ask_file_manager(path):
        return True
    return open_url(path.parent if path.is_file() else path)
