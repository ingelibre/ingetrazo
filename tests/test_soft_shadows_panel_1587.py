# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Soft sun shadows in the Shadows dropdown (#1587): right under «Show
shadows», the same switch as Preferences ▸ General (which keeps its own),
both reading and writing the one setting of this computer — never the
document."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QWidget

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.scene import Scene  # noqa: E402
from views.preferences_dialog import PreferencesDialog  # noqa: E402
from views.tray import ShadowsPanel  # noqa: E402
from views.viewport._support import (set_soft_shadows,  # noqa: E402
                                     soft_shadow_level)


@pytest.fixture(autouse=True)
def clean_settings():
    """The suite's own throwaway QSettings (conftest), emptied of the two
    keys before and after each test."""
    def wipe():
        st = QSettings()
        st.remove("display/soft_shadows")
        st.remove("display/soft_shadows_level")
        st.sync()
    wipe()
    yield
    wipe()


class _VP:
    edit_rest_mode = "fade"
    _msaa = 4
    _soft_shadows = 0

    def __init__(self):
        self.scene = Scene()
        self.updates = 0

    def set_edit_rest_mode(self, mode):
        self.edit_rest_mode = mode

    def update(self):
        self.updates += 1


class _Win(QWidget):
    def __init__(self):
        super().__init__()
        self.viewport = _VP()
        self.back = _VP()                   # a project in another tab
        self._rest_actions = {}
        self.shadows_panel = ShadowsPanel(self)

    def all_viewports(self):
        return [self.viewport, self.back]


def _saved():
    st = QSettings()
    return (int(st.value("display/soft_shadows", 0)),
            int(st.value("display/soft_shadows_level", 2)))


def test_the_switch_sits_right_under_show_shadows():
    panel = _Win().shadows_panel
    grid = panel.layout()
    show = grid.itemAtPosition(0, 0).widget()
    assert show is panel._enable
    row = grid.itemAtPosition(1, 0).layout()
    widgets = [row.itemAt(i).widget() for i in range(row.count())]
    assert panel._soft in widgets and panel._soft_level in widgets
    assert isinstance(panel._soft, QCheckBox)
    assert isinstance(panel._soft_level, QComboBox)


def test_off_by_default_with_its_level_greyed():
    panel = _Win().shadows_panel
    assert not panel._soft.isChecked()
    assert not panel._soft_level.isEnabled()
    assert panel._soft_level.currentData() == 2


def test_ticking_it_reaches_every_view_at_once_and_not_the_document():
    win = _Win()
    panel = win.shadows_panel
    versions = (win.viewport.scene.version, win.back.scene.version)
    panel._soft.setChecked(True)
    assert panel._soft_level.isEnabled()
    assert _saved() == (2, 2)
    for vp in (win.viewport, win.back):
        assert vp._soft_shadows == 2
        assert vp.updates == 1
    panel._soft_level.setCurrentIndex(panel._soft_level.findData(3))
    assert _saved() == (3, 3)
    assert win.viewport._soft_shadows == 3 and win.back._soft_shadows == 3
    # A view setting, not a sun setting: the .igz stays unchanged.
    assert (win.viewport.scene.version, win.back.scene.version) == versions


def test_turned_off_the_level_is_kept_for_next_time():
    win = _Win()
    panel = win.shadows_panel
    panel._soft.setChecked(True)
    panel._soft_level.setCurrentIndex(panel._soft_level.findData(1))
    panel._soft.setChecked(False)
    assert _saved() == (0, 1)
    assert win.viewport._soft_shadows == 0
    assert not panel._soft_level.isEnabled()
    # A level picked while off is remembered, and the views stay crisp.
    panel._soft_level.setCurrentIndex(panel._soft_level.findData(3))
    assert _saved() == (0, 3)
    assert win.viewport._soft_shadows == 0
    assert _Win().shadows_panel._soft_level.currentData() == 3


def test_the_dropdown_shows_what_preferences_saved():
    win = _Win()
    dlg = PreferencesDialog(win)
    assert dlg._soft_shadows is not None          # Preferences keeps it
    dlg._soft_shadows.setChecked(True)
    dlg._soft_level.setCurrentIndex(dlg._soft_level.findData(1))
    dlg.accept()
    panel = win.shadows_panel
    assert panel._soft.isChecked()                 # refreshed on OK
    assert panel._soft_level.currentData() == 1
    assert win.viewport._soft_shadows == 1


def test_preferences_shows_what_the_dropdown_set():
    win = _Win()
    win.shadows_panel._soft.setChecked(True)
    win.shadows_panel._soft_level.setCurrentIndex(
        win.shadows_panel._soft_level.findData(3))
    dlg = PreferencesDialog(win)
    assert dlg._soft_shadows.isChecked()
    assert dlg._soft_level.currentData() == 3


def test_reopening_the_dropdown_rereads_the_setting():
    panel = _Win().shadows_panel
    st = QSettings()
    st.setValue("display/soft_shadows", 2)
    st.sync()
    panel.refresh()                     # what showEvent does
    assert panel._soft.isChecked()
    assert panel._soft_level.currentData() == 2


def test_refreshing_writes_nothing_back():
    win = _Win()
    st = QSettings()
    st.setValue("display/soft_shadows", 3)
    st.sync()
    win.viewport._soft_shadows = 0          # not yet pushed to this view
    win.shadows_panel.refresh()
    assert win.viewport.updates == 0
    assert win.viewport._soft_shadows == 0


@pytest.mark.parametrize("on, level, stored", [
    (None, None, 2), ("3", None, 3), ("0", "1", 1), ("0", "9", 2),
    ("x", "y", 2)])
def test_the_level_to_come_back_at(on, level, stored):
    st = QSettings()
    if on is not None:
        st.setValue("display/soft_shadows", on)
    if level is not None:
        st.setValue("display/soft_shadows_level", level)
    st.sync()
    assert soft_shadow_level() == stored


def test_a_nonsense_level_falls_back_to_moderate():
    vp = _VP()
    assert set_soft_shadows([vp], True, 7) == 2
    assert vp._soft_shadows == 2
    assert _saved() == (2, 2)
