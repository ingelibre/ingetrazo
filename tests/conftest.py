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

# Windows: the offscreen platform has NO font database there (fontconfig
# finds the fonts on Linux; on Windows nothing looks), so every glyph drew
# as an empty box — 3D text lost the O's counter and built faces for
# spaces, and every test that measures a label's width measured boxes.
# Pointed at the system fonts, and with the faces the app gets from the
# native platform (Segoe UI 9 pt; the "Sans" alias the tests and the
# Linux defaults name resolves to a sans-serif, not the alphabetically
# first family), the suite sees the text a Windows user sees.
_WIN_OFFSCREEN = (sys.platform == "win32"
                  and os.environ["QT_QPA_PLATFORM"] == "offscreen")
if _WIN_OFFSCREEN:
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(
        os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

if _WIN_OFFSCREEN:
    from PySide6.QtGui import QFont  # noqa: E402
    for _alias in ("Sans", "Sans Serif", "DejaVu Sans"):
        QFont.insertSubstitutions(_alias, ["Segoe UI", "Arial"])
    QApplication.setFont(QFont("Segoe UI", 9))

# And a QSettings store of its own, thrown away with the session. The suite
# is not read-only about preferences: a test that exercises «new items
# inherit the last style» writes that style out, so it landed in the
# developer's real settings and POISONED ITS OWN NEXT RUN — the cota style
# test placed a cota with text_pos="below" and then failed the next day
# asserting "above". Isolating the store makes every run start from the
# same place, here and on the CI runner.
import tempfile  # noqa: E402

from PySide6.QtCore import QSettings  # noqa: E402

_settings_dir = tempfile.mkdtemp(prefix="ingetrazo-tests-settings-")
QSettings.setDefaultFormat(QSettings.IniFormat)
for scope in (QSettings.UserScope, QSettings.SystemScope):
    QSettings.setPath(QSettings.IniFormat, scope, _settings_dir)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _world_drawing_axes():
    """The drawing axes are process-wide (core.axes, issue #44): a test that
    leaves a turned group open must not tilt the next one's inferences."""
    from core import axes
    axes.sync(None)
    yield
    axes.sync(None)


def pytest_sessionfinish(session, exitstatus):
    """Leave no Python-owned clipboard entry (``formats.clip.ClipMime``) in
    Qt's clipboard while the interpreter tears down — a Copy in a test puts
    one there, and the CI run of 9393ef5 passed and then segfaulted on exit."""
    try:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is not None:
            from formats import clip
            clip.flush()
            QApplication.clipboard().clear()
    except Exception:  # noqa: BLE001 - teardown must not fail the run
        pass


@pytest.fixture(autouse=True, scope="session")
def _no_stray_autosave():
    """Every MainWindow a test builds armed the 5-minute auto-save timer,
    and the windows outlive their tests. Once the session ran past five
    minutes those timers fired inside later tests, and the tick's
    gc.collect() over half-torn-down Qt objects stalled or crashed the run
    (24-09: runs stuck at ~95 %, the faulthandler dump caught it in
    ``_on_autosave_tick``). The timer is still built and armed — the
    Preferences test reads its settings — then stopped at once; tests that
    exercise the tick call it directly."""
    from views.main_window import MainWindow
    original = MainWindow._setup_autosave

    def armed_but_stopped(self):
        original(self)
        self._autosave_timer.stop()

    MainWindow._setup_autosave = armed_but_stopped
    yield
    MainWindow._setup_autosave = original
