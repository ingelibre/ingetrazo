# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #221: someone who models parts for a 3D printer wants each new
document to start empty, without the 1.70 m scale figure. Preferences ▸
General ▸ «Put the scale figure in new documents»."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def figure_setting():
    yield lambda on: QSettings().setValue("new_document/scale_figure",
                                          "1" if on else "0")
    QSettings().remove("new_document/scale_figure")


def _window():
    from views.main_window import MainWindow
    return MainWindow()


def _close(w):
    w._saved_version = w.viewport.scene.version    # no "save?" modal
    w.close()


def test_by_default_a_new_document_has_the_figure(figure_setting):
    w = _window()
    try:
        assert len(w.viewport.scene.groups) == 1
    finally:
        _close(w)


def test_switched_off_new_documents_start_empty(figure_setting):
    figure_setting(False)
    w = _window()
    try:
        assert w.viewport.scene.groups == []           # at startup
        assert not w._is_dirty()                       # and not «unsaved»
        w._on_new()
        assert w.viewport.scene.groups == []           # and on File ▸ New
        assert not w._is_dirty()
    finally:
        _close(w)


def test_the_preference_is_stored(figure_setting):
    from views.preferences_dialog import PreferencesDialog
    w = _window()
    try:
        dlg = PreferencesDialog(w)
        assert dlg._scale_figure.isChecked()
        dlg._scale_figure.setChecked(False)
        dlg.accept()
        assert QSettings().value("new_document/scale_figure") == "0"
    finally:
        _close(w)
