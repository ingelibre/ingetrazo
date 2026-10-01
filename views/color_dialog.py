# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The colour picker every panel opens: Qt's own dialog, not the desktop's.

On GNOME the native picker is GTK's small palette, and opened from a
right-click menu it came back without the colour chosen — editing a
material's colour did nothing (Marco, testing 0.5.7). Qt's dialog is the
same on Linux, Windows and macOS: a colour wheel, RGB, HSV, a hex field
and custom colours."""
from __future__ import annotations

from PySide6.QtWidgets import QColorDialog


def get_color(*args, **kwargs):
    """``QColorDialog.getColor`` with Qt's own dialog."""
    kwargs.setdefault("options",
                      QColorDialog.ColorDialogOption.DontUseNativeDialog)
    return QColorDialog.getColor(*args, **kwargs)
