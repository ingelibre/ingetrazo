# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Crash guard for extension ``setup()`` calls (issue #306).

A segfault inside an extension's ``setup(app)`` cannot be caught with
``try`` — on one machine a bundled extension took the whole app down on
*every* launch, until the user deleted the file by hand. So the loader
leaves a marker naming the extension it is about to set up, and removes
it when the call returns. A marker still there at the next start means
the previous launch died inside that extension: its stem goes on the
crash-disabled list (kept next to the crash log, in the state
directory) and the extension is skipped — and reported — until it is
re-enabled (:func:`reenable`, what an Extensions-manager action calls).
Core and community extensions alike: the marker is armed around every
``setup()`` the loader runs.
"""
from __future__ import annotations

import json
from pathlib import Path

_MARKER = "extension-setup.marker"
_DISABLED = "extension-crash-disabled.json"


def _marker_path() -> Path:
    from core.paths import user_log_dir
    return user_log_dir() / _MARKER


def _disabled_path() -> Path:
    from core.paths import user_log_dir
    return user_log_dir() / _DISABLED


def arm(stem: str) -> None:
    """Name ``stem`` as the extension being set up, before the call."""
    try:
        _marker_path().write_text(stem, encoding="utf-8")
    except OSError:
        pass


def disarm() -> None:
    """The setup call returned: no extension is in flight any more."""
    try:
        _marker_path().unlink(missing_ok=True)
    except OSError:
        pass


def crash_disabled() -> list[str]:
    """The stems disabled after a crash, in the order they were caught."""
    try:
        data = json.loads(_disabled_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [s for s in data if isinstance(s, str)]


def _save_disabled(stems: list[str]) -> None:
    try:
        _disabled_path().write_text(json.dumps(stems), encoding="utf-8")
    except OSError:
        pass


def note_crash() -> str | None:
    """Fold a leftover marker into the crash-disabled list.

    Called once at startup, before any ``setup()`` runs: returns the
    stem the previous launch died in (now disabled), or ``None`` when
    the last launch got through every setup."""
    try:
        stem = _marker_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    disarm()
    if not stem:
        return None
    stems = crash_disabled()
    if stem not in stems:
        _save_disabled([*stems, stem])
    return stem


def reenable(stem: str) -> None:
    """Take ``stem`` off the crash-disabled list: the next launch runs
    its ``setup()`` again."""
    _save_disabled([s for s in crash_disabled() if s != stem])
