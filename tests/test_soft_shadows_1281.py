# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Soft sun shadows (#1281): Preferences ▸ General turns them on, at a
level, off by default since they cost the graphics card more while the sun
casts shadows. The penumbra widens with the distance from what casts it
(percentage-closer soft shadows), its width worked out in the world so the
whole-model map, the detail map of a settled view (#958) and an export's
bigger map soften alike."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QVector2D, QVector3D as V
from PySide6.QtWidgets import QApplication, QWidget

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

import views.preferences_dialog as prefs_mod  # noqa: E402
from views.preferences_dialog import PreferencesDialog  # noqa: E402
from views.viewport import (SOFT_SHADOW_SPREAD, Viewport,  # noqa: E402
                            _load_soft_shadows)

FRAG = (Path(__file__).resolve().parent.parent
        / "resources" / "shaders" / "basic.frag")


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "prefs.ini"
    monkeypatch.setattr(
        prefs_mod, "QSettings",
        lambda: QSettings(str(path), QSettings.IniFormat))
    return path


class _VP:
    edit_rest_mode = "fade"
    _msaa = 4                               # as the dialog leaves it
    _soft_shadows = 0

    def __init__(self):
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

    def all_viewports(self):
        return [self.viewport, self.back]


def _fresh(path):
    return QSettings(str(path), QSettings.IniFormat)


def test_off_by_default_with_its_level_greyed(settings_file):
    dlg = PreferencesDialog(_Win())
    assert not dlg._soft_shadows.isChecked()
    assert not dlg._soft_level.isEnabled()
    assert dlg._soft_level.currentData() == 2
    dlg._soft_shadows.setChecked(True)
    assert dlg._soft_level.isEnabled()


def test_ok_saves_the_level_and_every_view_redraws_at_once(settings_file):
    win = _Win()
    dlg = PreferencesDialog(win)
    dlg._soft_shadows.setChecked(True)
    dlg._soft_level.setCurrentIndex(dlg._soft_level.findData(3))
    dlg.accept()
    st = _fresh(settings_file)
    assert int(st.value("display/soft_shadows")) == 3
    for vp in (win.viewport, win.back):
        assert vp._soft_shadows == 3
        assert vp.updates == 1


def test_turned_off_the_level_is_kept_for_next_time(settings_file):
    st = _fresh(settings_file)
    st.setValue("display/soft_shadows", 1)
    st.setValue("display/soft_shadows_level", 1)
    st.sync()
    win = _Win()
    dlg = PreferencesDialog(win)
    assert dlg._soft_shadows.isChecked()
    assert dlg._soft_level.currentData() == 1
    dlg._soft_shadows.setChecked(False)
    dlg.accept()
    st = _fresh(settings_file)
    assert int(st.value("display/soft_shadows")) == 0
    assert int(st.value("display/soft_shadows_level")) == 1
    assert win.viewport._soft_shadows == 0
    dlg = PreferencesDialog(_Win())
    assert not dlg._soft_shadows.isChecked()
    assert dlg._soft_level.currentData() == 1


def test_restore_defaults_turns_them_off(settings_file):
    st = _fresh(settings_file)
    st.setValue("display/soft_shadows", 3)
    st.sync()
    dlg = PreferencesDialog(_Win())
    assert dlg._soft_shadows.isChecked()
    dlg.restore_defaults()
    assert not dlg._soft_shadows.isChecked()
    assert dlg._soft_level.currentData() == 2


@pytest.mark.parametrize("stored, level", [
    (None, 0), ("0", 0), ("2", 2), ("3", 3), ("7", 0), ("lots", 0)])
def test_the_viewport_reads_the_level_and_ignores_nonsense(
        tmp_path, monkeypatch, stored, level):
    import PySide6.QtCore as qtcore
    path = tmp_path / "prefs.ini"
    st = QSettings(str(path), QSettings.IniFormat)
    if stored is not None:
        st.setValue("display/soft_shadows", stored)
    st.sync()
    monkeypatch.setattr(qtcore, "QSettings",
                        lambda: QSettings(str(path), QSettings.IniFormat))
    assert _load_soft_shadows() == level


def test_the_footprint_of_the_map_comes_off_the_light_matrix():
    """The shader turns world widths into map coordinates with it: metres
    across a side and along the depth range, for the whole-model map and
    for a detail map of a settled view (#958) alike."""
    lo, hi = V(-3, -2, 0), V(5, 7, 4)
    d = (0.3, 0.5, 0.8)
    n = sum(c * c for c in d) ** 0.5
    d = tuple(c / n for c in d)
    _view, r = Viewport._light_view(d, lo, hi)
    across, along = Viewport._shadow_footprint(Viewport._light_vp(d, lo, hi))
    assert across == pytest.approx(2.0 * r, rel=1e-5)
    assert along == pytest.approx(3.0 * r, rel=1e-5)
    across, along = Viewport._shadow_footprint(
        Viewport._light_vp(d, lo, hi, (0.5, -0.2, 1.25)))
    assert across == pytest.approx(2.5, rel=1e-5)
    assert along == pytest.approx(3.0 * r, rel=1e-5)


class _Program:
    def __init__(self):
        self.set = {}

    def setUniformValue1f(self, loc, value):
        self.set[loc] = value

    def setUniformValue(self, loc, value):
        self.set[loc] = value


class _Stand:
    """Only what the uniforms read."""
    _loc_shadow_soft = "soft"
    _loc_shadow_world = "world"
    _shadow_footprint = staticmethod(Viewport._shadow_footprint)

    def __init__(self, level):
        self._soft_shadows = level
        self._program = _Program()
        self._shadow_vp = Viewport._light_vp(
            (0.0, 0.0, 1.0), V(0, 0, 0), V(10, 10, 3))


def test_off_sends_zero_and_the_shader_keeps_the_crisp_map():
    stand = _Stand(0)
    Viewport._set_soft_shadow_uniforms(stand)
    assert stand._program.set == {"soft": 0.0}


@pytest.mark.parametrize("level", sorted(SOFT_SHADOW_SPREAD))
def test_a_level_sends_its_spread_and_the_footprint(level):
    stand = _Stand(level)
    Viewport._set_soft_shadow_uniforms(stand)
    assert stand._program.set["soft"] == SOFT_SHADOW_SPREAD[level]
    world = stand._program.set["world"]
    assert isinstance(world, QVector2D)
    assert world.x() > 0.0 and world.y() > 0.0


def test_the_levels_grow():
    spreads = [SOFT_SHADOW_SPREAD[k] for k in sorted(SOFT_SHADOW_SPREAD)]
    assert spreads == sorted(spreads) and len(set(spreads)) == 3


def test_the_shader_branches_on_the_spread():
    """Off, the fragment shader runs the 3x3 PCF it always ran: the soft
    path is behind ``u_shadow_soft > 0``."""
    src = FRAG.read_text(encoding="utf-8")
    assert "uniform float u_shadow_soft;" in src
    assert "uniform vec2 u_shadow_world;" in src
    assert "if (u_shadow_soft > 0.0) {" in src
    assert "soft_shadow_light(uvz, grad, bias, texel)" in src
