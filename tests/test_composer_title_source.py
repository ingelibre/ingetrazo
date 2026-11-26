# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What a view title says: the view's name, its full path through the
Scenes tab's folders, or custom text — so two scenes of the same name filed
in different folders («Ground floor / Plan new», «First floor / Plan new»)
read apart on a sheet."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from core.composition import (Composicion, MarcoVista, expand_fields,
                              frame_view_folders, local_field_names)
from core.saved_views import SavedView
from tests.test_composer_canvas import _FakeViewport
from views.composer import ComposerWindow, FrameItem, view_title_texts

_app = QApplication.instance() or QApplication([])


def _scene_with_folders(scene):
    """«01 Plans › 02 Ground floor › Plan new» and a top-level «Site»."""
    scene.scene_folders = ["01 Plans", "02 Ground floor"]
    scene.scene_folder_parents = {"02 Ground floor": "01 Plans"}
    scene.saved_views.append(SavedView("Plan new", folder="02 Ground floor"))
    scene.saved_views.append(SavedView("Site"))
    return scene


def _composer():
    host = QWidget()
    host.viewport = _FakeViewport()
    _scene_with_folders(host.viewport.scene)
    composer = ComposerWindow(host)
    composer._set_field_context(composer.comp)
    return composer, host


def test_the_default_title_is_still_the_view_name():
    composer, _host = _composer()
    f = composer.comp.frames[0]
    f.view_key, f.show_title = "scene:Plan new", True
    assert f.title_source == ""
    assert view_title_texts(f)["title"] == "Plan new"
    f.title_text = "PLAN"                    # a document from before: text wins
    assert view_title_texts(f)["title"] == "PLAN"


def test_full_path_with_its_options():
    composer, _host = _composer()
    f = composer.comp.frames[0]
    f.view_key, f.title_source = "scene:Plan new", "path"
    assert view_title_texts(f)["title"] == (
        "01 Plans / 02 Ground floor / Plan new")
    f.title_path_sep = " › "
    f.title_path_strip = True
    assert view_title_texts(f)["title"] == "Plans › Ground floor › Plan new"
    f.title_path_levels = 1
    assert view_title_texts(f)["title"] == "Ground floor › Plan new"
    f.title_text = "ignored while the source is the path"
    assert view_title_texts(f)["title"] == "Ground floor › Plan new"


def test_path_of_a_top_level_or_standard_view_is_its_name():
    composer, _host = _composer()
    f = composer.comp.frames[0]
    f.title_source = "path"
    f.view_key = "scene:Site"
    assert view_title_texts(f)["title"] == "Site"
    f.view_key = "std:top"
    assert view_title_texts(f)["title"] == "Top (plan)"
    assert frame_view_folders(f) == []


def test_name_source_ignores_typed_text_and_custom_uses_it():
    composer, _host = _composer()
    f = composer.comp.frames[0]
    f.view_key, f.title_text = "scene:Plan new", "Ground floor plan"
    f.title_source = "name"
    assert view_title_texts(f)["title"] == "Plan new"
    f.title_source = "custom"
    assert view_title_texts(f)["title"] == "Ground floor plan"
    f.title_text = ""
    assert view_title_texts(f)["title"] == "Plan new"       # empty: the name


def test_view_fields_read_this_frame_in_every_language():
    composer, _host = _composer()
    f = composer.comp.frames[0]
    f.view_key, f.title_source = "scene:Plan new", "custom"
    f.title_text = "{view} ({view_folder})"
    assert view_title_texts(f)["title"] == "Plan new (01 Plans / 02 Ground floor)"
    f.title_text = "{ansichtspfad}"
    assert view_title_texts(f)["title"] == "01 Plans / 02 Ground floor / Plan new"
    f.title_subtitle = "{vista}"
    assert view_title_texts(f)["subtitle"] == "Plan new"
    # Free sheet texts read the sheet's main frame.
    assert expand_fields("{ruta}") == "01 Plans / 02 Ground floor / Plan new"


def test_local_field_names_spell_the_view_fields():
    from core import i18n
    old = i18n.current_language()
    try:
        i18n.set_language("en")
        assert local_field_names("{ruta}") == "{view_path}"
        i18n.set_language("de")
        assert local_field_names("{carpeta}") == "{ansichtsordner}"
    finally:
        i18n.set_language(old)


def test_title_settings_survive_save_and_load():
    f = MarcoVista(title_source="path", title_path_sep=" › ",
                   title_path_levels=2, title_path_strip=True)
    comp = Composicion()
    comp.frames = [f]
    back = Composicion.from_dict(comp.to_dict()).frames[0]
    assert (back.title_source, back.title_path_sep, back.title_path_levels,
            back.title_path_strip) == ("path", " › ", 2, True)
    legacy = Composicion.from_dict({"frames": [{"title_text": "A"}]}).frames[0]
    assert legacy.title_source == "" and legacy.title_path_sep == " / "


def test_panel_switches_the_source_and_shows_path_rows_only_for_the_path():
    composer, _host = _composer()
    frame = composer.comp.frames[0]
    frame.view_key = "scene:Plan new"
    item = next(it for it in composer.canvas.items()
                if getattr(it, "model", None) is frame)
    assert isinstance(item, FrameItem)
    item.setSelected(True)
    composer.on_selection_changed()
    composer.title_check.setChecked(True)
    form = composer._frame_form
    assert composer.title_source_combo.currentData() == "name"
    assert not composer.title_text_edit.isEnabled()
    assert not any(form.isRowVisible(r) for r in composer._title_path_rows)
    composer.title_source_combo.setCurrentIndex(
        composer.title_source_combo.findData("path"))
    assert frame.title_source == "path"
    assert all(form.isRowVisible(r) for r in composer._title_path_rows)
    composer.title_strip_check.setChecked(True)
    composer.title_levels_spin.setValue(1)
    composer.title_sep_combo.setCurrentIndex(
        composer.title_sep_combo.findData(" › "))
    assert (frame.title_path_strip, frame.title_path_levels,
            frame.title_path_sep) == (True, 1, " › ")
    assert view_title_texts(frame)["title"] == "Ground floor › Plan new"
    composer.title_source_combo.setCurrentIndex(
        composer.title_source_combo.findData("custom"))
    assert composer.title_text_edit.isEnabled()
    composer.title_text_edit.setText("Plan")
    assert view_title_texts(frame)["title"] == "Plan"


def test_a_frame_from_before_shows_custom_text_when_it_has_some():
    composer, _host = _composer()
    frame = composer.comp.frames[0]
    frame.title_text, frame.show_title = "OLD TITLE", True
    item = next(it for it in composer.canvas.items()
                if getattr(it, "model", None) is frame)
    item.setSelected(True)
    composer.on_selection_changed()
    assert composer.title_source_combo.currentData() == "custom"
    assert composer.title_text_edit.isEnabled()
