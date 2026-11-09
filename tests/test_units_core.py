# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The units core: one table, one way in (``parse``) and one way out
(``format_*``). Values are stored in metres; the units only change what is
shown and what a bare number means. Most checks run over generated values
(a seeded random sweep) so the round trip holds everywhere, not only on
the handful of numbers a person would pick."""
from __future__ import annotations

import math
import random

import pytest

from core import units
from core.scene import Scene

IN = 0.0254
FT = 0.3048


@pytest.fixture
def doc():
    """A bound scene whose units a test sets; metres afterwards."""
    scene = Scene()
    units.bind_scene(scene)

    def set_units(length, precision=2):
        scene.units = {"length": length, "precision": precision}
        return scene
    yield set_units
    units.bind_scene(None)


# ---- the table ------------------------------------------------------------

def test_exact_factors():
    assert units.convert(1, "in", "m") == IN
    assert units.convert(1, "ft", "m") == FT
    assert units.convert(1, "m", "cm") == pytest.approx(100)
    assert units.convert(1, "m", "mm") == pytest.approx(1000)
    assert units.convert(12, "in", "ft") == pytest.approx(1)
    assert units.convert(1, "yd", "ft") == pytest.approx(3)
    assert units.convert(1, "mi", "ft") == pytest.approx(5280)
    assert units.convert(1, "acre", "ft2") == pytest.approx(43560)
    assert units.convert(1, "ha", "m2") == pytest.approx(10000)
    assert units.convert(1, "gal", "in3") == pytest.approx(231)
    assert units.convert(180, "deg", "rad") == pytest.approx(math.pi)
    assert units.convert(400, "grad", "deg") == pytest.approx(360)


def test_survey_foot_is_its_own_unit():
    """About 2 parts per million longer than the international foot — kept
    apart so a survey file is not read 2 ppm off."""
    ratio = units.convert(1, "us-ft", "ft")
    assert ratio != 1.0
    assert (ratio - 1) * 1e6 == pytest.approx(2.0, abs=0.01)


def test_a_length_is_never_an_area():
    with pytest.raises(ValueError):
        units.convert(1, "m", "m2")


def test_every_unit_is_well_formed():
    for code, row in units.UNITS.items():
        assert row.code == code
        assert row.kind in units.BASE_UNIT
        assert row.factor > 0 and math.isfinite(row.factor)
        assert row.symbol
        # every alias reads back as its own unit
        for alias in row.aliases:
            assert units._ALIASES[alias.lower()] is row, alias
    for kind, base in units.BASE_UNIT.items():
        assert units.UNITS[base].factor == 1.0 and units.UNITS[base].kind == kind


# ---- reading what is typed ------------------------------------------------

@pytest.mark.parametrize("text, metres", [
    ("1,20", 1.2), ("1.20", 1.2), ("1.20 m", 1.2), ("120cm", 1.2),
    ("1m 20", 1.2), ("1m20", 1.2), ("1m 20cm", 1.2), ("  5 cm ", 0.05),
    ("-0,5 m", -0.5), ("+2m", 2.0), ("2 metros", 2.0), ("3 pies", 3 * FT),
    ("1500 milímetros", 1.5), ("0.002 km", 2.0), ("2 yd", 2 * 0.9144),
    ('3\'6"', 3 * FT + 6 * IN), ("5'", 5 * FT), ("5'3", 5 * FT + 3 * IN),
    ('5\' 3 1/2"', 5 * FT + 3.5 * IN), ('63"', 63 * IN),
    ('3\'-6 1/2"', 3 * FT + 6.5 * IN), ("5ft 3in", 5 * FT + 3 * IN),
    ("5ft 3", 5 * FT + 3 * IN), ('1 1/2"', 1.5 * IN), ('3/4"', 0.75 * IN),
    ("3′ 6″", 3 * FT + 6 * IN),
])
def test_tolerant_input(doc, text, metres):
    doc("m")
    r = units.parse(text)
    assert r.ok, (text, r.error)
    assert r.value == pytest.approx(metres, abs=1e-12)


@pytest.mark.parametrize("text, error", [
    ("abc", "Not a number"), ("", "Type a value"), ("   ", "Type a value"),
    ("-", "Type a number"), ("5 m²", "Expected a length"),
    ("5 m2", "Expected a length"), ("3 l", "Expected a length"),
    ("45°", "Expected a length"), ("2 furlongs", "Unknown unit: {unit}"),
    ("2 3", "Type one value"), ("2mm 3", "Type one value"),
    ('3/0"', "Not a number"), ("1''", "Not a number"), ("1e5", "Unknown unit: {unit}"),
    ("9" * 400, "Not a number"), ("nan", "Not a number"), ("inf", "Not a number"),
])
def test_invalid_input_explains_itself(doc, text, error):
    doc("m")
    r = units.parse(text)
    assert not r.ok and r.value is None
    assert r.error == error
    assert r.message()                    # a readable text, never empty


def test_the_error_points_at_the_problem():
    r = units.parse("12 m²")
    assert r.position == 3 and r.word == "m²"
    assert "furlongs" in units.parse("2 furlongs").message()


def test_errors_are_translated(doc):
    from core.i18n import set_language
    set_language("es")
    try:
        assert units.parse("5 m²").message() == "Se esperaba una longitud"
        assert units.parse("2 xyz").message() == "Unidad desconocida: xyz"
    finally:
        set_language("en")


@pytest.mark.parametrize("length, metres", [
    ("m", 2.0), ("cm", 0.02), ("mm", 0.002), ("in", 2 * IN), ("ft", 2 * FT),
    ("ft-in", 2 * IN), ("in-frac", 2 * IN), ("ft-in-frac", 2 * IN),
])
def test_a_bare_number_is_in_the_documents_unit(doc, length, metres):
    doc(length)
    assert units.parse("2").value == pytest.approx(metres)
    assert units.parse("2m").value == pytest.approx(2.0)     # its own unit wins


def test_a_field_can_name_its_own_unit(doc):
    doc("m")
    assert units.parse("25", unit="mm").value == pytest.approx(0.025)
    assert units.parse("25", unit="in-frac").value == pytest.approx(25 * IN)


def test_hyphen_feet_inches_only_in_imperial(doc):
    doc("ft-in")
    assert units.parse("5-3 1/2").value == pytest.approx(5 * FT + 3.5 * IN)
    assert units.parse("5-3").value == pytest.approx(5 * FT + 3 * IN)
    assert units.parse("1-1/2").value == pytest.approx(1.5 * IN)   # mixed number
    doc("m")
    assert not units.parse("5-3").ok


def test_other_kinds(doc):
    doc("m")
    assert units.parse("2 ha", "area").value == pytest.approx(20000)
    assert units.parse("3 m²", "area").value == pytest.approx(3)
    assert units.parse("1 acre", "area").value == pytest.approx(4046.8564224)
    assert units.parse("3 l", "volume").value == pytest.approx(0.003)
    assert units.parse("1 gal", "volume").value == pytest.approx(3.785411784e-3)
    assert units.parse("45°", "angle").value == pytest.approx(math.pi / 4)
    assert units.parse("45", "angle").value == pytest.approx(math.pi / 4)
    assert units.parse("1 rad", "angle").value == pytest.approx(1)
    assert units.parse("2 m", "area").error == "Expected an area"
    doc("mm")
    assert units.parse("4", "area").value == pytest.approx(4e-6)  # mm²


# ---- showing a value -------------------------------------------------------

def test_fractions_round_to_the_nearest_and_carry():
    assert units.format_length(0.5 * IN, "in-frac", 2) == '1/2"'
    assert units.format_length(11.99 * IN, "ft-in-frac", 2) == "1'0\""
    assert units.format_length(11.99 * IN, "ft-in-frac", 2) != "0'11 16/16\""
    assert units.format_length(3.999 * IN, "in-frac", 2) == '4"'
    assert units.format_length(15 / 16 * IN, "in-frac", 2) == '15/16"'
    assert units.format_length(1.5 * IN, "ft-in", 1) == "0'1.5\""
    assert units.format_length(11.999 * IN, "ft-in", 2) == "1'0.00\""


def test_no_negative_zero():
    assert units.format_length(-0.0001, "m", 2) == "0.00 m"
    assert units.format_length(-0.0001 * IN, "in-frac", 2) == '0"'
    assert units.format_length(-0.0001 * IN, "ft-in-frac", 2) == "0'0\""
    assert units.format_length(-0.0001 * IN, "ft-in", 1) == "0'0.0\""
    assert units.format_length(-0.5, "m", 2) == "-0.50 m"


def test_limits():
    assert units.format_length(0, "mm", 0) == "0 mm"
    assert units.format_length(1e-6, "mm", 3) == "0.001 mm"         # 0.001 mm
    assert units.format_length(10000, "km", 1) == "10.0 km"
    assert units.format_length(10000, "m", 0) == "10000 m"
    assert units.format_length(math.nan, "m", 2) == "—"
    assert units.format_length(math.inf, "ft-in-frac", 2) == "—"   # no crash
    assert units.format_length(1.0, "yd", 2) == "1.09 yd"


def test_area_volume_angle():
    assert units.format_area(12.5, "m2", 2) == "12.50 m²"
    assert units.format_area(20000, "ha", 1) == "2.0 ha"
    assert units.format_area(FT ** 2 * 43560, "acre", 2) == "1.00 acre"
    assert units.format_volume(0.003, "l", 1) == "3.0 L"
    assert units.format_volume(1, "m3", 0) == "1 m³"
    assert units.format_angle(math.pi / 4) == "45.0°"
    assert units.format_angle(1, "rad", 3) == "1.000 rad"
    assert units.format_value(1.2, "cm", 0, symbol=False) == "120"


def test_document_volume_follows_its_length(doc):
    doc("mm", 0)
    assert units.fmt_volume(1e-3) == "1000.000 cm³"
    doc("ft", 1)
    assert units.fmt_volume(FT ** 3) == "1.000 ft³"


def test_display_steps(doc):
    doc("mm", 0)
    assert units.display_step() == pytest.approx(0.001)
    doc("m", 2)
    assert units.display_step() == pytest.approx(0.01)
    assert units.display_step("in-frac", 2) == pytest.approx(IN / 16)


# ---- the round trip, over generated values ---------------------------------

_FORMS = [("m", 3), ("cm", 1), ("mm", 0), ("km", 4), ("in", 3), ("ft", 4),
          ("ft-in", 3), ("in-frac", 4), ("ft-in-frac", 4), ("yd", 4)]


def _shown_step(unit, decimals):
    if unit in ("in-frac", "ft-in-frac"):
        return IN / units._FRAC_DENOMS[decimals]
    return units.display_step(unit, decimals)


@pytest.mark.parametrize("unit, decimals", _FORMS)
def test_parse_of_format_returns_the_value(doc, unit, decimals):
    """parse(format(v)) == v within half a shown step, for thousands of
    values from a tenth of a millimetre to ten kilometres, both signs."""
    doc(unit, decimals)
    rng = random.Random(f"{unit}:{decimals}")
    half = _shown_step(unit, decimals) / 2
    for _ in range(2000):
        v = 10 ** rng.uniform(-4, 4) * rng.choice((1, -1))
        text = units.format_length(v, unit, decimals)
        r = units.parse(text)
        assert r.ok, (v, text, r.error)
        assert abs(r.value - v) <= half + 1e-9 * max(1.0, abs(v)), (v, text)


@pytest.mark.parametrize("unit", ["mm2", "cm2", "m2", "ha", "ft2", "acre"])
def test_area_round_trip(unit):
    rng = random.Random(unit)
    for _ in range(500):
        v = 10 ** rng.uniform(-3, 5)
        if v / units.UNITS[unit].factor > units.MAX_TYPED:
            continue                     # no field takes a number that big
        text = units.format_area(v, unit, 6)
        r = units.parse(text, "area")
        assert r.ok and r.value == pytest.approx(v, rel=1e-5, abs=units.UNITS[unit].factor * 1e-6)


def test_formatting_never_touches_the_value(doc):
    """Showing to fewer decimals is for the eye: the stored value is the
    same float before and after, whatever the unit."""
    scene = doc("m")
    rng = random.Random(7)
    values = [rng.uniform(-50, 50) for _ in range(200)]
    before = list(values)
    for unit, decimals in _FORMS:
        scene.units = {"length": unit, "precision": decimals}
        for v in values:
            units.fmt_len(v)
            units.format_length(v, unit, 0)
    assert values == before


def test_comma_and_point_mean_the_same(doc):
    doc("cm", 1)
    rng = random.Random(3)
    for _ in range(500):
        whole, frac = rng.randint(0, 9999), rng.randint(0, 99)
        a = units.parse(f"{whole},{frac:02d}")
        b = units.parse(f"{whole}.{frac:02d}")
        assert a.ok and a.value == b.value
