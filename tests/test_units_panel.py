# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The units panel (Preferences ▸ Units): profiles, length, area and
volume, angle, decimal separator and a live preview — saved in the
document, read by every readout, and never touching a stored value."""
from __future__ import annotations

import math
import random

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication([])

from core import units  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats import igz  # noqa: E402
from views.units_panel import UnitsPanel  # noqa: E402

FT = 0.3048
IN = 0.0254


@pytest.fixture
def scene():
    s = Scene()
    units.bind_scene(s)
    yield s
    units.bind_scene(None)


# ---- settings ----------------------------------------------------------------

def test_absent_settings_read_as_before(scene):
    """A document that never opened the panel (every .igz written before
    it) shows exactly what it always did."""
    assert units.model_units_of(scene) == {"length": "m", "precision": 2}
    assert units.fmt_area(4.0) == "4.00 m²"
    assert units.fmt_angle_deg(45, signed=True) == "+45.0°"
    assert units.fmt_volume(1.0) == "1.000 m³"           # three decimals, as ever


def test_unknown_or_broken_settings_are_dropped():
    raw = {"length": "mm", "precision": 0, "area": "furlong2", "volume": "m2",
           "angle": "turns", "angle_precision": 9, "decimal": ";",
           "area_precision": True}
    assert units.model_units_of({"units": raw}) == {"length": "mm", "precision": 0}


def test_defaults_are_not_written():
    raw = {"length": "m", "precision": 2, "area": "auto", "angle": "deg",
           "angle_precision": 1, "decimal": "."}
    assert units.model_units_of({"units": raw}) == {"length": "m", "precision": 2}


def test_area_and_volume_can_differ_from_the_length(scene):
    """Widths in centimetres, areas in square metres — the usual pair in
    architecture."""
    scene.units = {"length": "cm", "precision": 1, "area": "m2",
                   "area_precision": 2, "volume": "l", "volume_precision": 0}
    assert units.fmt_len(1.2345) == "123.5 cm"
    assert units.fmt_area(12.3456) == "12.35 m²"
    assert units.fmt_volume(0.25) == "250 L"
    scene.units = {"length": "cm", "precision": 1}
    assert units.fmt_area(1.0) == "10000.0 cm²"           # follows the length


def test_angle_unit_and_precision(scene):
    scene.units = {"length": "m", "precision": 2, "angle": "rad",
                   "angle_precision": 3}
    assert units.fmt_angle_deg(90, signed=True) == "+1.571 rad"
    assert units.fmt_angle_deg(-90, signed=True) == "-1.571 rad"
    scene.units = {"length": "m", "precision": 2, "angle_precision": 0}
    assert units.fmt_angle_deg(44.6) == "45°"


def test_decimal_comma_everywhere(scene):
    scene.units = {"length": "m", "precision": 2, "decimal": ","}
    assert units.fmt_len(1.2345) == "1,23 m"
    assert units.fmt_pair(3.0, 2.5) == "3,00 × 2,50 m"
    assert units.fmt_area(4.5) == "4,50 m²"
    assert units.fmt_angle_deg(22.5, signed=True) == "+22,5°"
    assert units.fmt_len_fine(0.0043) == "0,004 m"
    assert units.fmt_triple(1, 2, 3) == "1,00 × 2,00 × 3,00 m"
    # ...and what is shown reads back
    assert units.parse(units.fmt_len(1.2345)).value == pytest.approx(1.23)


def test_profiles():
    assert units.profile_of({"length": "m", "precision": 2}) == "metric"
    assert units.profile_of({"length": "mm", "precision": 0,
                             "decimal": ","}) == "millimetric"
    assert units.profile_of({"length": "ft-in-frac", "precision": 2}) == "imperial"
    assert units.profile_of({"length": "cm", "precision": 1}) == "custom"
    assert units.profile_of({"length": "m", "precision": 2,
                             "area": "ha"}) == "custom"
    out = units.with_profile({"length": "cm", "precision": 1, "area": "ha",
                              "decimal": ","}, "imperial")
    assert out == {"length": "ft-in-frac", "precision": 2, "decimal": ","}


# ---- saved with the document ---------------------------------------------------

def test_saved_and_reopened(tmp_path):
    s = Scene()
    s.mesh.add_edge(QVector3D(0, 0, 0), QVector3D(1.2345, 0, 0))
    s.units = {"length": "cm", "precision": 1, "area": "m2", "area_precision": 2,
               "volume": "l", "volume_precision": 0, "angle": "rad",
               "angle_precision": 3, "decimal": ","}
    path = tmp_path / "unidades.igz"
    igz.save_scene(s, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.units == s.units
    old = tmp_path / "antiguo.igz"            # a file from before the panel
    s.units = {"length": "m", "precision": 2}
    igz.save_scene(s, old)
    back = Scene()
    igz.load_into(back, old)
    assert back.units == {"length": "m", "precision": 2}


def test_the_geometry_never_moves_when_the_units_change(tmp_path):
    """Generated points; every profile and setting in turn; the stored
    coordinates are the same floats before and after, and so is the file's
    geometry."""
    rng = random.Random(33)
    s = Scene()
    for _ in range(50):
        a = QVector3D(*(rng.uniform(-20, 20) for _ in range(3)))
        b = QVector3D(*(rng.uniform(-20, 20) for _ in range(3)))
        s.mesh.add_edge(a, b)
    before = [(v.position.x(), v.position.y(), v.position.z())
              for v in s.mesh.vertices]
    for name in units.PROFILES:
        units.apply_units(s, units.with_profile(s.units, name))
    units.apply_units(s, {"length": "cm", "precision": 0, "area": "acre",
                          "decimal": ","})
    after = [(v.position.x(), v.position.y(), v.position.z())
             for v in s.mesh.vertices]
    assert after == before


# ---- the panel -------------------------------------------------------------------

def test_panel_shows_and_returns_the_settings():
    s = {"length": "cm", "precision": 1, "area": "m2", "area_precision": 2,
         "angle": "rad", "angle_precision": 3, "decimal": ","}
    panel = UnitsPanel(s)
    assert panel.settings() == s
    assert panel.profile.currentData() == "custom"


def test_picking_a_profile_fills_the_blocks():
    panel = UnitsPanel({"length": "cm", "precision": 1, "area": "ha",
                        "decimal": ","})
    panel.profile.setCurrentIndex(panel.profile.findData("imperial"))
    assert panel.settings() == {"length": "ft-in-frac", "precision": 2,
                                "decimal": ","}
    assert panel.length.currentData() == "ft-in-frac"
    assert panel.area.currentData() == "auto"
    assert panel.fraction.currentText() == '1/16"'


def test_editing_a_block_makes_it_custom():
    panel = UnitsPanel({"length": "m", "precision": 2})
    assert panel.profile.currentData() == "metric"
    panel.area.setCurrentIndex(panel.area.findData("ha"))
    assert panel.profile.currentData() == "custom"
    panel.area.setCurrentIndex(panel.area.findData("auto"))
    assert panel.profile.currentData() == "metric"


def test_fractional_lengths_pick_a_fraction():
    panel = UnitsPanel({"length": "m", "precision": 2})
    panel.length.setCurrentIndex(panel.length.findData("in-frac"))
    assert panel._precision.currentWidget() is panel.fraction
    panel.fraction.setCurrentIndex(4)
    assert panel.settings()["precision"] == 4          # 1/64"
    panel.length.setCurrentIndex(panel.length.findData("mm"))
    assert panel._precision.currentWidget() is panel.decimals


def test_follow_the_length_disables_its_precision():
    panel = UnitsPanel({"length": "m", "precision": 3})
    assert not panel.area_decimals.isEnabled()
    assert panel.area_decimals.value() == 3
    panel.area.setCurrentIndex(panel.area.findData("m2"))
    assert panel.area_decimals.isEnabled()


def test_live_preview():
    panel = UnitsPanel({"length": "cm", "precision": 1})
    assert "1.2345 m → 123.5 cm" in panel.preview.text()
    panel.decimal.setCurrentIndex(panel.decimal.findData(","))
    assert "1,2345 m → 123,5 cm" in panel.preview.text()
    panel.length.setCurrentIndex(panel.length.findData("ft-in-frac"))
    assert panel.fraction.currentText() == '1/4"'     # precision 1 carried
    panel.fraction.setCurrentIndex(2)                 # 1/16"
    # 48.602": 0.602 × 16 = 9.6 sixteenths, the nearest is 10/16 = 5/8
    assert '→ 4\'5/8"' in panel.preview.text()
    panel.angle.setCurrentIndex(panel.angle.findData("deg"))
    assert "rad → 70,7°" in panel.preview.text()


def test_preferences_dialog_applies_the_panel(scene, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QWidget

    import views.preferences_dialog as prefs_mod
    path = tmp_path / "prefs.ini"
    monkeypatch.setattr(prefs_mod, "QSettings",
                        lambda: QSettings(str(path), QSettings.IniFormat))

    class _Vp:
        def __init__(self, s):
            self.scene = s

        def update(self):
            pass

        def __getattr__(self, name):          # anything else: harmless
            return lambda *a, **k: None

    win = QWidget()
    win.viewport = _Vp(scene)
    dlg = prefs_mod.PreferencesDialog(win)
    panel = dlg._units_panel
    panel.profile.setCurrentIndex(panel.profile.findData("millimetric"))
    panel.volume.setCurrentIndex(panel.volume.findData("cm3"))
    dlg._units_for_new.setChecked(False)
    dlg.accept()
    assert scene.units == {"length": "mm", "precision": 0, "volume": "cm3"}
    assert units.fmt_len(0.25) == "250 mm"
    assert scene.dimension_style["units"] == "mm"
    assert math.isclose(units.parse("20").value, 0.020)


def test_by_the_length_says_the_unit_it_gives():
    panel = UnitsPanel({"length": "m", "precision": 2})
    assert panel.area.itemText(0) == "By the length (m²)"
    assert panel.volume.itemText(0) == "By the length (m³)"
    panel.length.setCurrentIndex(panel.length.findData("mm"))
    assert panel.area.itemText(0) == "By the length (mm²)"
    assert panel.volume.itemText(0) == "By the length (cm³)"
    panel.length.setCurrentIndex(panel.length.findData("ft-in"))
    assert panel.area.itemText(0) == "By the length (ft²)"


def test_decimals_read_as_words():
    panel = UnitsPanel({"length": "m", "precision": 2})
    assert panel.decimals.text() == "2 decimals"
    panel.angle_decimals.setValue(1)
    assert panel.angle_decimals.text() == "1 decimal"
