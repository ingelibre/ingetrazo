# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Preferences fits a short screen (#1336).

On a laptop screen the dialog was taller than the screen and could not be
made smaller, so OK and Cancel were out of reach. Its pages now scroll:
it opens no taller than the screen, can be shrunk by hand, and with room
to spare it opens at its natural size, as before."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, QSettings
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

import views.preferences_dialog as prefs_mod  # noqa: E402
from views.preferences_dialog import PreferencesDialog  # noqa: E402


@pytest.fixture(autouse=True)
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "prefs.ini"
    monkeypatch.setattr(
        prefs_mod, "QSettings",
        lambda: QSettings(str(path), QSettings.IniFormat))
    return path


class _Win(QWidget):
    """Just enough main window for the dialog."""

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


#: A short laptop screen's free area, in logical pixels: 1600×900 at 125 %
#: is 1280×720, less a taskbar.
_SHORT = QRect(0, 0, 1280, 480)


def test_the_dialog_can_be_made_shorter_than_its_tallest_page():
    dlg = PreferencesDialog(_Win())
    dlg.layout().activate()
    tallest = max(dlg._tabs.widget(i).sizeHint().height()
                  for i in range(dlg._tabs.count()))
    assert dlg.minimumSizeHint().height() < tallest
    assert dlg.minimumSizeHint().height() <= 400


def test_on_a_short_screen_it_opens_within_it_with_the_buttons_in_reach():
    dlg = PreferencesDialog(_Win())
    dlg.fit_to(_SHORT)
    assert dlg.height() <= _SHORT.height()
    dlg.show()
    QApplication.processEvents()
    try:
        # OK and Cancel sit inside the dialog, not cut off below it.
        assert dlg._buttons.isVisible()
        assert dlg._buttons.geometry().bottom() < dlg.height()
        # The tallest page scrolls instead.
        dlg._tabs.setCurrentIndex(0)
        QApplication.processEvents()
        page = dlg._tabs.currentWidget()
        assert isinstance(page, QScrollArea)
        assert page.verticalScrollBar().maximum() > 0
    finally:
        dlg.close()


def test_with_room_to_spare_it_opens_at_its_natural_size():
    dlg = PreferencesDialog(_Win())
    dlg.fit_to(QRect(0, 0, 4000, 3000))
    assert dlg.size() == dlg.sizeHint()


def test_the_pages_are_all_there_and_units_still_opens_on_its_page():
    dlg = PreferencesDialog(_Win())
    names = [dlg._tabs.tabText(i) for i in range(dlg._tabs.count())]
    assert len(names) == 6
    for i in range(dlg._tabs.count()):
        page = dlg._tabs.widget(i)
        if page is dlg._shortcuts:          # its list scrolls on its own
            continue
        assert isinstance(page, QScrollArea), names[i]
        assert page.widget() is not None
    dlg.show_units_page()
    current = dlg._tabs.currentWidget()
    assert current is dlg._units_page
    assert dlg._units_panel in current.widget().findChildren(
        type(dlg._units_panel))
