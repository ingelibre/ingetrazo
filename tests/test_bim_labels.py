# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""BIM panel IFC labels are translated, not just the IFC code (#1578).

The class dropdown shows the code plus its translated name
(``"IfcWall (Wand)"`` in German) and the takeoff tree shows the translated
name alone (``"Wand"``). Stored tags and exports keep using the IFC code.
The delivery button falls back to the main catalogues when the Türkiye
profile has no translation for the language.
"""
from __future__ import annotations

import pytest

from core import i18n
from views.bim_labels import class_label, short_class_label


@pytest.fixture(autouse=True)
def _restore_language():
    previous = i18n.current_language()
    yield
    i18n.set_language(previous)


def test_german_dropdown_shows_code_plus_translated_name():
    i18n.set_language("de")
    assert class_label("IfcWall") == "IfcWall (Wand)"
    assert class_label("IfcSlab") == "IfcSlab (Decke)"
    assert class_label("IfcWindow") == "IfcWindow (Fenster)"


def test_german_tree_shows_translated_name_only():
    i18n.set_language("de")
    assert short_class_label("IfcWall") == "Wand"
    assert short_class_label("IfcSlab") == "Decke"
    assert short_class_label("IfcWindow") == "Fenster"


def test_english_and_turkish_labels_are_unchanged():
    i18n.set_language("en")
    assert class_label("IfcWall") == "IfcWall"
    assert short_class_label("IfcWall") == "Wall"
    i18n.set_language("tr")
    assert class_label("IfcWall") == "IfcWall — Duvar"
    assert short_class_label("IfcWall") == "IfcWall — Duvar"


def test_delivery_button_falls_back_to_the_main_catalogue():
    from core.turkiye_delivery import ui

    i18n.set_language("de")
    assert ui("Türkiye delivery information") == (
        "Informationen zur Lieferung in Türkiye")
    i18n.set_language("fr")
    assert ui("Türkiye delivery information") == (
        "Informations de livraison pour la Türkiye")
