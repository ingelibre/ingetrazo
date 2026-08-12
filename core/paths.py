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
