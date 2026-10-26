# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The texts a NEW sheet item starts with are in the interface's language
— the title block's labels (PROYECTO, LÁMINA… were fixed Spanish), the
legend's title, a label's text, the level mark, the scale label and the
default sheet name. What a document was saved with stays as it is, and
filling the date, the scale or the sheet number still finds its row
whichever language labels it."""
from __future__ import annotations

import pytest

from core import i18n
from core.composition import (
    Cajetin, Composicion, EtiquetaItem, Leyenda, NivelItem,
)


@pytest.fixture
def german():
    before = i18n.current_language()
    i18n.set_language("de")
    yield
    i18n.set_language(before)


def test_a_new_title_block_speaks_the_interface_s_language(german):
    c = Cajetin()
    assert [row[0] for row in c.campos] == [
        "PROJEKT", "VERFASSER", "DATUM", "MASSSTAB", "BLATT"]


def test_new_items_and_a_new_sheet_speak_it_too(german):
    assert Leyenda().title == "LEGENDE"
    assert EtiquetaItem().text == "Text"
    assert NivelItem().text == "OKFF {z}"
    assert Composicion().name == "Blatt 1"
    assert Composicion.from_dict({}).name == "Blatt 1"


def test_english_is_the_source():
    before = i18n.current_language()
    i18n.set_language("en")
    try:
        assert [row[0] for row in Cajetin().campos] == [
            "PROJECT", "AUTHOR", "DATE", "SCALE", "SHEET"]
        assert Composicion().name == "Sheet 1"
    finally:
        i18n.set_language(before)


def test_a_saved_sheet_keeps_its_texts(german):
    c = Composicion.from_dict({
        "name": "Lámina 3",
        "cajetin": {"campos": [["PROYECTO", "Plaza"], ["LÁMINA", "L-03"]]},
        "leyendas": [{"title": "LEYENDA"}]})
    assert c.name == "Lámina 3"
    assert c.cajetin.campos == [["PROYECTO", "Plaza"], ["LÁMINA", "L-03"]]
    assert c.leyendas[0].title == "LEYENDA"


@pytest.mark.parametrize("label", ["LÁMINA", "SHEET", "BLATT", "Blatt"])
def test_the_sheet_number_finds_its_row_in_any_of_its_languages(german,
                                                                label):
    c = Cajetin(campos=[["PROYECTO", "Plaza"], [label, "L-01"]])
    c.set_field("lamina", "L-09")
    assert c.campos == [["PROYECTO", "Plaza"], [label, "L-09"]]


def test_a_missing_field_row_is_added_in_the_interface_s_language(german):
    c = Cajetin(campos=[["OBRA", "Pileta"]])
    c.set_field("fecha", "25/10/2026")
    assert c.campos[-1] == ["DATUM", "25/10/2026"]


def test_an_old_spanish_label_still_names_its_field(german):
    c = Cajetin()                                   # German rows
    c.set_field("ESCALA", "1:50")                   # as older code said it
    assert ["MASSSTAB", "1:50"] in c.campos


def test_a_custom_label_matches_as_written():
    c = Cajetin(campos=[["DISTRITO", ""]])
    c.set_field("distrito", "Yanque")
    assert c.campos == [["DISTRITO", "Yanque"]]
