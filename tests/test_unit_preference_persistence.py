# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Unit choices and the new-document opt-in survive Preferences and reopening."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QWidget

from core import units
from core.scene import Scene
from formats import igz
from views.preferences_dialog import PreferencesDialog


CM = {"length": "cm", "precision": 2}
METRES = {"length": "m", "precision": 2, "area": "m2", "area_precision": 2}


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path):
    """Use the suite's isolated INI store with a separate identity per test."""
    previous = (QCoreApplication.organizationName(), QCoreApplication.applicationName())
    QCoreApplication.setOrganizationName("UnitPreferencePersistenceTests")
    QCoreApplication.setApplicationName(tmp_path.name)
    units.remember_new_document_units(CM)
    yield
    QCoreApplication.setOrganizationName(previous[0])
    QCoreApplication.setApplicationName(previous[1])


class _Viewport:
    edit_rest_mode = "fade"
    history = None

    def __init__(self, settings):
        self.scene = Scene()
        units.apply_units(self.scene, settings)
        self.notifications = 0

    def update(self):
        pass

    def set_edit_rest_mode(self, mode):
        self.edit_rest_mode = mode

    def notify_scene_changed(self):
        self.notifications += 1


def _dialog(settings):
    window = QWidget()
    window.viewport = _Viewport(settings)
    return window, PreferencesDialog(window)


def _choose(panel, settings):
    panel.set_settings(settings)


@pytest.mark.parametrize("chosen", [METRES, {**METRES, "length": "cm"},
                                    {"length": "mm", "precision": 1}])
def test_changed_units_remain_the_default_when_the_open_model_differs(chosen):
    window, dialog = _dialog({"length": "ft", "precision": 2})
    _choose(dialog._units_panel, chosen)
    dialog.accept()

    # Applying the document's units must also remember the still-enabled
    # new-document choice; it cannot be inferred from the old units matching.
    assert window.viewport.scene.units == chosen
    assert units.new_document_units() == chosen
    from views.main_window import MainWindow
    fresh_scene = Scene()
    fresh_window = SimpleNamespace(viewport=SimpleNamespace(scene=fresh_scene))
    MainWindow._apply_new_document_units(fresh_window)
    assert fresh_scene.units == chosen


def test_accepting_unrelated_preferences_does_not_restore_a_stale_default():
    window, dialog = _dialog(CM)
    # Another window can change the global default while this dialog is open.
    units.remember_new_document_units(METRES)
    dialog._autosave_min.setValue(dialog._autosave_min.value() + 1)
    dialog.accept()

    assert units.new_document_units() == METRES
    assert window.viewport.scene.units == CM
    assert window.viewport.notifications == 0


def test_document_only_choice_is_remembered_after_reopening_preferences():
    window, dialog = _dialog(CM)
    dialog._units_for_new.setChecked(False)
    _choose(dialog._units_panel, METRES)
    dialog.accept()
    assert window.viewport.scene.units == METRES
    assert units.new_document_units() == CM

    # Match the saved default here: equality used to re-enable the checkbox.
    reopened_window, reopened = _dialog(CM)
    assert not reopened._units_for_new.isChecked()
    _choose(reopened._units_panel, {"length": "mm", "precision": 0})
    reopened.accept()
    assert reopened_window.viewport.scene.units["length"] == "mm"
    assert units.new_document_units() == CM


def test_unrelated_preferences_do_not_reenable_a_newer_document_only_choice():
    stale_window, stale = _dialog(CM)
    other_window, other = _dialog(CM)
    other._units_for_new.setChecked(False)
    other.accept()
    stale._autosave_min.setValue(stale._autosave_min.value() + 1)
    stale.accept()

    final_window, final = _dialog(CM)
    assert not final._units_for_new.isChecked()
    final.reject()
    assert units.new_document_units() == CM


def test_explicitly_enabling_defaults_remembers_unchanged_document_units():
    window, dialog = _dialog(CM)
    dialog._units_for_new.setChecked(False)
    dialog.accept()

    other_window, other = _dialog(METRES)
    assert not other._units_for_new.isChecked()
    other._units_for_new.setChecked(True)
    other.accept()
    assert other_window.viewport.scene.units == METRES
    assert units.new_document_units() == METRES


def test_cancel_does_not_change_units_or_the_document_only_choice():
    window, dialog = _dialog(CM)
    dialog._units_for_new.setChecked(False)
    dialog.accept()

    other_window, cancelled = _dialog(CM)
    cancelled._units_for_new.setChecked(True)
    _choose(cancelled._units_panel, METRES)
    cancelled.reject()
    assert units.new_document_units() == CM
    assert other_window.viewport.scene.units == CM
    final_window, final = _dialog(CM)
    assert not final._units_for_new.isChecked()
    final.reject()


def test_independent_length_and_area_units_roundtrip_in_the_model(tmp_path):
    chosen = {**METRES, "length": "cm"}
    window, dialog = _dialog({"length": "mm", "precision": 0})
    _choose(dialog._units_panel, chosen)
    dialog.accept()
    path = tmp_path / "independent-units.igz"
    igz.save_scene(window.viewport.scene, path)

    loaded = Scene()
    igz.load_into(loaded, path)
    assert loaded.units == chosen
    assert loaded.dimension_style["units"] == "cm"
    assert units.new_document_units() == chosen

    # A document retains its own units even when the global default changes.
    units.remember_new_document_units(METRES)
    igz.load_into(loaded, path)
    assert loaded.units == chosen
    assert units.new_document_units() == METRES


def test_document_unit_changes_notify_the_window():
    window, dialog = _dialog(CM)
    original_version = window.viewport.scene.version
    _choose(dialog._units_panel, METRES)
    dialog.accept()
    assert window.viewport.scene.version == original_version + 1
    assert window.viewport.notifications == 1
