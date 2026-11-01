# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Dimensions without their unit symbol: «1.30», not «1.30 m» (#374, #637).

Many drawings state the unit once, in the title block or a general note,
and write every dimension as a bare number. A «Show unit» option, on by
default, in the model's dimension style and in each sheet cota. Feet and
inches together keep their marks: 5'3" without them reads «5 3». Documents
and sheets saved before the option open with the unit, as they were."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core.composition import Composicion, CotaItem, CotaRadialItem  # noqa: E402
from core.units import format_length  # noqa: E402


@pytest.mark.parametrize("units, shown, bare", [
    ("m", "1.60 m", "1.60"),
    ("cm", "160.00 cm", "160.00"),
    ("mm", "1600.00 mm", "1600.00"),
    ("in", '62.99"', "62.99"),
    ("ft", "5.25'", "5.25"),
    ("in-frac", '63"', "63"),
])
def test_format_length_with_and_without_the_unit(units, shown, bare):
    assert format_length(1.6, units, 2) == shown
    assert format_length(1.6, units, 2, show_unit=False) == bare


@pytest.mark.parametrize("units", ["ft-in", "ft-in-frac"])
def test_feet_and_inches_keep_their_marks(units):
    assert (format_length(1.6, units, 2, show_unit=False)
            == format_length(1.6, units, 2))


def test_not_a_number_stays_a_dash():
    assert format_length(float("nan"), "m", 2, show_unit=False) == "—"


def test_model_dimension_style_hides_the_unit():
    from core.scene import Scene
    from views.viewport import Viewport
    style = Scene().dimension_style
    assert style["show_unit"] is True                 # new documents: as before
    assert Viewport._format_dim_value(1.3, style) == "1.30 m"
    style["show_unit"] = False
    assert Viewport._format_dim_value(1.3, style) == "1.30"
    style["units"] = "mm"
    style["decimals"] = 0
    assert Viewport._format_dim_value(1.3, style) == "1300"


def test_style_without_the_key_shows_the_unit():
    from views.viewport import Viewport
    assert Viewport._format_dim_value(1.3, {"units": "m", "decimals": 2}) \
        == "1.30 m"


def _cota(**kw):
    # 13 mm on paper at 1:100 = 1.30 m
    return CotaItem(dx_mm=13.0, dy_mm=0.0, scale_n=100.0, **kw)


def test_sheet_cota_without_unit():
    assert _cota().label() == "1.30 m"
    assert _cota(show_unit=False).label() == "1.30"
    assert _cota(show_unit=False, units="mm", decimals=0).label() == "1300"
    assert _cota(show_unit=False, text="L = <>").label() == "L = 1.30"


def test_long_sheet_cota_without_unit_stays_in_its_own_unit():
    """Over 1 km a cota in metres reads «1.234 km»; without its symbol it
    must not become «1.234», which would read as metres."""
    far = CotaItem(dx_mm=12.34, scale_n=100000.0)
    assert far.label() == "1.234 km"
    far.show_unit = False
    assert far.label() == "1234.00"


def test_radial_cota_keeps_its_symbol_without_the_unit():
    r = CotaRadialItem(radius_mm=13.0, scale_n=100.0)
    assert r.label().endswith("1.30 m") and r.label() != "1.30 m"
    r.show_unit = False
    assert r.label() == r.symbol() + "1.30"
    d = CotaRadialItem(radius_mm=6.5, scale_n=100.0, kind="diameter",
                       show_unit=False)
    assert d.label() == d.symbol() + "1.30"


def test_sheet_keeps_the_choice_and_old_sheets_show_the_unit():
    c = Composicion()
    c.cotas.append(_cota(show_unit=False))
    c.cotas_rad.append(CotaRadialItem(radius_mm=13.0, show_unit=False))
    d = c.to_dict()
    back = Composicion.from_dict(d)
    assert back.cotas[0].show_unit is False
    assert back.cotas_rad[0].show_unit is False
    for item in d["cotas"] + d["cotas_rad"]:
        del item["show_unit"]                       # a sheet from before
    old = Composicion.from_dict(d)
    assert old.cotas[0].show_unit is True
    assert old.cotas_rad[0].show_unit is True


def test_document_keeps_the_choice_and_old_documents_show_the_unit(tmp_path):
    import json

    from core.scene import Scene
    from formats import igz
    scene = Scene()
    scene.dimension_style["show_unit"] = False
    path = tmp_path / "sin-unidad.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.dimension_style["show_unit"] is False

    # The same file with the key taken out: a document from before. A
    # small document is plain JSON text.
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["scene"]["dimension_style"].pop("show_unit") is False
    old = tmp_path / "antiguo.igz"
    old.write_text(json.dumps(payload), encoding="utf-8")
    again = Scene()
    igz.load_into(again, old)
    assert again.dimension_style["show_unit"] is True


def test_dimension_style_panel_switches_it():
    from core.scene import Scene
    from views.tray import DimensionStylePanel
    scene = Scene()
    vp = SimpleNamespace(scene=scene, update=lambda: None)
    panel = DimensionStylePanel(SimpleNamespace(viewport=vp))
    assert panel._show_unit.isChecked()
    v0 = scene.version
    panel._show_unit.setChecked(False)
    assert scene.dimension_style["show_unit"] is False
    assert scene.version > v0                       # the viewport redraws
    panel._show_unit.setChecked(True)
    assert scene.dimension_style["show_unit"] is True


def test_new_sheet_cotas_follow_the_document():
    from core.scene import Scene
    from views.composer import ComposerWindow
    scene = Scene()
    stub = SimpleNamespace(_scene=lambda: scene)
    assert ComposerWindow._document_shows_unit(stub) is True
    scene.dimension_style["show_unit"] = False
    assert ComposerWindow._document_shows_unit(stub) is False
