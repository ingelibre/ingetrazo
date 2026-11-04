# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Levels example extension shows and reads heights in the document's
units: a 10' level in a feet-inches document read «+3.05 m», and its height
could only be typed in metres."""
from __future__ import annotations

import importlib.util
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import units  # noqa: E402

_app = QApplication.instance() or QApplication([])

EXAMPLE = os.path.join(os.path.dirname(__file__), os.pardir, "examples",
                       "extensions", "niveles.py")


def _niveles():
    spec = importlib.util.spec_from_file_location("niveles_under_test", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Scene:
    def __init__(self, length, precision):
        self.units = {"length": length, "precision": precision}


@pytest.fixture
def document_units():
    """Bind a scene with the given units for the test, then unbind."""
    def bind(length, precision=2):
        units.bind_scene(_Scene(length, precision))
    yield bind
    units.bind_scene(None)


def test_metres_keep_the_level_mark_they_always_had(document_units):
    document_units("m", 2)
    niveles = _niveles()
    assert niveles._fmt(3.0) == "+3.00"
    assert niveles._fmt(0.0) == "±0.00"
    assert niveles._fmt(-0.45) == "-0.45"
    assert niveles._fmt_listed(3.0) == "+3.00 m"


def test_feet_and_inches_read_as_feet_and_inches(document_units):
    document_units("ft-in", 0)
    niveles = _niveles()
    ten_feet = 10 * units.FT_M
    assert niveles._fmt(ten_feet) == units.format_signed_level(
        ten_feet, "ft-in", 0)
    assert "'" in niveles._fmt(ten_feet) and "m" not in niveles._fmt(ten_feet)
    assert niveles._fmt_listed(ten_feet) == niveles._fmt(ten_feet)


def test_the_height_is_typed_in_the_document_units(document_units):
    document_units("ft-in-frac", 2)
    niveles = _niveles()
    dlg = niveles._LevelDialog(None, "Level", "Level 2", 10 * units.FT_M)
    try:
        assert "'" in dlg.z.text()
        assert dlg.z.value() == pytest.approx(10 * units.FT_M)
        dlg.z.lineEdit().setText("9'-1 1/8\"")
        dlg.z.interpretText()
        assert dlg.z.value() == pytest.approx(
            9 * units.FT_M + 1.125 * units.IN_M, abs=1e-6)
    finally:
        dlg.deleteLater()


def test_a_new_level_repeats_the_last_floor_to_floor():
    niveles = _niveles()
    ten = 10 * units.FT_M
    assert niveles._next_height([]) == 0.0
    assert niveles._next_height([{"z": 0.0}]) == pytest.approx(
        niveles.DEFAULT_STORY)
    assert niveles._next_height([{"z": 0.0}, {"z": ten}]) == pytest.approx(
        2 * ten)
    # Only the two highest count, whatever order they are stored in.
    assert niveles._next_height(
        [{"z": 2 * ten}, {"z": -1.0}, {"z": 2 * ten - 3.0}]) == pytest.approx(
        2 * ten + 3.0)
