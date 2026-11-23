# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The fog is part of the style, so its controls sit in the Styles window's
Background page instead of behind a toolbar button of their own."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QToolBar, QToolButton

from core.style import Style

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def library(tmp_path, monkeypatch):
    import core.style as styles
    monkeypatch.setattr(styles, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))


@pytest.fixture
def editor(library):
    from tests.test_styles_window import _Window
    from views.tray import StylesPanel
    window = _Window()
    panel = StylesPanel(window)
    window.panel = panel
    yield window, panel
    panel.close()
    panel.deleteLater()


def test_the_fog_controls_are_on_the_background_page(editor):
    _window, panel = editor
    background = panel._edit_stack.widget(2)
    assert background.isAncestorOf(panel.fog)
    assert background.isAncestorOf(panel.fog._enable)


def test_the_fog_switch_edits_the_style_and_marks_it_changed(editor):
    window, panel = editor
    seen = []
    window._sync_style_menu = lambda: seen.append(True)
    panel.fog._enable.setChecked(True)
    assert window.viewport.scene.display_style.fog_enabled
    assert seen                      # the header shows the edited style
    assert window.viewport.updates


def test_choosing_a_style_shows_its_fog(editor):
    window, panel = editor
    window.viewport.scene.display_style = Style(fog_enabled=True,
                                                fog_use_background=True)
    panel.refresh()
    assert panel.fog._enable.isChecked()
    assert panel.fog._use_background.isChecked()
    window.viewport.scene.display_style = Style()
    panel.refresh()
    assert not panel.fog._enable.isChecked()


def test_the_panels_toolbar_has_no_separate_fog_button(library):
    from views.main_window import MainWindow
    window = MainWindow()
    try:
        toolbar = window.findChild(QToolBar, "panels_toolbar")
        keys = [key for button, key in window._icon_actions
                if isinstance(button, QToolButton)
                and toolbar.isAncestorOf(button)]
        assert "fog" not in keys and "styles" in keys
        # The window's fog_panel (refreshed on loads) is the one in Styles.
        assert window.fog_panel is window.styles_panel.fog
    finally:
        window._saved_version = window.viewport.scene.version
        window.close()


def test_the_fog_rows_line_up_with_the_page_and_the_track_is_full_width(editor):
    """The Background page folds into sections (Sky and ground, Panorama,
    Fog) like the Camera Settings'; their label columns are one, so the fog
    swatch starts where the horizon's does, and the fog distance's value
    sits beside its name, not beside the track (it used to squeeze it)."""
    _window, panel = editor
    panel.resize(460, 1400)
    panel._tabs.setCurrentIndex(1)
    panel._select_category(2)
    for sec in panel._background_sections:
        sec.set_open(True)
    panel.show()
    QApplication.processEvents()
    fog = panel.fog
    titles = [sec.header.text() for sec in panel._background_sections]
    assert titles == ["Sky and ground", "Panorama", "Fog"]
    x = lambda w: w.mapTo(panel, w.rect().topLeft()).x()
    assert x(fog._color) == x(panel._horizon_c) == x(panel._panorama_btn)
    assert fog._color.width() == panel._horizon_c.width()
    body = panel._background_sections[2].body
    assert fog._range.width() >= 0.85 * body.width()
    panel.hide()


def test_the_style_pages_scroll_only_up_and_down(editor):
    from PySide6.QtCore import Qt
    _window, panel = editor
    for i in range(panel._edit_stack.count()):
        area = panel._edit_stack.widget(i)
        assert area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
