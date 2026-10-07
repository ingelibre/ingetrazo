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


@pytest.fixture(autouse=True, scope="session")
def _isolated_application_data(tmp_path_factory):
    """Keep autosaves, tile caches and texture caches out of real user data.

    QSettings isolation alone does not cover QStandardPaths. A non-writable
    user cache made retinting silently fall back to a new folder on every call.
    """
    from PySide6.QtCore import QStandardPaths

    root = tmp_path_factory.mktemp("application-data")
    original = QStandardPaths.writableLocation
    locations = {
        QStandardPaths.AppDataLocation, QStandardPaths.AppLocalDataLocation,
        QStandardPaths.GenericDataLocation, QStandardPaths.CacheLocation,
        QStandardPaths.GenericCacheLocation,
    }

    def writable_location(location):
        if location in locations:
            path = root / str(location.value)
            path.mkdir(exist_ok=True)
            return str(path)
        return original(location)

    QStandardPaths.writableLocation = staticmethod(writable_location)
    try:
        yield
    finally:
        QStandardPaths.writableLocation = staticmethod(original)


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
