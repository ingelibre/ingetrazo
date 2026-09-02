# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""One full QApplication for the whole test session, created BEFORE any test
module imports. Test files that need widgets (MainWindow, the tray) and
files that only need fonts used to create their own app at import time —
a QGuiApplication first meant every later widget test aborted, so the
outcome depended on which files were on the command line."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])
