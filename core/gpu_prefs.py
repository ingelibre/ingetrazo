# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Ask Windows for the discrete GPU on hybrid laptops.

A laptop with an Intel iGPU and an NVIDIA/AMD dGPU starts every unknown
program on the Intel chip; IngeTrazo then orbits at a crawl while the RTX
sits idle. Windows keeps the per-program choice the user makes in
Settings ▸ System ▸ Display ▸ Graphics as a string value under
``HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences`` (name: the
executable's full path, data: ``GpuPreference=2;`` for high performance).
Writing that value ourselves is exactly what the Settings page does, needs
no elevation, and the user can still change it there afterwards — we only
fill it in when no choice was made yet."""
from __future__ import annotations

import sys
from pathlib import Path

GPU_PREFS_KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
HIGH_PERFORMANCE = "GpuPreference=2;"


def app_executable() -> Path | None:
    """The packaged ``ingetrazo.exe``; None when running from a checkout
    (tagging the venv's python.exe would leak into every script)."""
    if getattr(sys, "frozen", False) and sys.executable:
        return Path(sys.executable)
    return None


def ensure_high_performance_gpu(exe: Path | None = None, *,
                                winreg=None, platform: str | None = None) -> str:
    """Register the high-performance preference for ``exe`` unless the user
    already chose one. Returns ``"set"``, ``"kept"`` (a value existed),
    ``"skipped"`` (not Windows / not packaged) or ``"failed"`` (registry
    refused). Never raises: this runs before the window exists."""
    platform = platform or sys.platform
    if not platform.startswith("win"):
        return "skipped"
    exe = exe or app_executable()
    if exe is None:
        return "skipped"
    if winreg is None:
        try:
            import winreg  # type: ignore[import-not-found]
        except ImportError:
            return "failed"
    name = str(exe)
    try:
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, GPU_PREFS_KEY, 0,
                                 winreg.KEY_READ | winreg.KEY_WRITE)
    except OSError:
        return "failed"
    try:
        try:
            winreg.QueryValueEx(key, name)
            return "kept"
        except FileNotFoundError:
            pass
        except OSError:
            return "failed"
        try:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, HIGH_PERFORMANCE)
            return "set"
        except OSError:
            return "failed"
    finally:
        try:
            winreg.CloseKey(key)
        except Exception:
            pass
