# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Window ▸ Preferences: the scattered QSettings gathered in one dialog.

OK writes and flushes; Cancel touches nothing; the rest-of-model mode goes
through the viewport (the same live path the Camera menu uses).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

import views.preferences_dialog as prefs_mod  # noqa: E402
from views.preferences_dialog import PreferencesDialog  # noqa: E402


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Point the dialog's QSettings at a throwaway INI file."""
    path = tmp_path / "prefs.ini"
    monkeypatch.setattr(
        prefs_mod, "QSettings",
        lambda: QSettings(str(path), QSettings.IniFormat))
    return path


class _Win(QWidget):
    """Just enough main window: a viewport with the rest-mode contract."""

    def __init__(self):
        super().__init__()

        class _VP:
            edit_rest_mode = "fade"

            def set_edit_rest_mode(self, mode):
                self.edit_rest_mode = mode

        self.viewport = _VP()
        self._rest_actions = {}


def _fresh(path):
    return QSettings(str(path), QSettings.IniFormat)


def test_ok_writes_the_settings(settings_file):
    win = _Win()
    dlg = PreferencesDialog(win)
    dlg._obj_unit.setCurrentIndex(dlg._obj_unit.findData("cm"))
    dlg._dxf_unit.setCurrentIndex(dlg._dxf_unit.findData("m"))
    dlg._coord.setCurrentIndex(dlg._coord.findData("utm"))
    dlg._model.setText("llama-3.3-70b")
    dlg._shots.setChecked(False)
    dlg._autosave_min.setValue(10)
    dlg._backup.setChecked(False)
    dlg._invert.setChecked(True)
    dlg._msaa.setCurrentIndex(dlg._msaa.findData(8))
    dlg.accept()
    st = _fresh(settings_file)
    assert st.value("import/obj_unit") == "cm"
    assert st.value("import/dxf_unit") == "m"
    assert st.value("georef/coord_mode") == "utm"
    assert st.value("ia/modelo") == "llama-3.3-70b"
    assert st.value("ia/capturas") == "0"
    assert st.value("general/autosave") == "1"
    assert int(st.value("general/autosave_min")) == 10
    assert st.value("general/backup") == "0"
    assert st.value("nav/invert_wheel") == "1"
    assert int(st.value("display/msaa")) == 8
    # The live pieces reach the viewport immediately.
    assert win.viewport._invert_wheel is True
    assert win.viewport._msaa == 8
    assert win.viewport._fbo_size is None   # next paint rebuilds the FBO


def test_cancel_touches_nothing(settings_file):
    win = _Win()
    dlg = PreferencesDialog(win)
    dlg._obj_unit.setCurrentIndex(dlg._obj_unit.findData("ft"))
    dlg.reject()
    st = _fresh(settings_file)
    assert st.value("import/obj_unit") is None      # never written
    assert win.viewport.edit_rest_mode == "fade"


def test_rest_mode_applies_through_the_viewport(settings_file):
    win = _Win()
    dlg = PreferencesDialog(win)
    assert dlg._rest.currentData() == "fade"        # mirrors the viewport
    dlg._rest.setCurrentIndex(dlg._rest.findData("hide"))
    dlg.accept()
    assert win.viewport.edit_rest_mode == "hide"


def test_dialog_reloads_saved_values(settings_file):
    st = _fresh(settings_file)
    st.setValue("import/dxf_unit", "in")
    st.setValue("ia/proveedor", "auto")
    st.sync()
    dlg = PreferencesDialog(_Win())
    assert dlg._dxf_unit.currentData() == "in"
    assert dlg._provider.currentData() == "auto"
