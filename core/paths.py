# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Where the application's data files live, running from the repo or frozen.

A PyInstaller build unpacks the bundled data under ``sys._MEIPASS`` and
synthesises ``__file__`` for modules inside the archive, so every path derived
from ``__file__`` alone points somewhere that only works while the bundle
layout happens to mirror the repo. Each place that reads a shader, a
translation, a texture or a component goes through ``app_root()`` instead, so
there is one answer to "where am I installed". (Same contract as IngeCAD's
``core/paths.py`` — keep both in sync.)
"""
from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    """The directory holding ``resources/`` and ``i18n/``."""
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen)
    return Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    """True in a PyInstaller bundle. For messages that differ when packaged."""
    return getattr(sys, "frozen", False) is True


def user_log_dir() -> Path:
    """A writable folder for the black-box logs (crash / failed commands).

    Never the install folder: on Windows the installer lands in Program
    Files, read-only for users, and a relative ``open("…log", "a")`` at
    startup raised PermissionError — whose fallback touched ``sys.stderr``,
    None in a windowed build, so v0.3.8/v0.3.9 died before showing a window
    ("sys.stderr is None"). Windows: ``%LOCALAPPDATA%\\IngeTrazo``; macOS:
    ``~/Library/Logs/IngeTrazo``; elsewhere ``$XDG_STATE_HOME/ingetrazo`` or
    ``~/.local/state/ingetrazo``; the temp dir as the last resort."""
    import os
    import tempfile
    home = Path.home()
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        candidates = [Path(base) / "IngeTrazo"]
    elif sys.platform == "darwin":
        candidates = [home / "Library" / "Logs" / "IngeTrazo"]
    else:
        state = os.environ.get("XDG_STATE_HOME") or str(home / ".local" / "state")
        candidates = [Path(state) / "ingetrazo"]
    candidates.append(Path(tempfile.gettempdir()) / "ingetrazo")
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".write-test"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
            return d
        except OSError:
            continue
    return Path(tempfile.gettempdir())


def open_crash_log(name: str = "ingetrazo-crash.log"):
    """An append handle for the faulthandler black box, or None when no
    location is writable at all — callers must then leave faulthandler on
    its default only if ``sys.stderr`` exists."""
    path = user_log_dir() / name
    prune_handled_com_errors(path)
    try:
        return open(path, "a", encoding="utf-8")
    except OSError:
        return None


_CRASH_HEADERS = ("Windows fatal exception:", "Fatal Python error:")


def prune_handled_com_errors(path) -> None:
    """Drop from the crash log the entries of COM errors that were raised
    and handled, with the app still running: on Windows faulthandler logs
    every SEH exception with the error bit set, and UI Automation (screen
    readers, test tools) raises RPC errors such as 0x8001010d by the
    dozen — the log filled with «fatal» entries that were not crashes and
    hid the one that was (#763). Only codes of the RPC facility
    (0x8001xxxx) go; an access violation or any other code stays."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    if "code 0x8001" not in text:
        return
    kept, block, drop = [], [], False
    for line in text.splitlines(keepends=True):
        if line.startswith(_CRASH_HEADERS):
            if not drop:
                kept.extend(block)
            block = []
            drop = line.lower().startswith(
                "windows fatal exception: code 0x8001")
        block.append(line)
    if not drop:
        kept.extend(block)
    try:
        Path(path).write_text("".join(kept), encoding="utf-8")
    except OSError:
        pass
