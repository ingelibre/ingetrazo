# SPDX-License-Identifier: GPL-3.0-or-later
"""Adversarial regressions for the normal-export storey contribution."""

import pytest

from core.group import Group
from core.mesh import Mesh
from formats.ifc import save_ifc
from tests.test_ifc_storeys import _add, _export, _scene


def test_default_storey_keeps_the_original_step_entity_order(tmp_path):
    scene = _scene()
    _add(scene, "IfcWall", "Wall", 0.0)
    model = _export(tmp_path, scene)
    (building,) = model.by_type("IfcBuilding")
    (storey,) = model.by_type("IfcBuildingStorey")
    assert storey.id() == building.id() + 1
