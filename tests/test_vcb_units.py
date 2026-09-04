# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Typed lengths in inches and feet next to metres (Marco, 2026-09-03: the
timber and the pipes come in inches, the spans in metres)."""
from __future__ import annotations

import pytest

from views.viewport import Viewport, _parse_length_field

IN = 0.0254
FT = 0.3048


@pytest.mark.parametrize("text, metres", [
    ("2", 2.0), ("30cm", 0.3), ("1500mm", 1.5), ("2m", 2.0),
    ('2"', 2 * IN), ("2in", 2 * IN), ("2.5in", 2.5 * IN),
    ("1'", FT), ("1ft", FT), ("1.5ft", 1.5 * FT),
    ('1\'6"', FT + 6 * IN), ("1'6", FT + 6 * IN), ('0\'6"', 6 * IN),
    ('3/4"', 0.75 * IN), ('1/2in', 0.5 * IN), ('1\'3/4"', FT + 0.75 * IN),
    ('-2"', -2 * IN), ("-1'", -FT), (".5in", 0.5 * IN),
])
def test_length_fields_in_every_unit(text, metres):
    assert abs(_parse_length_field(text) - metres) < 1e-9


def test_nonsense_fields_are_rejected():
    for bad in ("", "in", '"', "2x", "3/0\"", "1''", "abc", "2mm3"):
        assert _parse_length_field(bad) is None


def test_rectangle_and_delta_mix_units():
    parse = Viewport._parse_value_buffer
    w, h = parse('2";4"')                          # a 2×4 in inches
    assert abs(w - 2 * IN) < 1e-9 and abs(h - 4 * IN) < 1e-9
    dx, dy, dz = parse("3,2;1'6\";10cm")           # metres, feet-inches, cm
    assert (abs(dx - 3.2) < 1e-9 and abs(dy - (FT + 6 * IN)) < 1e-9
            and abs(dz - 0.1) < 1e-9)
    assert abs(parse('3/4"') - 0.75 * IN) < 1e-9
    assert parse("2r") == ("radius", 2.0)          # untouched
    assert parse("3:12")[0] == "ratio"


class _Ev:
    def __init__(self, text, key=0):
        self._t, self._k = text, key

    def text(self):
        return self._t

    def key(self):
        return self._k


def test_the_buffer_takes_imperial_marks_only_after_a_digit():
    vp = Viewport.__new__(Viewport)
    vp._value_buffer = ""
    vp.active_tool = object()
    emitted = []
    vp.valueBufferChanged = type("S", (), {"emit": lambda self, t: emitted.append(t)})()
    vp.update = lambda: None
    # a bare " or / or i is not input (I / F stay tool shortcuts)
    assert vp._handle_value_key(_Ev('"')) is True and vp._value_buffer == ""
    assert vp._handle_value_key(_Ev("i")) is False
    assert vp._handle_value_key(_Ev("f")) is False
    for ch in '2"':
        vp._handle_value_key(_Ev(ch))
    assert vp._value_buffer == '2"'
    vp._value_buffer = ""
    for ch in "1'6\"":
        vp._handle_value_key(_Ev(ch))
    assert vp._value_buffer == "1'6\""
    vp._value_buffer = ""
    for ch in "3/4in":
        vp._handle_value_key(_Ev(ch))
    assert vp._value_buffer == "3/4in"


def test_dimension_labels_can_read_in_inches_and_feet():
    fmt = Viewport._format_dim_value
    assert fmt(2 * IN, {"units": "in", "decimals": 2}) == '2.00"'
    assert fmt(FT + 6 * IN, {"units": "ft-in", "decimals": 1}) == "1'6.0\""
    assert fmt(2 * FT, {"units": "ft", "decimals": 2}) == "2.00'"
    assert fmt(1.5, {"units": "m", "decimals": 2}) == "1.50 m"


def test_mixed_numbers_the_way_sketchup_writes_them():
    parse = Viewport._parse_value_buffer
    assert abs(parse('1 1/2"') - 1.5 * IN) < 1e-9          # space form
    assert abs(parse('1-1/2"') - 1.5 * IN) < 1e-9          # hyphen form
    assert abs(parse("2 3/4in") - 2.75 * IN) < 1e-9
    assert abs(parse('-1 1/2"') + 1.5 * IN) < 1e-9
    w, h = parse('1 1/2";3 1/2"')                          # a real 2×4
    assert abs(w - 1.5 * IN) < 1e-9 and abs(h - 3.5 * IN) < 1e-9
    assert abs(parse("1'6 1/2\"") - (FT + 6.5 * IN)) < 1e-9
    assert abs(parse("1'6-1/2\"") - (FT + 6.5 * IN)) < 1e-9
    dx, dy = parse("2 1/2\";3")                            # then metres
    assert abs(dx - 2.5 * IN) < 1e-9 and abs(dy - 3.0) < 1e-9
    assert parse("1 2") == (1.0, 2.0)                      # two plain fields
    assert _parse_length_field("1-2") is None


def test_fractional_inches_read_like_a_carpenter_writes_them():
    from core.units import format_length
    assert format_length(1.5 * IN, "in-frac", 2) == '1 1/2"'
    assert format_length(0.75 * IN, "in-frac", 2) == '3/4"'
    assert format_length(6 * IN, "in-frac", 2) == '6"'
    assert format_length(FT + 6.5 * IN, "ft-in-frac", 2) == "1'6 1/2\""
    assert format_length(2 * FT, "ft-in-frac", 2) == "2'0\""
    assert format_length(11.99 * IN, "ft-in-frac", 0) == "1'0\""   # rounds up
    assert format_length(1.03 * IN, "in-frac", 1) == '1"'          # 1/4 grid
    assert format_length(1.03 * IN, "in-frac", 4) == '1 1/32"'     # 1/64 grid
    assert format_length(-1.5 * IN, "in-frac", 2) == '-1 1/2"'
    assert format_length(1.5, "m", 2) == "1.50 m"
    assert format_length(1.5, "mm", 0) == "1500 mm"


def test_sheet_cotas_take_units():
    from core.composition import CotaItem, Composicion
    c = CotaItem(x_mm=10.0, y_mm=10.0, dx_mm=38.1, scale_n=1.0, units="in-frac",
                 decimals=2)                                    # 38.1 mm = 1.5"
    assert c.auto_label() == '1 1/2"'
    c.units = "ft-in"
    assert c.auto_label() == "0'1.50\""
    c.units = "m"
    assert c.auto_label() == "0.04 m"
    back = Composicion.from_dict({"cotas": [{"x_mm": 1.0, "y_mm": 2.0,
                                             "dx_mm": 10.0, "decimals": 1}]})
    assert back.cotas[0].units == "m"                          # old documents
