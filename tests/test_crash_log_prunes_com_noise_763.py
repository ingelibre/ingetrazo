# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The crash log keeps crashes, not handled COM errors (#763).

On Windows faulthandler logs every SEH exception with the error bit set;
UI Automation raises RPC errors (0x8001010d) by the dozen while the app
keeps running, and the «fatal» entries buried the real crash. At start
the log drops the RPC-facility entries and keeps everything else."""
from __future__ import annotations

from core.paths import prune_handled_com_errors

_COM = """Windows fatal exception: code 0x8001010d

Current thread 0x00001a2c (most recent call first):
  File "main.py", line 520 in main
  File "main.py", line 540 in <module>

"""
_CRASH = """Windows fatal exception: access violation

Current thread 0x00001a2c (most recent call first):
  File "views/viewport.py", line 3001 in paintGL

"""
_PY = """Fatal Python error: Segmentation fault

Current thread 0x00007f (most recent call first):
  File "core/mesh.py", line 10 in add_face

"""


def test_handled_com_errors_go_and_the_crashes_stay(tmp_path):
    log = tmp_path / "ingetrazo-crash.log"
    log.write_text(_COM + _CRASH + _COM + _COM + _PY + _COM, encoding="utf-8")
    prune_handled_com_errors(log)
    assert log.read_text(encoding="utf-8") == _CRASH + _PY


def test_a_log_without_com_noise_is_left_alone(tmp_path):
    log = tmp_path / "ingetrazo-crash.log"
    log.write_text(_CRASH + _PY, encoding="utf-8")
    before = log.stat().st_mtime_ns
    prune_handled_com_errors(log)
    assert log.read_text(encoding="utf-8") == _CRASH + _PY
    assert log.stat().st_mtime_ns == before


def test_a_missing_log_is_fine(tmp_path):
    prune_handled_com_errors(tmp_path / "none.log")
