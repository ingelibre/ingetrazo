# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Window ▸ Preferences ▸ Restore defaults: the controls go back to what a
fresh profile gets; OK saves that, Cancel still touches nothing, and the
language, the AI Assistant and the shortcuts stay as they were."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QWidget

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
    path = tmp_path / "prefs.ini"
    monkeypatch.setattr(
        prefs_mod, "QSettings",
        lambda: QSettings(str(path), QSettings.IniFormat))
    return path


class _Win(QWidget):
    def __init__(self):
        super().__init__()

        class _VP:
            edit_rest_mode = "hide"

            def set_edit_rest_mode(self, mode):
                self.edit_rest_mode = mode

        self.viewport = _VP()
        self._rest_actions = {}


def _fresh(path):
    return QSettings(str(path), QSettings.IniFormat)


def _customised(path):
    """A profile someone has tuned: nothing at its default."""
    st = _fresh(path)
    st.setValue("General/autosave", "0")
    st.setValue("General/autosave_min", 30)
    st.setValue("General/backup", "0")
    st.setValue("General/undo_steps", 50)
    st.setValue("General/cursor_style", "arrow")
    st.setValue("General/ext_menus", "flat")
    st.setValue("section/ask_name", "0")
    st.setValue("new_document/scale_figure", "0")
    st.setValue("nav/invert_wheel", "1")
    st.setValue("nav/invert_orbit_y", "1")
    st.setValue("walk/look_sensitivity", 80)
    st.setValue("display/msaa", 0)
    st.setValue("import/obj_unit", "ft")
    st.setValue("import/dxf_unit", "in")
    st.setValue("georef/coord_mode", "utm")
    st.setValue("language", "fr")
    st.setValue("ia/api_key", "test-key-123")
    st.setValue("ia/modelo", "my-model")
    st.sync()


def _restore_button(dlg):
    box = dlg.findChild(QDialogButtonBox)
    return next(b for b in box.buttons()
                if box.buttonRole(b) == QDialogButtonBox.ResetRole)


def test_the_dialog_has_a_restore_defaults_button(settings_file):
    dlg = PreferencesDialog(_Win())
    assert _restore_button(dlg) is dlg._defaults_btn


def test_ok_stays_the_highlighted_button_after_restoring(settings_file, monkeypatch):
    """With the focus on Restore defaults (after its click, or by Tab) it
    took the default-button highlight from OK, and Enter restored again."""
    dlg = PreferencesDialog(_Win())
    dlg.show()
    monkeypatch.setattr(prefs_mod.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.Ok)
    dlg._defaults_btn.setFocus()
    dlg._defaults_btn.click()
    QApplication.processEvents()
    box = dlg.findChild(QDialogButtonBox)
    assert not dlg._defaults_btn.isDefault()
    assert box.button(QDialogButtonBox.Ok).isDefault()
    dlg.reject()


def test_restore_puts_every_control_back_to_its_default(settings_file):
    _customised(settings_file)
    dlg = PreferencesDialog(_Win())
    assert dlg._obj_unit.currentData() == "ft"        # the tuned profile
    assert not dlg._autosave.isChecked()
    dlg.restore_defaults()
    assert dlg._autosave.isChecked()
    assert dlg._autosave_min.value() == 5
    assert dlg._backup.isChecked()
    assert dlg._undo_steps.value() == 200
    assert dlg._ask_section.isChecked()
    assert dlg._scale_figure.isChecked()
    assert not dlg._invert.isChecked()
    assert not dlg._invert_orbit.isChecked()
    assert dlg._look_sens.value() == 25
    assert dlg._cursor_style.currentData() == "tool"
    assert dlg._msaa.currentData() == 4
    assert dlg._ext_menus.currentData() == "auto"
    assert dlg._rest.currentData() == "fade"
    assert dlg._theme.currentData() == "dark"
    assert dlg._accent.currentData() == "orange"
    assert dlg._obj_unit.currentData() == "m"
    assert dlg._dxf_unit.currentData() == "mm"
    assert dlg._coord.currentData() == "geo"
    assert dlg._ndof_on.isChecked()
    assert dlg._ndof_speed.value() == 100
    assert not any(b.isChecked() for b in dlg._ndof_inv.values())


def test_ok_saves_the_defaults_and_keeps_language_and_ai(settings_file):
    _customised(settings_file)
    win = _Win()
    dlg = PreferencesDialog(win)
    dlg.restore_defaults()
    dlg.accept()
    st = _fresh(settings_file)
    assert st.value("General/autosave") == "1"
    assert int(st.value("General/autosave_min")) == 5
    assert int(st.value("General/undo_steps")) == 200
    assert st.value("nav/invert_wheel") == "0"
    assert int(st.value("walk/look_sensitivity")) == 25
    assert st.value("import/obj_unit") == "m"
    assert win.viewport.edit_rest_mode == "fade"
    # Not part of the reset.
    assert st.value("language") == "fr"
    assert st.value("ia/api_key") == "test-key-123"
    assert st.value("ia/modelo") == "my-model"


def test_cancel_after_restore_touches_nothing(settings_file):
    _customised(settings_file)
    win = _Win()
    dlg = PreferencesDialog(win)
    dlg.restore_defaults()
    dlg.reject()
    st = _fresh(settings_file)
    assert st.value("import/obj_unit") == "ft"
    assert st.value("General/autosave") == "0"
    assert win.viewport.edit_rest_mode == "hide"


def test_restore_does_not_copy_the_document_units_to_new_documents(settings_file):
    st = _fresh(settings_file)
    st.setValue("units/use_for_new_documents", "0")
    st.sync()
    dlg = PreferencesDialog(_Win())
    dlg.restore_defaults()
    assert dlg._units_for_new.isChecked()
    assert dlg._units_for_new_explicit is False


def test_the_button_asks_first(settings_file, monkeypatch):
    _customised(settings_file)
    dlg = PreferencesDialog(_Win())
    monkeypatch.setattr(prefs_mod.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.Cancel)
    dlg._defaults_btn.click()
    assert dlg._obj_unit.currentData() == "ft"        # declined: untouched
    monkeypatch.setattr(prefs_mod.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.Ok)
    dlg._defaults_btn.click()
    assert dlg._obj_unit.currentData() == "m"
