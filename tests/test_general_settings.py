# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Preferences ▸ General survives a restart (#266, @parampreetss).

Qt's INI writes a group called «general» (any case) as ``[%General]`` and
a NEW process reads it back as ``General/…``. Everything was stored as
``general/…``, which only Qt's in-process cache could find: after a
restart the theme came back dark and the other General settings to their
defaults. Each check that matters runs the read in a separate process —
the same process would answer from that cache and prove nothing.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSettings

from core import general_settings

APP = Path(__file__).resolve().parents[1]


def _read_in_new_process(ini: Path, name: str) -> str:
    code = (
        "from PySide6.QtCore import QSettings\n"
        "from core import general_settings\n"
        f"st = QSettings({str(ini)!r}, QSettings.IniFormat)\n"
        f"print(general_settings.value({name!r}, 'MISSING', st))\n")
    out = subprocess.run([sys.executable, "-c", code], cwd=APP,
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_a_general_setting_survives_a_restart(tmp_path):
    ini = tmp_path / "IngeTrazo.conf"
    st = QSettings(str(ini), QSettings.IniFormat)
    general_settings.set_value("theme", "light", st)
    st.sync()
    assert "[%General]" in ini.read_text()
    assert _read_in_new_process(ini, "theme") == "light"


def test_what_earlier_versions_saved_is_still_read(tmp_path):
    # Written by 0.5.7 as general/theme: the file is the reporter's.
    ini = tmp_path / "IngeTrazo.conf"
    ini.write_text("[%General]\nautosave=0\ntheme=light\nundo_steps=50\n")
    assert _read_in_new_process(ini, "theme") == "light"
    assert _read_in_new_process(ini, "autosave") == "0"
    assert _read_in_new_process(ini, "undo_steps") == "50"


def test_the_old_lower_case_key_is_the_fallback(tmp_path):
    # A macOS plist keeps «general/…» exactly as written; nobody loses a
    # setting on the way to the new key.
    st = QSettings(str(tmp_path / "x.ini"), QSettings.IniFormat)
    st.setValue("general/backup", "0")
    assert general_settings.value("backup", "1", st) == "0"
    general_settings.set_value("backup", "1", st)
    assert general_settings.value("backup", "0", st) == "1"


def test_a_missing_setting_gives_the_default(tmp_path):
    st = QSettings(str(tmp_path / "y.ini"), QSettings.IniFormat)
    assert general_settings.value("platform", "auto", st) == "auto"
