# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The units question at startup (metres, millimetres or imperial, with
«Don't show this at startup»), its switch in Preferences ▸ Units, and
Window ▸ Units… on Ctrl+U."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QDialog

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core import units  # noqa: E402
from views import units_start_dialog as start  # noqa: E402
from views.units_start_dialog import UnitsStartDialog  # noqa: E402


@pytest.fixture(autouse=True)
def clean_settings():
    start.set_ask_at_start(True)
    units.remember_new_document_units(units.DEFAULT_MODEL_UNITS)
    yield
    start.set_ask_at_start(True)
    units.remember_new_document_units(units.DEFAULT_MODEL_UNITS)


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    _close(w)


def _answer(monkeypatch, profile, dont_ask=False, accept=True):
    """Make the dialog's exec pick ``profile`` (and tick the box)."""
    seen = {}

    def fake_exec(dlg):
        seen["choices"] = sorted(dlg.buttons)
        seen["preselected"] = dlg.profile()
        dlg.buttons[profile].setChecked(True)
        seen["preview"] = dlg.preview.text()
        dlg.dont_ask.setChecked(dont_ask)
        return QDialog.Accepted if accept else QDialog.Rejected

    monkeypatch.setattr(UnitsStartDialog, "exec", fake_exec)
    return seen


# ---- the three configurations ------------------------------------------------

@pytest.mark.parametrize("profile, expected, shown", [
    ("metric", {"length": "m", "precision": 2}, "1.23 m"),
    ("millimetric", {"length": "mm", "precision": 0}, "1235 mm"),
    ("imperial", {"length": "ft-in-frac", "precision": 2}, "4'5/8\""),
])
def test_each_choice_sets_the_new_document(win, monkeypatch, profile,
                                           expected, shown):
    seen = _answer(monkeypatch, profile)
    win.offer_units_at_start()
    assert seen["choices"] == ["custom", "imperial", "metric", "millimetric"]
    assert seen["preselected"] == "metric"             # metres by default
    assert shown in seen["preview"]
    scene = win.viewport.scene
    assert scene.units == expected
    assert scene.version == win._saved_version         # nothing to save
    assert units.new_document_units() == expected      # and every new one
    win._on_new()
    assert scene.units == expected


def test_metres_mean_square_and_cubic_metres_and_degrees(win, monkeypatch):
    _answer(monkeypatch, "metric")
    win.offer_units_at_start()
    assert units.fmt_area(2.0) == "2.00 m²"
    assert units.fmt_volume(2.0) == "2.000 m³"
    assert units.fmt_angle_deg(30) == "30.0°"


def test_the_last_choice_is_preselected_next_time(monkeypatch):
    units.remember_new_document_units({"length": "mm", "precision": 0})
    assert UnitsStartDialog().profile() == "millimetric"
    units.remember_new_document_units({"length": "cm", "precision": 1})
    dlg = UnitsStartDialog()
    assert dlg.profile() == "custom"                    # «keep my settings»
    assert dlg.settings() == {"length": "cm", "precision": 1}


def test_closing_the_question_changes_nothing(win, monkeypatch):
    _answer(monkeypatch, "imperial", accept=False)
    win.offer_units_at_start()
    assert win.viewport.scene.units == {"length": "m", "precision": 2}
    assert units.new_document_units() == {"length": "m", "precision": 2}


# ---- «Don't show this at startup» and back on ---------------------------------

def test_dont_show_again(win, monkeypatch):
    seen = _answer(monkeypatch, "millimetric", dont_ask=True)
    win.offer_units_at_start()
    assert win.viewport.scene.units["length"] == "mm"
    assert start.ask_at_start() is False
    seen.clear()
    win.offer_units_at_start()                          # the next start
    assert seen == {}                                   # not asked


def test_preferences_turn_it_back_on(win, monkeypatch):
    from views.preferences_dialog import PreferencesDialog
    start.set_ask_at_start(False)
    dlg = PreferencesDialog(win)
    assert dlg._units_at_start.isChecked() is False
    dlg._units_at_start.setChecked(True)
    dlg._units_for_new.setChecked(False)
    dlg.accept()
    assert start.ask_at_start() is True
    seen = _answer(monkeypatch, "metric")
    win.offer_units_at_start()
    assert seen["preselected"] == "metric"


def test_a_document_already_open_is_not_asked_about(win, monkeypatch, tmp_path):
    seen = _answer(monkeypatch, "imperial")
    win._current_path = tmp_path / "plano.igz"          # opened from argv
    win.offer_units_at_start()
    assert seen == {}
    win._current_path = None
    win.viewport.scene.version += 1                     # already drawn on
    win.offer_units_at_start()
    assert seen == {}


# ---- Ctrl+U -------------------------------------------------------------------------

def test_ctrl_u_opens_the_units_page(win, monkeypatch):
    from views import preferences_dialog as prefs
    act = win._act_units
    assert act.shortcut() == QKeySequence("Ctrl+U")
    others = [a for a in win.findChildren(type(act))
              if a is not act and QKeySequence("Ctrl+U") in a.shortcuts()]
    assert others == []                                 # nobody else has it
    opened = {}

    def fake_exec(dlg):
        opened["page"] = dlg._tabs.currentWidget()
        opened["units"] = dlg._units_page
        return QDialog.Rejected

    monkeypatch.setattr(prefs.PreferencesDialog, "exec", fake_exec)
    act.trigger()
    assert opened["page"] is opened["units"]


def test_custom_leads_to_the_units_panel(win, monkeypatch):
    """Custom…: OK opens Preferences on the Units page, «Also use for new
    documents» ticked; what is picked there is what the document gets."""
    from views import preferences_dialog as prefs
    _answer(monkeypatch, "custom")
    seen = {}

    def fake_prefs_exec(dlg):
        seen["page"] = dlg._tabs.currentWidget() is dlg._units_page
        seen["for_new"] = dlg._units_for_new.isChecked()
        p = dlg._units_panel
        p.length.setCurrentIndex(p.length.findData("cm"))
        p.decimals.setValue(1)
        p.area.setCurrentIndex(p.area.findData("m2"))
        p.area_decimals.setValue(2)
        p.decimal.setCurrentIndex(p.decimal.findData(","))
        dlg.accept()
        return QDialog.Accepted

    monkeypatch.setattr(prefs.PreferencesDialog, "exec", fake_prefs_exec)
    got = start.offer_at_start(win)
    assert seen == {"page": True, "for_new": True}
    want = {"length": "cm", "precision": 1, "area": "m2", "area_precision": 2,
            "decimal": ","}
    assert got == want
    assert win.viewport.scene.units == want
    assert win.viewport.scene.version == win._saved_version   # nothing to save
    assert units.new_document_units() == want
    assert units.fmt_len(1.2345) == "123,5 cm"
    assert units.fmt_area(12.345) == "12,35 m²"


def test_custom_cancelled_changes_nothing(win, monkeypatch):
    from views import preferences_dialog as prefs
    _answer(monkeypatch, "custom")
    monkeypatch.setattr(prefs.PreferencesDialog, "exec",
                        lambda dlg: QDialog.Rejected)
    assert start.offer_at_start(win) is None
    assert win.viewport.scene.units == {"length": "m", "precision": 2}
