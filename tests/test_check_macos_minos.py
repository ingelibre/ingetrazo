# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The minimum-macOS check of the Monterey package (#1123), on ``otool -l``
text: the check itself only runs on a Mac."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / "scripts" / "check_macos_minos.py"
_spec = importlib.util.spec_from_file_location("check_macos_minos", _path)
minos = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(minos)

OTOOL = """\
Load command 8
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform 1
    minos 14.0
      sdk 15.0
Load command 9
      cmd LC_VERSION_MIN_MACOSX
  cmdsize 16
  version 10.13
      sdk 10.15
Load command 10
          cmd LC_UUID
      version 99.0
"""


def test_reads_both_load_commands_and_nothing_else():
    assert minos.minimum_versions(OTOOL) == ["14.0", "10.13"]


def test_versions_compare_as_numbers():
    assert minos.too_new(["14.0", "10.13", "12.0", "12.0.1"], "12.0") == [
        "14.0", "12.0.1"]
    assert minos.too_new(["9.0"], "10.13") == []
