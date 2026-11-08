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
            edit_rest_fade = 0.75

            def set_edit_rest_mode(self, mode):
                self.edit_rest_mode = mode

            def set_edit_rest_fade(self, strength):
                self.edit_rest_fade = strength

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
    dlg._invert_orbit.setChecked(True)
    dlg._look_sens.setValue(40)
    dlg._msaa.setCurrentIndex(dlg._msaa.findData(8))
    dlg.accept()
    st = _fresh(settings_file)
    assert st.value("import/obj_unit") == "cm"
    assert st.value("import/dxf_unit") == "m"
    assert st.value("georef/coord_mode") == "utm"
    assert st.value("ia/modelo") == "llama-3.3-70b"
    assert st.value("ia/capturas") == "0"
    assert st.value("General/autosave") == "1"
    assert int(st.value("General/autosave_min")) == 10
    assert st.value("General/backup") == "0"
    assert st.value("nav/invert_wheel") == "1"
    assert st.value("nav/invert_orbit_y") == "1"
    assert int(st.value("walk/look_sensitivity")) == 40
    assert int(st.value("display/msaa")) == 8
    # The live pieces reach the viewport immediately.
    assert win.viewport._invert_wheel is True
    assert win.viewport._invert_orbit_y is True
    assert win.viewport._msaa == 8
    assert win.viewport._fbo_size is None   # next paint rebuilds the FBO


def test_cancel_touches_nothing(settings_file):
    win = _Win()
    dlg = PreferencesDialog(win)
    dlg._obj_unit.setCurrentIndex(dlg._obj_unit.findData("ft"))
    dlg._rest_fade.setValue(21)
    dlg.reject()
    st = _fresh(settings_file)
    assert st.value("import/obj_unit") is None      # never written
    assert win.viewport.edit_rest_mode == "fade"
    assert win.viewport.edit_rest_fade == 0.75


def test_rest_mode_applies_through_the_viewport(settings_file):
    win = _Win()
    dlg = PreferencesDialog(win)
    assert dlg._rest.currentData() == "fade"        # mirrors the viewport
    assert dlg._rest_fade.value() == 75
    dlg._rest_fade.setValue(42)
    dlg._rest.setCurrentIndex(dlg._rest.findData("hide"))
    assert not dlg._rest_fade.isEnabled()
    dlg.accept()
    assert win.viewport.edit_rest_mode == "hide"
    assert win.viewport.edit_rest_fade == 0.42


def test_dialog_reloads_saved_values(settings_file):
    st = _fresh(settings_file)
    st.setValue("import/dxf_unit", "in")
    st.setValue("ia/proveedor", "auto")
    st.sync()
    win = _Win()                 # referenced: see the theme test below
    dlg = PreferencesDialog(win)
    assert dlg._dxf_unit.currentData() == "in"
    assert dlg._provider.currentData() == "auto"


def test_toolbar_icon_size_lives_in_preferences_and_reaches_every_toolbar(settings_file):
    """Marco, 2026-09-14: the icon size belongs in Preferences, and it must
    size the sheet composer's toolbars too. One setting (ui/toolbar_icon_px),
    the old «large icons» toggle migrated, applied live through the window."""
    import views.icons as icons_mod
    from views.icons import save_toolbar_icon_px, toolbar_icon_px

    # the dialog and the helper read the same throwaway settings file
    st_factory = prefs_mod.QSettings
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(icons_mod, "QSettings", st_factory, raising=False)
    try:
        # migration: the retired toggle reads as 32 px until a size is saved
        st = _fresh(settings_file)
        st.setValue("ui/large_toolbar_icons", "1")
        st.sync()
        import PySide6.QtCore as qc
        monkeypatch.setattr(qc, "QSettings", st_factory)
        assert toolbar_icon_px() == 32

        win = _Win()
        seen = []
        win.set_toolbar_icon_size = lambda px: (seen.append(px), save_toolbar_icon_px(px))
        dlg = PreferencesDialog(win)
        assert dlg._icon_px.currentData() == 32
        dlg._icon_px.setCurrentIndex(dlg._icon_px.findData(40))
        dlg.accept()
        assert seen == [40]
        st = _fresh(settings_file)
        assert int(st.value("ui/toolbar_icon_px")) == 40
        assert st.value("ui/large_toolbar_icons") is None     # migrated away
        assert toolbar_icon_px() == 40
    finally:
        monkeypatch.undo()


def test_theme_choice_applies_at_once(settings_file):
    from views import theme
    app = QApplication.instance()
    before = theme.saved_theme()
    try:
        # Keep the parent referenced: a bare ``_Win()`` is collected at
        # once and takes the dialog (its child, tabs and all) with it —
        # the use-after-free behind the suite's exit segfault.
        win = _Win()
        dlg = PreferencesDialog(win)
        dlg._theme.setCurrentIndex(dlg._theme.findData(theme.LIGHT))
        dlg.accept()
        assert theme.saved_theme() == theme.LIGHT
        assert app.palette().window().color().lightness() > 128
    finally:
        theme.save_theme(before)
        theme.apply_theme(app, theme.DARK)


def test_the_3d_mouse_page_shows_the_device_live(settings_file, monkeypatch):
    """Nobody on the team has a SpaceMouse: the page shows the six numbers
    as the device sends them and how IngeTrazo reads them, so an owner can
    report a wrong sign by looking (#108)."""
    from core.ndof import NdofSample
    from views import ndof_input

    dev = ndof_input.NdofInput()
    monkeypatch.setattr(ndof_input, "_shared", dev)
    monkeypatch.setattr(type(dev), "backend_name",
                        property(lambda self: "rawinput"))
    dlg = PreferencesDialog(_Win())
    dev.raw.emit((12, -340, 0, 0, 0, 7))
    dev.motion.emit(NdofSample(forward=0.97), 0.01)
    assert "Y  -340" in dlg._ndof_raw.text()
    assert "RZ    +7" in dlg._ndof_raw.text()
    assert "+0.97" in dlg._ndof_read.text()
    dlg.reject()
    dev.raw.emit((0, 0, 0, 0, 0, 0))             # closed: no longer listens
    assert "Y  -340" in dlg._ndof_raw.text()


def test_the_tool_cursor_is_chosen_in_preferences(settings_file):
    """#858: the crosshair or the plain arrow instead of the tool's icon is a
    choice in Preferences ▸ General, saved where ``tool_cursor`` reads it and
    applied to the active tool at once; the tool's icon stays the default."""
    win = _Win()
    applied = []
    win.viewport._apply_tool_cursor = lambda: applied.append(True)
    dlg = PreferencesDialog(win)
    assert dlg._cursor_style.currentData() == "tool"
    dlg._cursor_style.setCurrentIndex(dlg._cursor_style.findData("crosshair"))
    dlg.accept()
    assert _fresh(settings_file).value("General/cursor_style") == "crosshair"
    assert applied == [True]
    assert PreferencesDialog(win)._cursor_style.currentData() == "crosshair"
