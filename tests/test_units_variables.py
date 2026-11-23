# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The model's variables (a follow-up of #630): a measurement named once
in the model — ``ancho`` = ``3.20m`` — read by name in every calculation
typed after «=», as in ``=ancho/2``."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from core import units  # noqa: E402
from core.history import SetVariablesCommand  # noqa: E402
from core.scene import Scene  # noqa: E402

VARS = {"ancho": "3.20m", "muro": "15cm", "n": "4",
        "luz": "=ancho-2*muro", "giro": "30°", "media": "=luz/2"}


@pytest.fixture(autouse=True)
def _metres():
    units.bind_scene(None)
    yield
    units.bind_scene(None)


@pytest.mark.parametrize("text, metres", [
    ("=ancho/2", 1.6),                       # the example asked for
    ("=ANCHO/2", 1.6),                       # a name has no case
    ("=ancho/n", 0.8),                       # a plain-number variable
    ("=n*45cm", 1.8),
    ("=luz", 2.9),                           # a variable of variables
    ("=media+10cm", 1.55),                   # two levels deep
    ("=(ancho-muro)/2", 1.525),
    ("=2*ancho+10cm", 6.5),
    ("=n", 4.0),                             # alone: the field's unit
])
def test_variables_in_a_calculation(text, metres):
    r = units.parse_expression(text, variables=VARS)
    assert r.ok, r.message()
    assert r.value == pytest.approx(metres)


def test_the_bound_scene_lends_its_variables_to_every_field():
    scene = Scene()
    scene.variables = {"ancho": "3.20m"}
    units.bind_scene(scene)
    # parse() is what the value box and every length field read through.
    assert units.parse("=ancho/2").value == pytest.approx(1.6)
    assert units.parse_length_field("=ancho/2") == pytest.approx(1.6)


def test_a_plain_number_variable_follows_the_field_unit():
    r = units.parse_expression("=n", "length", "cm", variables=VARS)
    assert r.value == pytest.approx(0.04)


def test_an_angle_variable_serves_an_angle_field_only():
    r = units.parse_expression("=giro*2", "angle", variables=VARS)
    assert r.value == pytest.approx(math.radians(60))
    r = units.parse_expression("=giro", "length", variables=VARS)
    assert not r.ok and r.position == 1


@pytest.mark.parametrize("text, error, where, word", [
    ("=alto/2", "Unknown variable: {name}", 1, "alto"),
    ("=1+ alto", "Unknown variable: {name}", 4, "alto"),
    ("=ancho*ancho", "Two measurements can't be multiplied: one must be "
                     "a plain number", 6, ""),
])
def test_what_does_not_add_up(text, error, where, word):
    r = units.parse_expression(text, variables=VARS)
    assert (r.error, r.position, r.word) == (error, where, word)


def test_the_error_names_the_variable():
    r = units.parse_expression("=alto/2", variables=VARS)
    assert "alto" in r.message()


def test_a_circle_of_variables_is_an_error_not_a_hang():
    vs = {"a": "=b+1", "b": "=a*2", "c": "=c"}
    for name in vs:
        r = units.parse_expression(f"={name}", variables=vs)
        assert r.error == "The variable {name} depends on itself"


def test_a_broken_variable_is_named_where_it_is_used():
    vs = {"ancho": "=3m+", "malo": "3 xx"}
    r = units.parse_expression("=1+ancho", variables=vs)
    assert (r.error, r.word, r.position) == (
        "The variable {name} has an error", "ancho", 3)
    r = units.parse_expression("=malo", variables=vs)
    assert r.word == "malo"


def test_without_variables_calculations_read_as_before():
    assert units.parse_expression("=1.25*2+2.45/2").value == \
        pytest.approx(3.725)
    assert units.parse_expression("=2*45cm").value == pytest.approx(0.9)
    assert units.parse_expression("=1m+cm").ok is False


@pytest.mark.parametrize("name, others, error", [
    ("ancho", (), ""),
    ("ancho_2", (), ""),
    ("año", (), ""),                          # letters of any language
    ("", (), "Type a name"),
    ("2ancho", (), "A name starts with a letter and has only letters, "
                   "digits and _"),
    ("an cho", (), "A name starts with a letter and has only letters, "
                   "digits and _"),
    ("cm", (), "{name} is a unit: choose another name"),
    ("Metros", (), "{name} is a unit: choose another name"),
    ("ANCHO", ("ancho",), "There is already a variable called {name}"),
])
def test_names(name, others, error):
    assert units.variable_name_error(name, others) == error


def test_read_variable_says_what_it_holds():
    assert units.read_variable("ancho", VARS) == ("length", pytest.approx(3.2))
    assert units.read_variable("n", VARS) == ("number", 4.0)
    kind, value = units.read_variable("giro", VARS)
    assert kind == "angle" and value == pytest.approx(math.radians(30))
    assert units.read_variable("sup", {"sup": "12m2"})[0] == "area"
    kind, bad = units.read_variable("a", {"a": "=a"})
    assert kind is None and "a" in bad.message()


def test_renaming_keeps_the_calculations_that_read_it():
    vs = units.rename_variable(
        {"ancho": "3m", "luz": "=Ancho-2*anchos+ancho_2+ancho"}, "ancho", "w")
    assert list(vs) == ["w", "luz"]
    assert vs["luz"] == "=w-2*anchos+ancho_2+w"


def test_model_variables_drops_what_is_not_a_variable():
    raw = {"variables": {"ancho": "3m", "cm": "1", "2x": "1", "n": 4,
                         "ANCHO": "5m"}}
    assert units.model_variables(raw) == {"ancho": "3m"}
    assert units.model_variables({}) == {}


def test_set_variables_command_undo_and_redo():
    scene = Scene()
    before = scene.version
    cmd = SetVariablesCommand({"ancho": "3.20m", "n": "4"})
    cmd.do(scene)
    assert scene.variables == {"ancho": "3.20m", "n": "4"}
    assert scene.version > before
    cmd.undo(scene)
    assert scene.variables == {}
    cmd.do(scene)
    assert list(scene.variables) == ["ancho", "n"]


def test_a_new_document_forgets_the_variables():
    scene = Scene()
    scene.variables = {"ancho": "3m"}
    scene.clear()
    assert scene.variables == {}


def test_variables_travel_in_the_igz(tmp_path):
    from formats import igz
    scene = Scene()
    scene.variables = {"ancho": "3.20m", "n": "4", "luz": "=ancho/n"}
    path = tmp_path / "vars.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.variables == scene.variables
    assert list(back.variables) == ["ancho", "n", "luz"]   # order kept


def test_a_model_without_variables_saves_no_key(tmp_path):
    from formats import igz
    scene = Scene()
    path = tmp_path / "none.igz"
    igz.save_scene(scene, path)
    back = Scene()
    back.variables = {"stale": "1m"}
    igz.load_into(back, path)
    assert back.variables == {}
