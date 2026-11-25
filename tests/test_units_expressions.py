# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #630: a calculation typed after «=» where a measurement goes —
«=1.25*2+2.45/2» instead of working the sum out on paper first."""
from __future__ import annotations

import pytest

from core import units

IN = 0.0254
FT = 0.3048


@pytest.fixture(autouse=True)
def _metres():
    units.bind_scene(None)
    yield
    units.bind_scene(None)


@pytest.mark.parametrize("text, metres", [
    ("=1.25*2+2.45/2", 3.725),                 # the example of the issue
    ("=(3-0.15*2)/4", 0.675),                  # parentheses first
    ("=2+3*4", 14.0),                          # * before +
    ("=1,25*2", 2.5),                          # decimal comma
    ("= 1 + 2 ", 3.0),                         # spaces are free
    ("=-(2+1)", -3.0), ("=--2", 2.0), ("=+2", 2.0),
    ("=1.20m+35cm", 1.55),                     # a unit on each term
    ("=2*45cm", 0.9),                          # a plain factor stays plain
    ("=45cm*2", 0.9),
    ("=90cm/2", 0.45),
    ("=1+20cm", 1.2),                          # bare = document unit
    ("=2m/50cm", 4.0),                         # a ratio is a plain number
    ("=1m 20+1", 2.2),                         # «1m 20» is still 1.20 m
    ('=3/4"+1"', 1.75 * IN),                   # a fraction with its mark
    ('=5\'3"+1"', 5 * FT + 4 * IN),
    ('=1 1/2"*2', 3 * IN),
])
def test_calculations_in_a_metre_document(text, metres):
    r = units.parse(text, "length")
    assert r.ok, r.error
    assert r.value == pytest.approx(metres)


@pytest.mark.parametrize("text, error", [
    ("=", "Type a calculation after ="),
    ("=2+", "A number is missing"),
    ("=*2", "A number is missing"),
    ("=(1+2", "A parenthesis is not closed"),
    ("=1+2)", "A parenthesis closes nothing"),
    ("=(2)3", "An operator is missing"),
    ("=1/0", "Division by zero"),
    ("=1/(2-2)", "Division by zero"),
    ("=2m*3m", "Two measurements can't be multiplied: one must be a plain "
               "number"),
    ("=2/3m*3m", "Two measurements can't be multiplied: one must be a plain "
                 "number"),
    ("=2/(3m)", "A plain number can't be divided by a measurement"),
    ("=5 m2", "Expected a length"),
    ("=2+3abc", "Unknown unit: {unit}"),
])
def test_what_does_not_add_up_says_why(text, error):
    r = units.parse(text, "length")
    assert not r.ok and r.error == error
    assert r.message()                          # translatable, never empty


def test_nothing_typed_is_run_as_code():
    for text in ("=__import__('os')", "=2**3", "=len('ab')", "=1e3"):
        assert not units.parse(text, "length").ok


def test_an_absurd_result_is_refused():
    assert not units.parse("=999999999*999999999", "length").ok


def test_a_plain_number_follows_the_document_unit():
    class _Scene:
        units = {"length": "mm", "precision": 0}
    units.bind_scene(_Scene())
    r = units.parse("=1000+500", "length")
    assert r.value == pytest.approx(1.5)        # 1500 mm
    r = units.parse("=2*45cm", "length")
    assert r.value == pytest.approx(0.9)        # the factor stays 2


def test_unitless_fields_read_plain_numbers():
    with units.unitless_numbers():
        r = units.parse("=90/4+0.5", "length")
    assert r.value == pytest.approx(23.0)       # an angle or a factor


def test_angles_take_calculations_too():
    r = units.parse("=90-30", "angle")
    assert r.ok and r.value == pytest.approx(units.parse("60", "angle").value)


def test_without_the_equals_sign_nothing_changes():
    assert units.parse("2+3", "length").ok is False
    assert units.parse("1m 20", "length").value == pytest.approx(1.2)
    assert units.parse('3/4"', "length").value == pytest.approx(0.75 * IN)
