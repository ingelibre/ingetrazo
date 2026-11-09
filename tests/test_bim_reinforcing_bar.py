# SPDX-License-Identifier: GPL-3.0-or-later
"""IfcReinforcingBar among the BIM classes (#495, @chakkreetiya).

A straight bar gets its length, its nominal diameter (the round section
that holds its volume) and its weight in steel -- reinforcement is billed by
the kilo -- and the IFC carries them in the entity and in
Qto_ReinforcingElementBaseQuantities."""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D as V

from core.bim import (IFC_CLASSES, STEEL_DENSITY, class_quantities, tag_group)
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from formats.ifc import save_ifc

D, L = 0.016, 6.0          # a Ø16 bar, 6 m long


def _bar(n=24):
    m = Mesh()
    r = D / 2
    ring = [(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n))
            for k in range(n)]
    m.add_face([V(0, y, z) for y, z in reversed(ring)])
    m.add_face([V(L, y, z) for y, z in ring])
    for k in range(n):
        (y0, z0), (y1, z1) = ring[k], ring[(k + 1) % n]
        m.add_face([V(0, y0, z0), V(0, y1, z1), V(L, y1, z1), V(L, y0, z0)])
    return m


def test_the_class_is_offered():
    assert "IfcReinforcingBar" in IFC_CLASSES


def test_a_bar_reads_its_length_diameter_and_weight():
    qset, entries, (metrado, unit) = class_quantities(
        "IfcReinforcingBar", _bar().faces)
    got = {name: val for _kind, name, val in entries}
    assert qset == "Qto_ReinforcingElementBaseQuantities"
    assert got["Length"] == pytest.approx(L)
    # a 24-gon holds a little less than the circle
    assert got["NominalDiameter"] == pytest.approx(D, rel=0.02)
    kg = math.pi * D * D / 4 * L * STEEL_DENSITY       # 9.47 kg
    assert got["Weight"] == pytest.approx(kg, rel=0.03)
    assert unit == "kg" and metrado == pytest.approx(got["Weight"])


def test_the_bar_exports_to_ifc(tmp_path):
    scene = Scene()
    g = Group(_bar(), name="N1 Ø16")
    scene.groups.append(g)
    tag_group(g, "IfcReinforcingBar", "N1 Ø16")
    path = tmp_path / "barra.ifc"
    assert save_ifc(scene, path) == 1
    text = path.read_text()
    assert "IFCREINFORCINGBAR(" in text
    assert "Qto_ReinforcingElementBaseQuantities" in text
    assert "IFCQUANTITYWEIGHT('Weight'" in text
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.validate
    f = ifcopenshell.open(str(path))
    bar = f.by_type("IfcReinforcingBar")[0]
    assert bar.NominalDiameter == pytest.approx(D, rel=0.02)
    assert bar.BarLength == pytest.approx(L)
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, log)
    assert log.statements == []
