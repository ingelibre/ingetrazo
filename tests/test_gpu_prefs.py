# SPDX-License-Identifier: GPL-3.0-or-later
"""Hybrid laptops: IngeTrazo claims the discrete GPU through the same
registry value the Windows Graphics settings page writes."""
from __future__ import annotations

from pathlib import Path

from core.gpu_prefs import GPU_PREFS_KEY, HIGH_PERFORMANCE, ensure_high_performance_gpu


class _FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ, KEY_WRITE, REG_SZ = 1, 2, "REG_SZ"

    def __init__(self, values=None, refuse=False):
        self.values = dict(values or {})
        self.refuse = refuse
        self.closed = 0

    def CreateKeyEx(self, root, sub, reserved, access):
        if self.refuse:
            raise PermissionError("registry locked down")
        assert (root, sub) == ("HKCU", GPU_PREFS_KEY)
        return "key"

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, data):
        self.values[name] = data

    def CloseKey(self, key):
        self.closed += 1


EXE = Path(r"C:\Program Files\IngeTrazo\ingetrazo.exe")


def test_first_run_claims_the_high_performance_gpu():
    reg = _FakeWinreg()
    assert ensure_high_performance_gpu(EXE, winreg=reg, platform="win32") == "set"
    assert reg.values == {str(EXE): HIGH_PERFORMANCE}
    assert reg.closed == 1


def test_a_choice_the_user_already_made_is_respected():
    reg = _FakeWinreg({str(EXE): "GpuPreference=1;"})       # power saving, on purpose
    assert ensure_high_performance_gpu(EXE, winreg=reg, platform="win32") == "kept"
    assert reg.values[str(EXE)] == "GpuPreference=1;"


def test_other_platforms_and_source_checkouts_do_nothing():
    reg = _FakeWinreg()
    assert ensure_high_performance_gpu(EXE, winreg=reg, platform="linux") == "skipped"
    assert ensure_high_performance_gpu(None, winreg=reg, platform="win32") == "skipped"
    assert reg.values == {}


def test_a_locked_registry_never_stops_start_up():
    assert ensure_high_performance_gpu(EXE, winreg=_FakeWinreg(refuse=True),
                                       platform="win32") == "failed"
