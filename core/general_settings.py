# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Preferences ▸ General settings, under the one key that survives a
restart on every platform.

Qt's INI format (Linux) reserves the section name «General» for keys with
no group, so a group of that name — in ANY case — is written escaped as
``[%General]``; and a new process reads that section back as
``General/…`` with a capital G. Everything was stored as ``general/…``:
inside one session Qt's in-memory cache answered, and after a restart the
lower-case key found nothing — the theme always came back dark, and a
disabled autosave or backup, the undo depth and the display server choice
quietly returned to their defaults (#266, diagnosed by @parampreetss).

``General/…`` reads what earlier versions saved on Linux (the same
``[%General]`` section). The registry (Windows) ignores case, and a macOS
plist kept ``general/…`` as written, so reading falls back to the old key
there and nobody loses a setting on the way.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings

_GROUP = "General/"
_OLD_GROUP = "general/"


def value(name: str, default=None, settings: QSettings | None = None):
    """The saved General setting ``name``, or ``default``."""
    st = settings if settings is not None else QSettings()
    got = st.value(_GROUP + name)
    if got is None:
        got = st.value(_OLD_GROUP + name)
    return default if got is None else got


def set_value(name: str, val, settings: QSettings | None = None) -> None:
    st = settings if settings is not None else QSettings()
    st.setValue(_GROUP + name, val)
