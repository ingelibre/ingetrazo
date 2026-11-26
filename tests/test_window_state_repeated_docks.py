# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Properties alone at the top of the side tray after a restart.

Restore default toolbars restored the factory layout with the panels
renamed out of its way; Qt kept a place for each panel that layout names,
and the next close saved those places beside the real ones — the same
panel twice. Started again, Properties went to the first: a group of its
own with the closed BIM and Georeference tabs, the other tabs under it,
and no menu entry put it back. Now the toolbar reset leaves the panels
out of it, and a layout saved with a panel twice is read with each panel
once, in its last place (views/window_state.py)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow, QWidget

from views import window_state

_app = QApplication.instance() or QApplication([])


def _settle():
    for _ in range(5):
        _app.processEvents()


# ---- the saved layout itself -------------------------------------------------

def _plain_window(names):
    """A bare window with one tab row of docks ``names``."""
    w = QMainWindow()
    w.setCentralWidget(QWidget())
    docks = []
    for name in names:
        d = QDockWidget(name, w)
        d.setObjectName(name)
        d.setWidget(QWidget())
        w.addDockWidget(Qt.RightDockWidgetArea, d)
        docks.append(d)
    for d in docks[1:]:
        w.tabifyDockWidget(docks[0], d)
    w.resize(900, 600)
    w.show()
    _settle()
    return w, docks


def _ghost_state():
    """A layout saved with every dock twice, made the way the old toolbar
    reset made it: another layout restored while the docks go by other
    names, then the names back."""
    names = ["props", "browser", "layers"]
    first, _ = _plain_window(names)
    other = bytes(first.saveState())
    first.close()
    w, docks = _plain_window(names)
    for d in docks:
        d.setObjectName("_away_" + d.objectName())
    w.restoreState(other)
    for d, name in zip(docks, names):
        d.setObjectName(name)
    state = bytes(w.saveState())
    w.close()
    return state, names


def test_the_old_way_saved_every_dock_twice():
    state, names = _ghost_state()
    assert window_state.repeated_docks(state) == set(names)


def test_each_dock_is_left_once_and_qt_still_reads_it():
    state, names = _ghost_state()
    mended = window_state.without_repeated_docks(state)
    assert mended is not None
    assert window_state.repeated_docks(mended) == set()
    w, docks = _plain_window(names)
    assert w.restoreState(QByteArray(mended))
    _settle()
    assert {d.objectName() for d in w.tabifiedDockWidgets(docks[0])} == \
        set(names[1:])
    w.close()


def test_a_layout_without_repeats_is_left_as_it_is():
    from core.paths import app_root
    factory = (app_root() / "resources" / "ui"
               / "default_layout.state").read_bytes()
    assert window_state.without_repeated_docks(factory) is None
    header, sections = window_state._sections(factory)
    assert window_state._write(header, sections) == factory


@pytest.mark.parametrize("junk", [b"", b"\x00\x00\x00\xff", b"nonsense" * 9,
                                  b"\x00\x00\x00\xff\x00\x00\x00\x00\xfd\x00"])
def test_bytes_it_cannot_read_are_left_to_qt(junk):
    assert window_state.without_repeated_docks(junk) is None
    assert window_state.repeated_docks(junk) == set()
    assert window_state.with_toolbars_of(junk, junk) is None


# ---- the window --------------------------------------------------------------

@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "prefs.ini"
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    import PySide6.QtCore as qc
    import views.main_window as mw
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory)
    return path


def _open():
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1280, 800)
    w.show()
    _settle()
    return w


def _close(w):
    """What closing saves, without the questions."""
    w._dock_panels_for_saving()
    w._save_window_settings()
    w._saved_version = w.viewport.scene.version
    w.close()
    _settle()


def _saved_state():
    from views import main_window as mw
    return bytes(mw.QSettings().value("ui/window_state"))


def _properties_among_the_tabs(w):
    return w.project_browser in w.tabifiedDockWidgets(w.tray)


def test_toolbar_reset_with_the_tray_folded_keeps_properties_in_its_tabs(
        settings_file):
    w = _open()
    w._set_sidebar_visible(False)
    _settle()
    w.restore_default_toolbars()
    _settle()
    w._set_sidebar_visible(True)
    _settle()
    _close(w)
    assert window_state.repeated_docks(_saved_state()) == set()
    again = _open()
    try:
        assert _properties_among_the_tabs(again)
    finally:
        _close(again)


def test_a_layout_already_saved_twice_heals_on_the_next_start(settings_file):
    # What the old reset left behind, made here by hand: the factory
    # layout restored with the panels renamed, the sidebar folded.
    from core.paths import app_root
    w = _open()
    w._set_sidebar_visible(False)
    _settle()
    docks = {d: d.objectName() for d in w.findChildren(QDockWidget)}
    for d in docks:
        d.setObjectName("_away_" + d.objectName())
    w.restoreState(QByteArray((app_root() / "resources" / "ui"
                               / "default_layout.state").read_bytes()))
    for d, name in docks.items():
        d.setObjectName(name)
    w._set_sidebar_visible(True)
    _settle()
    # Saved as Qt saves it.
    from views import main_window as mw
    raw = QMainWindow.saveState(w)
    w._saved_version = w.viewport.scene.version
    w.close()
    _settle()
    assert "tray_properties" in window_state.repeated_docks(bytes(raw))
    mw.QSettings().setValue("ui/window_state", raw)
    again = _open()
    try:
        assert _properties_among_the_tabs(again)
        assert not again.tray.isHidden()
    finally:
        _close(again)
    assert window_state.repeated_docks(_saved_state()) == set()
