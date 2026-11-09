# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #287: in a millimetre document the 3D Text dialog asked for the
height and the extrusion in metres. Its fields now show and read the
document's units (``views.length_field.LengthSpinBox``) while the values
behind them stay metres — and the value box takes the feet-and-inches
forms people write (``5' 3 1/2"``)."""
from __future__ import annotations

import random

import pytest
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QApplication, QDialog, QWidget

if QApplication.instance() is None:
    QApplication([])

from core import units  # noqa: E402
from core.scene import Scene  # noqa: E402
from views.length_field import LengthSpinBox  # noqa: E402
from views.viewport import Viewport  # noqa: E402

IN = 0.0254
FT = 0.3048


@pytest.fixture
def doc():
    scene = Scene()
    units.bind_scene(scene)

    def set_units(length, precision=2):
        scene.units = {"length": length, "precision": precision}
    yield set_units
    units.bind_scene(None)


def test_the_field_shows_the_documents_unit(doc):
    doc("mm", 0)
    box = LengthSpinBox(minimum=0.001, maximum=1000.0)
    box.setValue(0.25)
    assert box.text() == "250 mm"
    assert box.value() == pytest.approx(0.25)         # metres behind it
    doc("m", 2)
    box = LengthSpinBox(minimum=0.001, maximum=1000.0)
    box.setValue(0.25)
    assert box.text() == "0.250 m"                    # to the millimetre
    doc("ft-in-frac", 2)
    box = LengthSpinBox(minimum=0.0, maximum=1000.0)
    box.setValue(FT + 6.5 * IN)
    assert box.text() == "1'6 1/2\""


@pytest.mark.parametrize("typed, metres", [
    ("20", 0.020), ("2,5 cm", 0.025), ("1\"", IN), ("0.1m", 0.1),
    ("3/4\"", 0.75 * IN), ("1m 20", 1.2),
])
def test_the_field_reads_what_is_typed(doc, typed, metres):
    doc("mm", 0)
    box = LengthSpinBox(minimum=0.0, maximum=1000.0)
    assert box.validate(typed, 0)[0] == QValidator.Acceptable
    assert box.valueFromText(typed) == pytest.approx(metres)


def test_the_field_refuses_what_is_not_a_length(doc):
    doc("mm", 0)
    box = LengthSpinBox(minimum=0.001, maximum=1.0)
    box.setValue(0.25)
    for bad in ("5 m²", "abc", "2 l"):
        assert box.validate(bad, 0)[0] == QValidator.Intermediate
        assert box.valueFromText(bad) == pytest.approx(0.25)   # unchanged
    box.lineEdit().setText("5 m²")
    assert box.error_text() == "Expected a length"
    box.lineEdit().setText("2 m")                    # above the 1 m ceiling
    assert box.validate("2 m", 0)[0] == QValidator.Intermediate
    assert box.error_text().startswith("Out of range")
    box.lineEdit().setText("300")
    assert box.error_text() == ""


def test_arrows_step_one_shown_unit(doc):
    doc("mm", 0)
    box = LengthSpinBox(minimum=0.0, maximum=1000.0)
    box.setValue(0.25)
    box.stepBy(1)
    assert box.value() == pytest.approx(0.251)
    assert box.text() == "251 mm"


def test_values_survive_the_field_unrounded_to_the_micron(doc):
    """Generated values go in and come out of the field unchanged (Qt keeps
    9 decimals of metres) whatever the shown precision."""
    doc("cm", 0)
    box = LengthSpinBox(minimum=0.0, maximum=1000.0)
    rng = random.Random(287)
    for _ in range(300):
        v = round(rng.uniform(0, 900), 6)
        box.setValue(v)
        assert box.value() == pytest.approx(v, abs=1e-9)


def _run_text3d_dialog(monkeypatch, params, typed):
    """Open the real 3D Text dialog, type into its two length fields, press
    OK; returns (what the fields showed, the parameters it returned)."""
    from views.main_window import MainWindow
    shown = {}

    def fake_exec(dlg):
        boxes = dlg.findChildren(LengthSpinBox)
        assert len(boxes) == 2
        shown["height"], shown["depth"] = boxes[0].text(), boxes[1].text()
        for box, text in zip(boxes, typed):
            if text is not None:
                box.lineEdit().setText(text)
                box.interpretText()
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    host = QWidget()
    try:
        out = MainWindow._text3d_dialog(host, params)
    finally:
        host.deleteLater()
    return shown, out


def test_text3d_dialog_in_millimetres(doc, monkeypatch):
    doc("mm", 0)
    shown, out = _run_text3d_dialog(
        monkeypatch, {"text": "IngeTrazo", "height": 0.25, "thickness": 0.05},
        ("20", "3"))
    assert shown == {"height": "250 mm", "depth": "50 mm"}
    assert out["height"] == pytest.approx(0.020)       # stored in metres
    assert out["thickness"] == pytest.approx(0.003)


def test_text3d_dialog_in_metres_is_as_before(doc, monkeypatch):
    doc("m", 2)
    shown, out = _run_text3d_dialog(
        monkeypatch, {"text": "IngeTrazo", "height": 0.25, "thickness": 0.05},
        (None, "20cm"))
    assert shown == {"height": "0.250 m", "depth": "0.050 m"}
    assert out["height"] == pytest.approx(0.25)
    assert out["thickness"] == pytest.approx(0.20)


def test_text3d_dialog_in_inches(doc, monkeypatch):
    doc("in-frac", 2)
    shown, out = _run_text3d_dialog(
        monkeypatch, {"text": "A", "height": 2 * IN, "thickness": 0.25 * IN},
        ("1 1/2", None))
    assert shown == {"height": '2"', "depth": '1/4"'}
    assert out["height"] == pytest.approx(1.5 * IN)


# ---- the value box ----------------------------------------------------------

def test_the_value_box_takes_feet_and_inches_with_spaces(doc):
    doc("m")
    parse = Viewport._parse_value_buffer
    assert parse('5\' 3 1/2"') == pytest.approx(5 * FT + 3.5 * IN)
    assert parse('5\' 3"') == pytest.approx(5 * FT + 3 * IN)
    assert parse('3\'-6 1/2"') == pytest.approx(3 * FT + 6.5 * IN)
    w, h = parse('5\';3"')                          # a 5 ft × 3 in rectangle
    assert w == pytest.approx(5 * FT) and h == pytest.approx(3 * IN)
    assert parse("1m20") == pytest.approx(1.2)
    assert parse("1 2") == (1.0, 2.0)               # still two plain fields
    assert parse("2m 3") == (2.0, 3.0)
    assert parse("5 m²") is None


# ---- #189: what a Mac keyboard types -------------------------------------------

class _Key:
    def __init__(self, text):
        self._t = text

    def text(self):
        return self._t

    def key(self):
        return 0

    def modifiers(self):
        from PySide6.QtCore import Qt
        return Qt.NoModifier


def _typed(chars):
    """The value box's buffer after typing ``chars`` one key at a time."""
    vp = Viewport.__new__(Viewport)
    vp._value_buffer = ""
    vp.active_tool = object()
    vp.valueBufferChanged = type("S", (), {"emit": lambda self, t: None})()
    vp.update = lambda: None
    for ch in chars:
        vp._handle_value_key(_Key(ch))
    return vp._value_buffer


def test_fraction_characters_and_smart_quotes_are_typed(doc):
    """«1 ⅜", 1 3/16”» on a Mac in fractional inches: ⅜ and ” were dropped,
    and the comma read as a decimal joined both values (#189)."""
    doc("in-frac", 2)
    buf = _typed('1⅜”, 1 3/16”')
    assert buf == '1 3/8", 1 3/16"'
    w, h = Viewport._parse_value_buffer(buf, comma_lists=True)
    assert w == pytest.approx(1.375 * IN) and h == pytest.approx(1.1875 * IN)
    assert _typed("⅜”") == '3/8"'
    assert _typed("5’ 3½”") == "5' 3 1/2\""


@pytest.mark.parametrize("typed, inches", [
    ('1 ⅜", 1 3/16”', (1.375, 1.1875)),
    ("48, 96", (48, 96)),                     # comma and space: two values
    ('1 3/8"; 1 3/16"', (1.375, 1.1875)),
])
def test_rectangle_values_with_comma_and_space(doc, typed, inches):
    doc("in-frac", 2)
    for comma_lists in (False, True):
        got = Viewport._parse_value_buffer(typed, comma_lists=comma_lists)
        assert got == pytest.approx(tuple(v * IN for v in inches))


def test_a_decimal_comma_still_reads_as_one(doc):
    doc("m", 2)
    assert Viewport._parse_value_buffer("2,5") == pytest.approx(2.5)
    assert Viewport._parse_value_buffer("1,5;2,5") == pytest.approx((1.5, 2.5))
    assert units.parse("1⅜”", unit="in-frac").value == pytest.approx(1.375 * IN)
